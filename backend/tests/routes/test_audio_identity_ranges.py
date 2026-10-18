"""A range selects real signed chapter labels before pagination and job totals."""
from app.models import Chapter
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_text
from tests.routes.test_story_audio import setup_story, submit


def test_signed_gapped_range_filters_metadata_and_audio_summary_before_paging(
    client, auth_headers, db, test_user, test_library, monkeypatch, tmp_path,
):
    novel, voice = setup_story(db, test_user, test_library, monkeypatch, tmp_path)
    for number in (-2, 0, 7):
        document = from_text(f'Original prologue {number}')
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title=f'Part {number}',
                       content=document['plain_text'], document=document, content_status=ContentStatus.PRESENT))
    db.commit()
    assert submit(client, auth_headers, novel, voice, [1]).status_code == 202
    path = f'/audio/stories/{novel.id}?from_chapter=-2&to_chapter=0&limit=1'
    first = client.get(path, headers=auth_headers)
    assert first.status_code == 200
    body = first.json()
    assert body['total'] == 2
    assert body['summary'] == {'chapters': 2, 'downloaded': 2, 'ready': 0, 'queued': 0, 'needs_retry': 0}
    assert [row['chapter_number'] for row in body['chapters']] == [-2]
    second = client.get(path + '&offset=1', headers=auth_headers)
    assert second.status_code == 200 and second.json()['total'] == 2
    assert [row['chapter_number'] for row in second.json()['chapters']] == [0]
    empty = client.get(f'/audio/stories/{novel.id}?from_chapter=4&to_chapter=6', headers=auth_headers).json()
    assert empty['total'] == 0 and empty['chapters'] == [] and empty['summary']['queued'] == 0
    assert client.get(f'/audio/stories/{novel.id}?from_chapter=7&to_chapter=-2', headers=auth_headers).status_code == 422
    assert client.get(f'/audio/stories/{novel.id}?from_chapter=-2147483649', headers=auth_headers).status_code == 422
