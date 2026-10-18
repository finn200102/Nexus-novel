"""Exercise real HTTP serialization, not DTO-shaped copies of route responses."""
# Imported pytest fixtures are intentionally injected by argument name below.
# ruff: noqa: F811
from copy import deepcopy

import pytest

from app.models import Chapter, Library, Novel, ReadingProgress, User
from app.models.chapter import ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.services.chapter_document import content_version, from_html, from_text
from app.services.chapter_version_service import retain_current
from app.services.chapter_identity_service import identity
from tests.routes.conftest import auth_headers, client, db, test_library, test_user  # noqa: F401


@pytest.fixture
def story(db, test_library):
    novel = Novel(library_id=test_library.id, title="Private wire fixture")
    db.add(novel)
    db.flush()
    document = from_html('<h2>Opening</h2><p>😀 A <em>quiet</em> story.</p>'
        '<ul><li>One</li><li>Two</li></ul><table><tr><td>Map</td></tr></table>'
        '<p><a href="https://example.test/map">Map</a><img alt="Map" src="data:image/png;base64,AAAA"></p>'
        '<hr><aside class="author-note"><p>Author commentary.</p></aside>')
    document['image_assets'] = {'total': 2, 'ready': 1, 'missing': 1, 'bytes': 3,
        'failures': {'prohibited_host': 1}}
    # Public document extensions must survive wire validation verbatim.
    document['blocks'][1]['future_alignment'] = {'utf16': [0, 3], 'optional': None}
    document['future_asset_metadata'] = {'nested': [None, False, {'mime': 'image/png'}]}
    chapter = Chapter(novel_id=novel.id, chapter_number=3, title="Rich original",
        content=document['plain_text'], document=document, source_url='https://example.test/chapter/3',
        content_status=ContentStatus.PRESENT)
    db.add(chapter)
    db.commit()
    return novel, chapter, deepcopy(document)


def test_original_and_retained_versions_preserve_exact_documents(client, db, story, test_library, auth_headers):
    novel, chapter, original = story
    assert any(block.get('role') == 'author_note' for block in original['blocks'])
    assert original['content_version'] == content_version(original['blocks'])
    url = f'/chapter/content/library/{test_library.id}/{novel.id}/3'
    expected = dict(id=chapter.id, novel_id=novel.id, chapter_number=3, title=chapter.title,
        content=original['plain_text'], source_url=chapter.source_url, document=original,
        **identity(chapter), source_version=original['content_version'],
        current_content_version=original['content_version'])
    response = client.get(url, headers=auth_headers)
    assert response.status_code == 200 and response.json() == expected
    retain_current(db, chapter)
    replacement = from_html('<p>Replacement, with a different fingerprint.</p>')
    chapter.document = replacement
    chapter.content = replacement['plain_text']
    chapter.title = 'Revised title'
    db.commit()
    versions_url = f'/chapter/versions/{novel.id}/3'
    saved = client.get(f"{versions_url}/{original['content_version']}", headers=auth_headers)
    assert saved.status_code == 200 and saved.json() == {**expected,
        **identity(chapter), 'current_content_version': replacement['content_version']}
    assert saved.json()['document'] == original
    assert saved.json()['source_version'] == original['content_version']
    current = client.get(f"{versions_url}/{replacement['content_version']}", headers=auth_headers)
    assert current.status_code == 200 and current.json()['document'] == replacement
    assert client.get(url, headers=auth_headers).json()['document'] == replacement
    versions = client.get(versions_url, headers=auth_headers).json()
    assert versions['current_version'] == replacement['content_version']
    assert [(row['content_version'], row['current']) for row in versions['versions']] == [
        (replacement['content_version'], True), (original['content_version'], False)]
    db.refresh(chapter)
    assert chapter.document == replacement  # Reads never rewrite originals.


