from app.models import Chapter, Novel, User, Library, ReadingAnnotation
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_html
from app.services.chapter_identity_service import identity


def story(db, library, title='Owned book', text='A hidden silver compass marks the road.'):
    novel = Novel(title=title, library_id=library.id)
    db.add(novel); db.flush()
    doc = from_html('<p>' + text + '</p>')
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title='Beginning', content=doc['plain_text'], document=doc, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    return novel, chapter


def test_text_search_is_account_scoped_literal_paginated_and_bounded(client, db, test_library, auth_headers):
    novel, chapter = story(db, test_library, text='Intro ' * 80 + 'silver compass 100%_literal ' + 'tail ' * 200)
    other = User(username='other-search', password='unused')
    db.add(other); db.flush()
    library = Library(name='Other', user_id=other.id); db.add(library); db.flush()
    foreign, _ = story(db, library, text='silver compass secret')
    result = client.get('/chapter/search', params={'q':'SILVER COMPASS'}, headers=auth_headers)
    assert result.status_code == 200, result.text
    data = result.json(); assert data['total'] == 1
    item = data['matches'][0]
    assert item['novel_id'] == novel.id and item['library_id'] == test_library.id
    assert 'silver compass' in item['snippet'] and len(item['snippet']) <= 400
    assert item['chapter_key'] == chapter.chapter_key and item['content_version'] == chapter.document['content_version']
    assert result.headers['cache-control'] == 'private, no-store'
    assert client.get('/chapter/search', params={'q':'100%_literal'}, headers=auth_headers).json()['total'] == 1
    assert client.get('/chapter/search', params={'q':'silver', 'novel_id':foreign.id}, headers=auth_headers).status_code == 404
    assert client.get('/chapter/search', params={'q':'silver','offset':1}, headers=auth_headers).json()['matches'] == []


def test_aggregate_download_status_counts_every_owned_book_and_excludes_archived(client, db, test_library, auth_headers):
    novel, chapter = story(db, test_library)
    failed = Chapter(novel_id=novel.id, chapter_number=2, title='Failed', content_status=ContentStatus.FAILED, download_error='Source unavailable', retry_count=2)
    archived = Chapter(novel_id=novel.id, chapter_number=3, title='Archived', content_status=ContentStatus.PRESENT, archived=True)
    db.add_all([failed, archived]); db.commit()
    response = client.get('/chapter/download-status', params={'library_id':test_library.id}, headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json(); assert data['total'] == 1
    row = data['novels'][0]; assert row['novel_id'] == novel.id
    assert row['status']['total'] == 2 and row['status']['present'] == 1 and row['status']['failed'] == 1
    assert row['status']['failed_chapters'][0]['id'] == failed.id
    assert client.get('/chapter/download-status', params={'library_id':999999}, headers=auth_headers).status_code == 404


def test_edit_note_preserves_locator_and_requires_current_owned_identity(client, db, test_user, test_library, auth_headers):
    novel, chapter = story(db, test_library)
    item = ReadingAnnotation(user_id=test_user.id, novel_id=novel.id, chapter_id=chapter.id, annotation_type='highlight', quote='silver compass', note='Before', position=4, percent=20, block_id=chapter.document['blocks'][0]['id'], text_offset=9, locator_content_version=chapter.document['content_version'])
    db.add(item); db.commit()
    address = identity(chapter)
    body = {'note':'After', **{'expected_' + k:v for k,v in address.items()}, 'expected_content_version':chapter.document['content_version']}
    result = client.patch(f'/chapter/annotations/{item.id}', json=body, headers=auth_headers)
    assert result.status_code == 200, result.text
    row = result.json(); assert row['note'] == 'After' and row['quote'] == 'silver compass'
    assert row['text_offset'] == 9 and row['locator_content_version'] == chapter.document['content_version']
    bad = {**body, 'expected_content_version':'0'*64, 'note':'Wrong'}
    assert client.patch(f'/chapter/annotations/{item.id}', json=bad, headers=auth_headers).status_code == 409
    assert client.patch(f'/chapter/annotations/{item.id}', json={'note':'Wrong'}, headers=auth_headers).status_code == 409
    assert client.patch(f'/chapter/annotations/{item.id}', json={**body,'quote':'Moved'}, headers=auth_headers).status_code == 422
    db.refresh(item); assert item.note == 'After'


def test_annotation_edit_hides_other_users_notes(client, db, test_library, auth_headers):
    novel, chapter = story(db, test_library)
    other = User(username='note-owner', password='unused'); db.add(other); db.flush()
    note = ReadingAnnotation(user_id=other.id, novel_id=novel.id, chapter_id=chapter.id, note='Private')
    db.add(note); db.commit()
    response = client.patch(f'/chapter/annotations/{note.id}', json={'note':'Changed'}, headers=auth_headers)
    assert response.status_code == 404
    db.refresh(note); assert note.note == 'Private'
