"""Actual in-flight model returns cannot retarget chapter lifecycle proof."""
# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json

import pytest
from sqlalchemy import delete

from app.models import Chapter
from app.models.reader_guide import PrivateGuideArtifact, PrivateGuideJob
from app.models.translation import ReaderProviderRequest
from app.schemas.reader_guide import GuideCreate
from app.services import reader_guide_service as guide
from app.services.reading_progress_service import save_reading_progress
from tests.contracts.test_chapter_identity import captured
from tests.database.test_private_guide_postgres import seed
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


@pytest.mark.parametrize('replace_lifecycle', [False, True])
def test_provider_return_after_renumber_or_identical_replacement(run_engine, monkeypatch, replace_lifecycle):
    sessions, (user_id, novel_id, provider_id), preview = seed(run_engine, monkeypatch)
    with sessions() as db:
        queued = guide.queue(db, user_id, novel_id, GuideCreate(provider_id=provider_id,
            review_token=preview['review_token'], operation_id='identity-race'))
        chapter = db.query(Chapter).filter_by(novel_id=novel_id).one()
        original_id, original_key, document = chapter.id, chapter.chapter_key, chapter.document
    dispatched, release = Event(), Event()
    calls = []

    def transport(provider, **kwargs):
        payload = json.loads(kwargs['prompt'])
        calls.append(payload)
        evidence = payload['evidence'][0]
        if len(calls) == 1:
            dispatched.set()
            assert release.wait(timeout=15)
        citation = {'chapter': evidence['chapter'], 'block_id': evidence['block_id'], 'quote': evidence['text']}
        return {'choices': [{'message': {'content': json.dumps(dict(characters=[], relationships=[], locations=[],
            glossary=[], recap=None, citations=[citation]))}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}

    monkeypatch.setattr('app.services.companion_client.guide_request', transport)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(guide.process_one, sessions)
        try:
            assert dispatched.wait(timeout=15)
            with sessions() as db:
                # This transaction must finish while the provider is waiting:
                # no database transaction may span model I/O.
                if replace_lifecycle:
                    db.execute(delete(Chapter).where(Chapter.id == original_id))
                    db.commit()
                    chapter = Chapter(id=original_id, novel_id=novel_id, chapter_number=-2, title='Replacement',
                        content=document['plain_text'], document=document)
                    db.add(chapter)
                    db.commit()
                    assert chapter.chapter_key != original_key
                    save_reading_progress(db, user_id=user_id, chapter=chapter, position=0, percent=100,
                        content_version=document['content_version'], intent='confirm_read', **captured(chapter))
                else:
                    db.query(Chapter).filter_by(id=original_id).one().chapter_number = -9
                    db.commit()
        finally:
            release.set()
        assert running.result(timeout=15)

    with sessions() as db:
        # A response already billed upstream remains recorded even if its
        # source authority disappeared before it returned.
        assert db.query(ReaderProviderRequest).one().status == 'completed'
        if replace_lifecycle:
            assert db.get(PrivateGuideJob, queued['id']).status == 'needs_review'
            assert db.query(PrivateGuideArtifact).count() == 0
            assert guide.state(db, user_id, novel_id)['artifacts'] == []
        else:
            assert db.get(PrivateGuideJob, queued['id']).completed_steps == 1
    if replace_lifecycle:
        assert not guide.process_one(sessions)
        assert len(calls) == 1
    else:
        assert guide.process_one(sessions)
        assert not guide.process_one(sessions)
        with sessions() as db:
            state = guide.state(db, user_id, novel_id)
            citation = state['artifacts'][0]['citations'][0]
            assert citation['chapter'] == -9 and citation['chapter_key'] == original_key
            assert db.query(ReaderProviderRequest).count() == 2
        assert len(calls) == 2
        assert all(item['evidence'][0]['chapter'] == -2 for item in calls)
