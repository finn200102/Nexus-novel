from pathlib import Path
from uuid import uuid4
import pytest
from app.models import Chapter, Novel, User, Library
from app.models.chapter import ContentStatus
from app.models.audio_job import ChapterAudioJob
from app.models.translation import ReaderProvider, TranslationJob
from app.services.chapter_document import from_html


@pytest.fixture
def offline_story(db, test_user, test_library, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline copying must not generate audio or request paid processing')
    monkeypatch.setattr('app.services.reader_provider.invoke', forbidden)
    monkeypatch.setattr('app.services.audio_job_service.queue_audio_job', forbidden)
    novel = Novel(library_id=test_library.id, title='Private offline fixture')
    provider = ReaderProvider(user_id=test_user.id, name='Fixture', kind='local', base_url='http://unused', model='fixture')
    db.add_all([novel, provider]); db.flush()
    document = from_html('<p>PRIVATE_ORIGINAL_TEXT</p><aside class="author-note"><p>Retained note</p></aside>')
    chapter = Chapter(novel_id=novel.id, chapter_number=3, title='Private opening', content=document['plain_text'],
        document=document, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    from app.services.chapter_identity_service import identity
    proof = identity(chapter)
    path = tmp_path / 'completed.wav'; path.write_bytes(b'completed-recording')
    audio = ChapterAudioJob(user_id=test_user.id, library_id=test_library.id, novel_id=novel.id, chapter_id=chapter.id,
        **proof,
        source_version=document['content_version'], status='completed', audio_path=str(path),
        provider_id='custom', provider_url='http://unused', provider_model='fixture', provider_voice='fixture')
    translated = [{**block, 'text': 'PRIVATE_TRANSLATED_TEXT', 'html': '<p>PRIVATE_TRANSLATED_TEXT</p>'} for block in document['blocks']]
    job = TranslationJob(user_id=test_user.id, novel_id=novel.id, chapter_id=chapter.id, provider_id=provider.id,
        **proof,
        language='de', source_version=document['content_version'], fingerprint=uuid4().hex, provider_snapshot={'model':'fixture'},
        source_blocks=document['blocks'], translated_blocks=translated, glossary={}, status='completed')
    db.add_all([audio, job]); db.commit()
    return novel, chapter, document, audio, job


def test_manifest_is_private_payload_free_read_only_and_estimates_existing_media(client, db, auth_headers, offline_story):
    novel, chapter, document, audio, job = offline_story
    response = client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    data = response.json(); assert data['total'] == 1 and data['novel_title'] == novel.title
    row = data['chapters'][0]
    assert row['downloaded'] and row['source_version'] == document['content_version']
    assert row['text_bytes_estimate'] > len(chapter.content.encode())
    assert row['audio'] == {'job_id':audio.id, 'bytes':Path(audio.audio_path).stat().st_size, 'source_version':document['content_version']}
    assert row['translations'][0]['job_id'] == job.id and row['translations'][0]['bytes_estimate'] > 0
    assert 'PRIVATE_ORIGINAL_TEXT' not in response.text and 'PRIVATE_TRANSLATED_TEXT' not in response.text
    assert str(Path(audio.audio_path)) not in response.text and 'http://unused' not in response.text
    assert db.query(TranslationJob).count() == db.query(ChapterAudioJob).count() == 1


def test_offline_pages_require_same_manifest_snapshot(client, db, auth_headers, offline_story):
    novel, chapter, _, _, _ = offline_story
    url = f'/reader/stories/{novel.id}/offline-manifest'
    first = client.get(url, headers=auth_headers).json()
    assert first['chapters'][0]['chapter_key'] == chapter.chapter_key
    expected = {f'expected_{field}': first[field] for field in ('manifest_epoch', 'manifest_revision')}
    assert client.get(url, headers=auth_headers, params=expected).status_code == 200
    db.add(Chapter(novel_id=novel.id, chapter_number=8, title='Appended chapter'))
    db.commit()
    stale = client.get(url, headers=auth_headers, params=expected)
    assert stale.status_code == 409
    assert stale.json()['detail']['code'] == 'chapter_manifest_changed'
    assert stale.headers['cache-control'] == 'private, no-store'
    assert client.get(url, headers=auth_headers).json()['total'] == 2


def test_partial_or_foreign_offline_manifest_identity_is_rejected(client, auth_headers, offline_story):
    novel, _, _, _, _ = offline_story
    url = f'/reader/stories/{novel.id}/offline-manifest'
    for expected in ({'expected_manifest_revision': '1'}, {'expected_manifest_epoch': str(uuid4())}):
        response = client.get(url, headers=auth_headers, params=expected)
        assert response.status_code == 409
    assert client.get(url, headers=auth_headers, params={'expected_manifest_revision': '01'}).status_code == 422


def test_same_text_and_numeric_id_do_not_attach_foreign_audio_identity(client, db, auth_headers, offline_story):
    novel, _, _, audio, _ = offline_story
    audio.chapter_key = str(uuid4())
    db.commit()
    result = client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers)
    assert result.status_code == 200
    assert result.json()['chapters'][0]['audio'] is None


def test_offline_translation_exact_rich_document_and_stale_or_partial_rejected(client, db, auth_headers, offline_story):
    novel, chapter, document, _, job = offline_story
    url = f'/reader/offline/translations/{job.id}'
    response = client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.json()['document']['blocks'] == job.translated_blocks
    assert response.json()['source_version'] == document['content_version']
    assert 'provider' not in response.json()
    job.translated_blocks = job.translated_blocks[:1]; db.commit()
    assert client.get(url, headers=auth_headers).status_code == 409
    assert client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers).json()['chapters'][0]['translations'] == []
    chapter.document = from_html('<p>Revised original.</p>'); db.commit()
    assert client.get(url, headers=auth_headers).status_code == 409
    row = client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers).json()['chapters'][0]
    assert row['audio'] is None and row['translations'] == []


