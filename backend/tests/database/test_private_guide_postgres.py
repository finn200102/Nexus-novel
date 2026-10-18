"""Real PostgreSQL races for private guide dispatch and reviewed submission."""
# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import json
import pytest
from sqlalchemy.orm import sessionmaker
from app.models import User, Library, Novel, Chapter
from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact
from app.models.translation import ReaderProvider, ReaderProviderRequest
from app.schemas.reader_guide import GuideInput, GuideCreate, GuideAction
from app.services import reader_guide_service as guide
from app.services.chapter_document import from_text
from app.services.reading_progress_service import save_reading_progress
from config.database import Base
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


def seed(engine, monkeypatch):
    if engine.dialect.name != 'postgresql':
        pytest.skip('Actual row-lock race requires PostgreSQL')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL', 'http://private-guide.invalid/v1')
    with sessions() as db:
        user = User(username='guide-race', password='unused')
        db.add(user)
        db.flush()
        library = Library(name='private', user_id=user.id)
        db.add(library)
        db.flush()
        novel = Novel(title='Signed guide race', library_id=library.id)
        db.add(novel)
        db.flush()
        document = from_text('Alice enters the harbour.')
        chapter = Chapter(novel_id=novel.id, chapter_number=-2, title='Prologue', content=document['plain_text'], document=document)
        provider = ReaderProvider(user_id=user.id, name='Local', kind='local', base_url='http://private-guide.invalid/v1', model='fixture', capabilities=['guide_text'])
        db.add_all([chapter, provider])
        db.commit()
        save_reading_progress(db, user_id=user.id, chapter=chapter, position=0, percent=100, content_version=document['content_version'])
        ids = user.id, novel.id, provider.id
        preview = guide.preview(db, user.id, novel.id, GuideInput(provider_id=provider.id))
    return sessions, ids, preview


