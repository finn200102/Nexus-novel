"""Guides retain reviewed originals; citation labels never supply identity."""
# ruff: noqa: F811
from sqlalchemy import delete

from app.models import Chapter
from app.models.reader_guide import PrivateGuideArtifact, PrivateGuideJob
from app.services import reader_guide_service as guide
from app.services.reading_progress_service import save_reading_progress
from tests.contracts.test_chapter_identity import captured
from tests.routes.test_private_guides import material, prepare, complete, factory  # noqa: F401
from tests.routes.conftest import db, test_user, test_library, client, auth_headers  # noqa: F401


def renumber(db, chapters):
    chapters[0].chapter_number = -1
    chapters[1].chapter_number = 1
    db.commit()


def test_queued_guide_retains_exact_reviewed_input_after_renumber(client, db, auth_headers, material, monkeypatch):
    _, chapters, _, _ = material
    base, _, _ = prepare(client, auth_headers, material, -2)
    original_key = chapters[0].chapter_key
    renumber(db, chapters)
    calls = complete(db, monkeypatch)
    assert len(calls) == 2
    assert calls[0]['evidence'][0]['chapter'] == -2
    state = client.get(base, headers=auth_headers)
    assert state.status_code == 200, state.text
    citation = state.json()['artifacts'][0]['citations'][0]
    assert citation['chapter'] == -1 and citation['chapter_key'] == original_key
    assert citation['source_version'] == chapters[0].document['content_version']
    assert original_key not in str(calls)


def test_completed_guide_and_nested_citations_reproject_without_new_inference(client, db, auth_headers, material, monkeypatch):
    _, chapters, provider, _ = material
    base, _, job = prepare(client, auth_headers, material)
    calls = complete(db, monkeypatch)
    renumber(db, chapters)
    provider.enabled = False
    db.commit()
    response = client.get(base, headers=auth_headers)
    assert response.status_code == 200, response.text
    artifact = response.json()['artifacts'][0]
    citation = artifact['citations'][0]
    assert citation['chapter_key'] == chapters[0].chapter_key and citation['chapter'] == -1
    assert artifact['content']['recap']['citations'][0] == citation
    assert client.get(base + f'/artifacts/{artifact["id"]}', headers=auth_headers).json()['citations'][0] == citation
    reuse = client.post(base + '/preview', headers=auth_headers, json={'provider_id': provider.id})
    assert reuse.status_code == 200, reuse.text
    assert reuse.json()['reuse_job_id'] == job['id']
    assert len(calls) == 2 and db.query(PrivateGuideJob).count() == 1


def test_same_numeric_id_and_identical_text_cannot_retarget_a_saved_guide(client, db, test_user, auth_headers, material, monkeypatch):
    novel, chapters, _, _ = material
    base, _, _ = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    original = chapters[0]
    old_id, old_key, document = original.id, original.chapter_key, original.document
    db.expunge(original)
    db.execute(delete(Chapter).where(Chapter.id == old_id).execution_options(synchronize_session=False))
    db.commit()
    replacement = Chapter(id=old_id, novel_id=novel.id, chapter_number=-2, title='Same numeric address',
                          content=document['plain_text'], document=document)
    db.add(replacement)
    db.commit()
    assert replacement.chapter_key != old_key
    save_reading_progress(db, user_id=test_user.id, chapter=replacement, position=0, percent=100,
        content_version=document['content_version'], intent='confirm_read', **captured(replacement))
    response = client.get(base, headers=auth_headers)
    assert response.status_code == 200 and response.json()['artifacts'] == []
    assert db.query(PrivateGuideArtifact).count() == 2


def test_legacy_unproven_guide_is_retained_and_explicitly_needs_review(client, db, auth_headers, material, monkeypatch):
    base, _, queued = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    job = db.get(PrivateGuideJob, queued['id'])
    review = dict(job.review)
    review['proof'] = [row[:4] for row in review['proof']]
    job.review = review
    job.cache_key = 'a' * 64
    db.commit()
    response = client.get(base, headers=auth_headers)
    assert response.status_code == 200, response.text
    saved = response.json()['jobs'][0]
    assert saved['identity_review_required'] and saved['error_code'] == 'guide_identity_review_required'
    assert saved['artifacts'] == [] and db.query(PrivateGuideArtifact).count() == 2


def test_provider_schema_cannot_supply_server_chapter_keys():
    from pydantic import ValidationError
    import pytest
    from app.schemas.reader_guide import GuideCitation
    with pytest.raises(ValidationError):
        GuideCitation.model_validate({'chapter': -2, 'block_id': 'block', 'quote': 'A quoted observation',
                                      'chapter_key': '00000000-0000-0000-0000-000000000000'})


def test_guide_never_sends_author_note_spoilers_to_provider(client, db, test_user, auth_headers, material, monkeypatch):
    from app.services.chapter_document import from_html
    _, chapters, _, _ = material
    chapter = chapters[0]
    chapter.document = from_html('<p>Alice wears a blue coat.</p><aside class="author-note"><p>FUTURE_SECRET reveals the ending.</p></aside>')
    chapter.content = chapter.document['plain_text']
    db.commit()
    save_reading_progress(db, user_id=test_user.id, chapter=chapter, position=0, percent=100,
        content_version=chapter.document['content_version'], intent='confirm_read', **captured(chapter))
    base, _, _ = prepare(client, auth_headers, material, -2)
    calls = complete(db, monkeypatch)
    assert len(calls) == 2
    assert all('FUTURE_SECRET' not in str(call) for call in calls)
    assert client.get(base, headers=auth_headers).json()['artifacts']