def test_foreign_empty_populated_and_missing_story_cannot_leak_offline_metadata(client, db, auth_headers, offline_story):
    novel, _, _, _, job = offline_story
    stranger = User(username='offline-stranger', password='unused'); db.add(stranger); db.flush()
    library = Library(user_id=stranger.id, name='Private'); db.add(library); db.flush()
    empty = Novel(library_id=library.id, title='PRIVATE_EMPTY'); db.add(empty)
    novel.library_id = library.id; db.commit()
    for identity in (novel.id, empty.id, 999999):
        response = client.get(f'/reader/stories/{identity}/offline-manifest', headers=auth_headers)
        assert response.status_code == 404 and 'PRIVATE' not in response.text
        neighbor = client.get(f'/chapter/navigation/{identity}/3', headers=auth_headers)
        assert neighbor.status_code == 404 and 'PRIVATE' not in neighbor.text
    assert client.get(f'/reader/offline/translations/{job.id}', headers=auth_headers).status_code == 404


def test_manifest_paginates_gapped_chapters_and_checks_missing_files(client, db, test_library, auth_headers, offline_story):
    novel, _, _, audio, _ = offline_story
    db.add(Chapter(novel_id=novel.id, chapter_number=10, title='Unavailable', content_status=ContentStatus.MISSING)); db.commit()
    Path(audio.audio_path).unlink()
    response = client.get(f'/reader/stories/{novel.id}/offline-manifest?offset=1&limit=1', headers=auth_headers)
    data = response.json(); assert data['total'] == 2 and len(data['chapters']) == 1
    assert data['chapters'][0]['chapter_number'] == 10 and not data['chapters'][0]['downloaded']
    assert data['chapters'][0]['text_bytes_estimate'] == 0
    assert client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers).json()['chapters'][0]['audio'] is None
    assert client.get(f'/reader/stories/{novel.id}/offline-manifest?limit=201', headers=auth_headers).status_code == 422


def test_legacy_plaintext_has_same_fingerprint_as_reader_and_no_new_rows(client, db, auth_headers, offline_story):
    from app.services.chapter_document import from_text
    novel, chapter, _, _, _ = offline_story
    chapter.document = None; chapter.content = 'Legacy paragraphs.'; db.commit()
    response = client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()['chapters'][0]['source_version'] == from_text(chapter.content)['content_version']
    db.refresh(chapter); assert chapter.document is None


def test_next_manifest_filters_followed_categories_before_pagination_and_preserves_negative_start(client, db, test_user, auth_headers, offline_story):
    from app.models.novel_personal import NovelPersonalData
    novel, _, _, _, _ = offline_story
    for number, category in [(-2, 'story'), (-1, 'omake'), (0, 'story'), (7, 'omake'), (10, 'story')]:
        db.add(Chapter(novel_id=novel.id, chapter_number=number, category=category, title=str(number), content_status=ContentStatus.MISSING))
    db.commit()
    url = f'/reader/stories/{novel.id}/offline-manifest'
    full = client.get(url, headers=auth_headers).json()
    assert full['total'] == 6
    followed = client.get(url, params={'followed_only': True, 'limit': 2}, headers=auth_headers).json()
    assert followed['total'] == 4
    assert [row['chapter_number'] for row in followed['chapters']] == [-2, 0]
    later = client.get(url, params={'followed_only': True, 'from_chapter': 0, 'offset': 1, 'limit': 1}, headers=auth_headers).json()
    assert later['total'] == 3 and later['chapters'][0]['chapter_number'] == 3
    personal = NovelPersonalData(user_id=test_user.id, novel_id=novel.id, followed_categories=['omake'])
    db.add(personal); db.commit()
    custom = client.get(url, params={'followed_only': True, 'from_chapter': -1}, headers=auth_headers).json()
    assert custom['total'] == 2
    assert [row['chapter_number'] for row in custom['chapters']] == [-1, 7]
    assert client.get(url, params={'from_chapter': 2**31}, headers=auth_headers).status_code == 422