@pytest.mark.parametrize('same_operation', [False, True])
def test_reviewed_creation_serializes_same_and_different_operations(run_engine, monkeypatch, same_operation):
    sessions, (user_id, novel_id, provider_id), preview = seed(run_engine, monkeypatch)
    barrier = Barrier(2)
    def submit(index):
        with sessions() as db:
            barrier.wait(timeout=10)
            return guide.queue(db, user_id, novel_id, GuideCreate(provider_id=provider_id,
                review_token=preview['review_token'], operation_id='same' if same_operation else f'create-{index}'))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, [1,2]))
    assert results[0]['id'] == results[1]['id']
    calls = []
    def transport(provider, **kwargs):
        value = json.loads(kwargs['prompt'])
        calls.append(value['operation'])
        first = value['evidence'][0]
        citation = {'chapter':first['chapter'],'block_id':first['block_id'],'quote':first['text']}
        return {'choices':[{'message':{'content':json.dumps(dict(characters=[],relationships=[],locations=[],glossary=[],recap=None,citations=[citation]))},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':5}}
    monkeypatch.setattr('app.services.companion_client.guide_request',transport)
    assert guide.process_one(sessions)
    assert guide.process_one(sessions)
    assert not guide.process_one(sessions)
    with sessions() as db:
        assert db.query(PrivateGuideJob).count() == 1
        assert db.query(ReaderProviderRequest).count() == 2
    assert calls == ['extract','synthesize']


def test_cancel_during_actual_ledger_dispatch_fences_returned_artifact(run_engine, monkeypatch):
    sessions, (user_id, novel_id, provider_id), preview = seed(run_engine, monkeypatch)
    with sessions() as db:
        job = guide.queue(db, user_id, novel_id, GuideCreate(provider_id=provider_id,
            review_token=preview['review_token'], operation_id='queue'))
    dispatched, release = Event(), Event()
    def transport(provider, **kwargs):
        value = json.loads(kwargs['prompt'])
        evidence = value['evidence'][0]
        citation = {'chapter': evidence['chapter'], 'block_id': evidence['block_id'], 'quote': evidence['text']}
        dispatched.set()
        assert release.wait(timeout=10)
        return {'choices': [{'message': {'content': json.dumps(dict(characters=[], relationships=[], locations=[], glossary=[], recap=None, citations=[citation]))}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    monkeypatch.setattr('app.services.companion_client.guide_request', transport)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(guide.process_one, sessions)
        try:
            assert dispatched.wait(timeout=10)
            assert not guide.process_one(sessions)
            with sessions() as db:
                current = db.get(PrivateGuideJob, job['id'])
                canceled = guide.action(db, user_id, novel_id, job['id'], GuideAction(
                    expected_revision=current.revision, operation_id='cancel-during-request'), 'cancel')
                assert canceled['status'] == 'canceled'
        finally:
            release.set()
        assert running.result(timeout=10)
    with sessions() as db:
        assert db.get(PrivateGuideJob, job['id']).status == 'canceled'
        assert db.query(PrivateGuideArtifact).count() == 0
        assert db.query(ReaderProviderRequest).one().status == 'completed'
        state = guide.state(db, user_id, novel_id)
        assert state['through_chapter'] == -2 and state['artifacts'] == []


def test_large_confirmed_charge_is_preserved_without_post_billing_overflow(run_engine, monkeypatch):
    from uuid import uuid4
    from app.services.reader_provider_usage import snapshot
    sessions, (user_id, novel_id, provider_id), preview = seed(run_engine, monkeypatch)
    with sessions() as db:
        job = guide.queue(db, user_id, novel_id, GuideCreate(provider_id=provider_id,
            review_token=preview['review_token'], operation_id='large-charge'))
    def invoke(db, provider, **kwargs):
        kwargs['authorize']()
        first = json.loads(kwargs['prompt'])['evidence'][0]
        citation = {'chapter':first['chapter'],'block_id':first['block_id'],'quote':first['text']}
        return json.dumps(dict(characters=[],relationships=[],locations=[],glossary=[],recap=None,citations=[citation])), 10, 5, 3_000_000_000
    monkeypatch.setattr(guide.reader_provider,'invoke',invoke)
    assert guide.process_one(sessions)
    with sessions() as db:
        row = db.get(PrivateGuideJob, job['id'])
        assert row.completed_steps == 1 and row.charged_microusd == 3_000_000_000
        provider = db.get(ReaderProvider, provider_id)
        db.add(ReaderProviderRequest(request_key=str(uuid4()),user_id=user_id,provider_id=provider_id,
            model_snapshot=snapshot(provider),status='completed',revision=1,reserved_microusd=0,actual_microusd=3_000_000_000,
            purpose='guide_extract',job_key=row.job_key,item_key='0',retry_generation=0))
        db.commit()
        assert guide.job_view(db,row)['charged_microusd'] == 3_000_000_000


@pytest.mark.parametrize('same_operation', [False, True])
def test_reviewed_retry_serializes_and_keeps_one_request_generation(run_engine, monkeypatch, same_operation):
    from app.schemas.reader_guide import GuideRetry
    from fastapi import HTTPException
    sessions, (user_id,novel_id,provider_id), preview = seed(run_engine,monkeypatch)
    with sessions() as db:
        job = guide.queue(db,user_id,novel_id,GuideCreate(provider_id=provider_id,
            review_token=preview['review_token'],operation_id='initial'))
        stopped = guide.action(db,user_id,novel_id,job['id'],GuideAction(expected_revision=job['revision'],operation_id='stop'),'cancel')
        reviewed = guide.preview(db,user_id,novel_id,GuideInput.model_validate(stopped['retry_input']))
    barrier = Barrier(2)
    def retry(index):
        with sessions() as db:
            barrier.wait(timeout=10)
            try:
                return guide.action(db,user_id,novel_id,job['id'],GuideRetry(expected_revision=stopped['revision'],
                    operation_id='same-retry' if same_operation else f'retry-{index}',review_token=reviewed['review_token']),'retry')
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(retry,[1,2]))
    assert sum(isinstance(item,dict) for item in results) == (2 if same_operation else 1)
    if not same_operation:
        assert 409 in results
    with sessions() as db:
        row = db.get(PrivateGuideJob,job['id'])
        assert row.status == 'queued' and row.retry_generation == 1
        assert db.query(PrivateGuideJob).count() == 1 and db.query(ReaderProviderRequest).count() == 0
