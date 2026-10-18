"""Private model input requires completed, exact-version immutable identities."""
# ruff: noqa: F811
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models import ChapterReadReceipt
from app.services.chapter_document import from_text
from app.services.private_reading_evidence import verified_chapters
from app.services.reading_progress_service import save_reading_progress
from tests.contracts.test_chapter_identity import captured, original  # noqa: F401
from tests.routes.conftest import db, test_user, test_library, client, auth_headers  # noqa: F401


def evidence(db, user, novel):
    _, chapters = verified_chapters(db, user.id, novel.id)
    return list(chapters)


def save(db, user, chapter, percent, **kwargs):
    return save_reading_progress(db, user_id=user.id, chapter=chapter,
                                 position=0, percent=percent, **kwargs)


def test_lifetime_receipt_and_old_completion_cannot_authorize_revised_text(db, test_user, original):
    novel, chapter = original
    save(db, test_user, chapter, 100, content_version=chapter.document['content_version'])
    assert len(evidence(db, test_user, novel)) == 1
    chapter.content = 'New text that has only been half read.'
    chapter.document = from_text(chapter.content)
    version = chapter.document['content_version']
    db.add(ChapterReadReceipt(user_id=test_user.id, chapter_id=chapter.id,
                             content_version=version, completed=True, requires_review=False))
    db.commit()
    save(db, test_user, chapter, 50, content_version=version)
    assert evidence(db, test_user, novel) == []
    save(db, test_user, chapter, 100)
    assert evidence(db, test_user, novel) == []
    save(db, test_user, chapter, 100, content_version=version, intent='confirm_read')
    approved = evidence(db, test_user, novel)
    assert len(approved) == 1
    assert approved[0].chapter_key == chapter.chapter_key
    assert approved[0].document['content_version'] == version


def test_receipt_foreign_identity_never_authorizes_same_numeric_chapter(db, test_user, original):
    novel, chapter = original
    save(db, test_user, chapter, 100, content_version=chapter.document['content_version'])
    assert len(evidence(db, test_user, novel)) == 1
    db.execute(text('UPDATE chapter_read_receipts SET chapter_key = :key WHERE chapter_id = :id'),
               {'key': str(uuid4()), 'id': chapter.id})
    db.commit()
    assert evidence(db, test_user, novel) == []


def test_legacy_plain_text_requires_exact_verified_version(db, test_user, original):
    novel, chapter = original
    save(db, test_user, chapter, 100, content_version=chapter.document['content_version'])
    chapter.document = None
    db.commit()
    assert len(evidence(db, test_user, novel)) == 1
    chapter.content = 'A different plain text revision is not approved.'
    db.commit()
    assert evidence(db, test_user, novel) == []


@pytest.mark.parametrize('field,value', [
    ('expected_chapter_key', str(uuid4())),
    ('expected_manifest_epoch', str(uuid4())),
    ('expected_manifest_revision', '999999'),
    ('expected_content_version', 'f' * 64),
])
def test_explicit_confirm_read_rejects_stale_identity_without_creating_evidence(
        client, db, test_user, original, auth_headers, field, value):
    novel, chapter = original
    payload = captured(chapter) | {'content_version': chapter.document['content_version']}
    payload[field] = value
    response = client.post(f'/reader/companion/{novel.id}/chapters/1/confirm-read',
                           json=payload, headers=auth_headers)
    assert response.status_code == 409
    db.rollback()
    assert db.query(ChapterReadReceipt).filter_by(user_id=test_user.id).count() == 0
    assert evidence(db, test_user, novel) == []


@pytest.mark.parametrize('change', ['revised', 'archived', 'renumbered', 'unchanged', 'disabled', 'provider_changed'])
def test_question_revalidates_evidence_and_server_binds_citation_identity(
        client, db, test_user, original, auth_headers, monkeypatch, change):
    import json
    from config.settings import settings
    from app.models.companion_answer import CompanionAnswer
    from tests.routes.test_reader_tools import provider
    novel, chapter = original
    original_document = chapter.document
    chapter_key = chapter.chapter_key
    save(db, test_user, chapter, 100, content_version=original_document['content_version'])
    provider_id = provider(client, auth_headers, monkeypatch)
    monkeypatch.setattr(settings, 'ANALYSIS_ENGINE_URL', 'http://synthetic.invalid')
    monkeypatch.setattr(settings, 'ANALYSIS_ENGINE_API_KEY', 'synthetic-test-key')

    def answer(_db, _provider, *, prompt, **kwargs):
        # The provider receives story evidence, never authority to choose UUIDs.
        assert chapter_key not in prompt
        if change == 'revised':
            chapter.content = 'A new unapproved version during inference.'
            chapter.document = from_text(chapter.content)
        elif change == 'archived':
            chapter.archived = True
        elif change == 'renumbered':
            chapter.chapter_number = 9
        elif change == 'disabled':
            test_user.is_disabled = True
        elif change == 'provider_changed':
            _provider.model = 'A different provider model'
        db.commit()
        return json.dumps({'answer': 'Original private words', 'citations': [{
            'chapter': 1, 'block_id': original_document['blocks'][0]['id'],
            'quote': 'Original private words', 'chapter_key': str(uuid4())}]}), 1, 1, 0

    monkeypatch.setattr('app.services.reader_provider.invoke', answer)
    response = client.post(f'/reader/companion/{novel.id}/questions',
        json={'provider_id': provider_id, 'question': 'Original words?'}, headers=auth_headers)
    if change in {'revised', 'archived', 'disabled', 'provider_changed'}:
        assert response.status_code == (401 if change == 'disabled' else 409)
        if change != 'disabled':
            assert response.json()['detail']['code'] == ('provider_configuration_changed' if change == 'provider_changed' else 'companion_evidence_changed')
        assert db.query(CompanionAnswer).count() == 0
    else:
        assert response.status_code == 200, response.text
        citation = response.json()['citations'][0]
        assert citation['chapter_key'] == chapter_key
        assert citation['chapter'] == (9 if change == 'renumbered' else 1)
        assert citation['source_version'] == original_document['content_version']