def test_next_available_manifest_skips_missing_prefix_before_count_and_page(client, db, auth_headers, offline_story):
    novel, chapter, _, _, _ = offline_story
    db.add_all([Chapter(novel_id=novel.id, chapter_number=number, title='Unavailable', category='story', content_status=ContentStatus.MISSING) for number in range(-50, 3)])
    db.commit()
    data = client.get(f'/reader/stories/{novel.id}/offline-manifest', params={'followed_only': True, 'downloaded_only': True, 'limit': 1}, headers=auth_headers).json()
    assert data['total'] == 1 and data['chapters'][0]['id'] == chapter.id
    assert client.get(f'/reader/stories/{novel.id}/offline-manifest', headers=auth_headers).json()['total'] == 54


def test_negative_prologue_is_readable_downloadable_and_has_saved_versions(client, db, auth_headers, offline_story):
    novel, chapter, document, _, _ = offline_story
    original = client.get(f'/chapter/content/library/{novel.library_id}/{novel.id}/3', headers=auth_headers)
    assert original.status_code == 200
    before = original.json()
    chapter.chapter_number = -2; db.commit()
    captured = client.get(f'/chapter/content/library/{novel.library_id}/{novel.id}/-2',
        params={'expected_chapter_key': before['chapter_key']}, headers=auth_headers)
    assert captured.status_code == 200
    current = captured.json()
    assert current['chapter_key'] == before['chapter_key']
    assert current['manifest_epoch'] == before['manifest_epoch']
    assert int(current['manifest_revision']) > int(before['manifest_revision'])
    download = f'/chapter/download/{novel.library_id}/{novel.id}/-2'
    unsigned = client.get(download, headers=auth_headers)
    assert unsigned.status_code == 409 and unsigned.json()['detail']['code'] == 'chapter_identity_required'
    def proof(value):
        return {f'expected_{field}': value[field] for field in ('chapter_key', 'manifest_epoch', 'manifest_revision')} | {
            'expected_content_version': value['source_version']}
    stale = client.get(download, params=proof(before), headers=auth_headers)
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'chapter_manifest_changed'
    paths = [f'/chapter/{novel.id}/-2', f'/chapter/download/{novel.library_id}/{novel.id}/-2',
        f'/chapter/content/library/{novel.library_id}/{novel.id}/-2',
        f'/chapter/versions/{novel.id}/-2/{document["content_version"]}']
    for path in paths:
        response = client.get(path, params=proof(current) if path == download else {'expected_chapter_key': current['chapter_key']}, headers=auth_headers)
        assert response.status_code == 200, (path, response.text)
        assert response.json()['id'] == chapter.id and response.json()['chapter_number'] == -2
    versions = client.get(f'/chapter/versions/{novel.id}/-2', headers=auth_headers)
    assert versions.status_code == 200 and versions.json()['current_version'] == document['content_version']
    assert client.get(f'/chapter/content/library/{novel.library_id}/{novel.id}/nonnumeric', headers=auth_headers).status_code == 422
    assert client.get(f'/chapter/content/library/-{novel.library_id}/{novel.id}/-2', headers=auth_headers).status_code == 404


def test_chapter_list_pages_in_reading_order_including_prologues_and_gaps(client, db, auth_headers, offline_story):
    novel, _, _, _, _ = offline_story
    for number in (90_000, -2, 7, 0):
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title=str(number), content_status=ContentStatus.MISSING))
    db.commit()
    numbers = []
    for offset in (0, 2, 4):
        response = client.get(f'/chapter/{novel.id}', params={'skip': offset, 'limit': 2}, headers=auth_headers)
        assert response.status_code == 200, response.text
        numbers.extend(row['chapter_number'] for row in response.json())
        assert all('content' not in row and 'document' not in row for row in response.json())
    assert numbers == [-2, 0, 3, 7, 90_000]
    for params in ({'skip': -1}, {'limit': 0}, {'limit': 1001}):
        assert client.get(f'/chapter/{novel.id}', params=params, headers=auth_headers).status_code == 422


def test_navigation_uses_real_neighbors_with_negative_zero_and_gaps(client, db, auth_headers, offline_story):
    novel, _, _, _, _ = offline_story
    for number in (90_000, -2, 0, 7):
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title=str(number), content_status=ContentStatus.MISSING))
    db.commit()
    for number, previous, following in [(-2, None, 0), (0, -2, 3), (3, 0, 7), (90_000, 7, None)]:
        response = client.get(f'/chapter/navigation/{novel.id}/{number}', headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['chapter_number'] == number and data['novel_id'] == novel.id
        assert (data['previous']['chapter_number'] if data['previous'] else None) == previous
        assert (data['next']['chapter_number'] if data['next'] else None) == following
        assert 'content' not in response.text and 'document' not in response.text
    assert client.get(f'/chapter/navigation/{novel.id}/6', headers=auth_headers).status_code == 404
    assert client.get(f'/chapter/navigation/{novel.id + 9999}/0', headers=auth_headers).status_code == 404