def test_plain_text_legacy_read_and_missing_progress_keep_nulls(client, db, story, test_library, auth_headers):
    novel, chapter, _ = story
    chapter.document = None
    chapter.content = 'Old text <literal>\nSecond paragraph.'
    chapter.title = None
    chapter.source_url = None
    db.commit()
    assert client.get(f'/chapter/progress/{novel.id}', headers=auth_headers).content == b'null'
    response = client.get(f'/chapter/content/library/{test_library.id}/{novel.id}/3', headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body['content'] == chapter.content and body['source_url'] is None
    assert body['title'] == 'Chapter 3' and body['document'] == from_text(chapter.content)
    db.refresh(chapter)
    assert chapter.document is None
    legacy = ReadingProgress(user_id=test_library.user_id, novel_id=novel.id, chapter_id=chapter.id,
        chapter_number=3, position=91, percent=12)
    db.add(legacy)
    db.commit()
    payload = client.get(f'/chapter/progress/{novel.id}', headers=auth_headers).json()
    assert payload['reading_run_key'] is None and payload['block_id'] is None
    assert payload['locator_content_version'] is None and payload['locator_variant'] is None
    assert (payload['position'], payload['percent'], payload['revision']) == (91, 12, 0)


def test_progress_revision_run_operation_and_unicode_locator_roundtrip(client, story, auth_headers):
    novel, _, document = story
    block = document['blocks'][1]
    url = f'/chapter/progress/{novel.id}'
    request = dict(chapter_number=3, position=24, percent=20, expected_revision=0,
        operation_id='chapter-wire-save', device_id='wire-device', block_id=block['id'],
        text_offset=3, text_quote='A quiet story.', quote_prefix='😀 ', quote_suffix='',
        content_version=document['content_version'], locator_variant='original', reading_run_key=None)
    first = client.put(url, headers=auth_headers, json=request)
    assert first.status_code == 200
    saved = first.json()
    assert saved['reading_run_key'] and saved['revision'] == 1
    for field in ('block_id', 'text_offset', 'text_quote', 'quote_prefix', 'quote_suffix', 'locator_variant'):
        assert saved[field] == request[field]
    assert saved['locator_content_version'] == document['content_version']
    assert client.put(url, headers=auth_headers, json=request).json() == saved
    assert client.get(url, headers=auth_headers).json() == saved
    stale = client.put(url, headers=auth_headers, json={**request, 'operation_id': 'chapter-wire-stale',
        'reading_run_key': saved['reading_run_key'], 'percent': 30})
    assert stale.status_code == 409
    assert client.get(url, headers=auth_headers).json() == saved
    second = client.put(url, headers=auth_headers, json={**request, 'operation_id': 'chapter-wire-next',
        'reading_run_key': saved['reading_run_key'], 'expected_revision': 1, 'percent': 30})
    assert second.status_code == 200 and second.json()['revision'] == 2
    assert second.json()['reading_run_key'] == saved['reading_run_key']


def test_annotation_locator_null_legacy_and_empty_204_delete(client, story, auth_headers):
    novel, _, document = story
    url = f'/chapter/annotations/{novel.id}'
    anchor = dict(block_id=document['blocks'][1]['id'], text_offset=3, text_quote='A quiet story.',
        quote_prefix='😀 ', quote_suffix='', locator_content_version=document['content_version'], locator_variant='original')
    response = client.post(url, headers=auth_headers, json=dict(chapter_number=3, annotation_type='highlight',
        quote='A quiet story.', note='<em>Literal private note</em>', **anchor))
    assert response.status_code == 201
    annotation = response.json()
    assert all(annotation[key] == value for key, value in anchor.items())
    assert annotation['note'] == '<em>Literal private note</em>'
    legacy = client.post(url, headers=auth_headers, json={'chapter_number': 3}).json()
    assert legacy['block_id'] is None and legacy['locator_content_version'] is None and legacy['quote'] is None
    assert {row['id'] for row in client.get(url, headers=auth_headers).json()} == {annotation['id'], legacy['id']}
    deleted = client.delete(f"/chapter/annotations/{annotation['id']}", headers=auth_headers)
    assert deleted.status_code == 204 and deleted.content == b''
    assert [row['id'] for row in client.get(url, headers=auth_headers).json()] == [legacy['id']]


@pytest.mark.parametrize('empty', [False, True])
@pytest.mark.parametrize('method,path', [('get', 'download-status'), ('post', 'cancel-all-downloads'), ('get', 'recap')])
def test_foreign_empty_or_populated_story_operations_are_private(client, db, auth_headers, empty, method, path):
    user = User(username='foreign-wire-owner', password='unused')
    db.add(user); db.flush()
    library = Library(user_id=user.id, name='Private foreign library')
    db.add(library); db.flush()
    novel = Novel(library_id=library.id, title='Foreign story')
    db.add(novel); db.flush()
    chapter = job = None
    if not empty:
        chapter = Chapter(novel_id=novel.id, chapter_number=3, title='PRIVATE ACTIVE TITLE', content_status=ContentStatus.PROCESSING)
        db.add(chapter); db.flush()
        job = ChapterDownloadJob(user_id=user.id, library_id=library.id, novel_id=novel.id,
            chapter_id=chapter.id, status='processing', attempt_count=2, lease_owner='foreign-worker')
        db.add(job)
    db.commit()
    url = f'/chapter/recap/{novel.id}' if path == 'recap' else f'/chapter/novel/{novel.id}/{path}'
    response = getattr(client, method)(url, headers=auth_headers)
    assert response.status_code == 404 and 'PRIVATE ACTIVE TITLE' not in response.text
    if chapter:
        db.refresh(chapter); db.refresh(job)
        assert chapter.content_status == ContentStatus.PROCESSING
        assert (job.status, job.attempt_count, job.lease_owner) == ('processing', 2, 'foreign-worker')
    missing = '/chapter/recap/99999999' if path == 'recap' else f'/chapter/novel/99999999/{path}'
    assert getattr(client, method)(missing, headers=auth_headers).status_code == 404


def test_recap_reread_zero_boundary_does_not_expose_prior_run_titles_or_notes(client, db, story, auth_headers):
    novel, chapter, document = story
    progress_url = f'/chapter/progress/{novel.id}'
    finished = client.put(progress_url, headers=auth_headers, json=dict(chapter_number=3, percent=100,
        expected_revision=0, operation_id='wire-first-finish', content_version=document['content_version']))
    assert finished.status_code == 200
    saved = finished.json()
    annotation = client.post(f'/chapter/annotations/{novel.id}', headers=auth_headers,
        json=dict(chapter_number=3, annotation_type='note', note='PRIOR RUN NOTE'))
    assert annotation.status_code == 201
    previous = client.get(f'/chapter/recap/{novel.id}', headers=auth_headers).json()
    assert previous['spoiler_boundary_chapter'] == 3 and previous['chapters']
    restarted = client.post(f'/reading/stories/{novel.id}/runs/start', headers=auth_headers,
        json=dict(expected_revision=saved['revision'], operation_id='wire-reread-start',
            reading_run_key=saved['reading_run_key']))
    assert restarted.status_code == 200
    assert restarted.json()['current_progress']['furthest_chapter_number'] == 0
    # Imported legacy numbering can contain zero/negative chapters: zero is
    # the unread boundary, never permission to reveal those earlier rows.
    db.add_all([Chapter(novel_id=novel.id, chapter_number=number, title=f'PRIVATE NONPOSITIVE {number}',
        content='Prior source text', content_status=ContentStatus.PRESENT) for number in (-1, 0)])
    db.commit()
    for restore_from_snapshot in (False, True):
        if restore_from_snapshot:
            db.query(ReadingProgress).filter_by(novel_id=novel.id).delete()
            db.commit()
        recap = client.get(f'/chapter/recap/{novel.id}', headers=auth_headers)
        assert recap.status_code == 200
        assert recap.json()['spoiler_boundary_chapter'] is None
        assert recap.json()['chapters'] == [] and recap.json()['annotations'] == []
        assert chapter.title not in recap.text and 'PRIOR RUN NOTE' not in recap.text
        assert 'PRIVATE NONPOSITIVE' not in recap.text


def test_sparse_stored_document_extensions_are_not_defaulted_or_sanitized_again(client, db, story, test_library, auth_headers):
    novel, chapter, _ = story
    sparse = {'schema_version': 1, 'content_version': 'a' * 64,
        'blocks': [{'id': 'stable-legacy-id', 'html': '<p>Legacy <b>markup</b></p>',
            'text': 'Legacy markup', 'role': None, 'future_block': {'keep': True}}],
        'plain_text': 'Legacy markup', 'image_assets': {'ready': 1, 'future_asset_flag': False},
        'future_document': [None, 'preserve']}
    chapter.document = deepcopy(sparse)
    chapter.content = sparse['plain_text']
    db.commit()
    for url in (f'/chapter/content/library/{test_library.id}/{novel.id}/3',
            f"/chapter/versions/{novel.id}/3/{sparse['content_version']}"):
        response = client.get(url, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()['document'] == sparse
    db.refresh(chapter)
    assert chapter.document == sparse
