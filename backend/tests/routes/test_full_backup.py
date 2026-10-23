from datetime import UTC,datetime
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED,ZipFile

from app.models import Chapter,ChapterVersion,Library,Novel,ReadingAnnotation,ReadingProgress,User
from app.models.chapter import ContentStatus
from app.models.novel_personal import NovelPersonalData
from app.services.chapter_document import from_html,from_text
from app.services.chapter_identity_service import source_version
from tests.auth_helpers import bearer_headers


def seed_source_less_book(db,user):
    library=Library(user_id=user.id,name='Private backup');db.add(library);db.flush()
    novel=Novel(library_id=library.id,title='Private original',url=None,novel_site='local',scrape_status='awaiting_original');db.add(novel);db.flush()
    rich=from_html('<h2>Opening</h2><p>First paragraph.</p><ul><li>One</li><li>Two</li></ul><div class="author-note"><p>A/N: Source note.</p></div><blockquote><p>Quoted passage.</p></blockquote>')
    text='\n\n'.join(block['text'] for block in rich['blocks'])
    first=Chapter(novel_id=novel.id,chapter_number=1,title='Opening',content=text,document=rich,content_status=ContentStatus.PRESENT,word_count=8)
    second_doc=from_text('The preserved epilogue.')
    second=Chapter(novel_id=novel.id,chapter_number=99,title='Epilogue',content='The preserved epilogue.',document=second_doc,content_status=ContentStatus.PRESENT,archived=True,archived_at=datetime.now(UTC).replace(tzinfo=None))
    db.add_all([first,second]);db.flush()
    old=from_text('The earlier retained original.')
    db.add(ChapterVersion(chapter_id=first.id,chapter_key=first.chapter_key,content_version=old['content_version'],title='Opening',source_url='https://example.org/book/chapter?token=private',content='The earlier retained original.',document=old,byte_count=31,reason='source_replaced'))
    db.add(ReadingProgress(user_id=user.id,novel_id=novel.id,chapter_id=first.id,chapter_key=first.chapter_key,chapter_number=1,position=7,percent=35,source_content_version=source_version(first),furthest_chapter_number=1,furthest_percent=35))
    db.add(ReadingAnnotation(user_id=user.id,novel_id=novel.id,chapter_id=first.id,chapter_key=first.chapter_key,chapter_number=1,annotation_type='note',note='Keep this private note',quote='First paragraph.',block_id=rich['blocks'][1]['id'],locator_content_version=rich['content_version']))
    db.add(NovelPersonalData(user_id=user.id,novel_id=novel.id,notes='Private story note'))
    db.commit();return novel,first,second


def _zip_response(client,user,db):
    response=client.get('/me/backup',headers=bearer_headers(user.id,db))
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['content-type'].startswith('application/zip')
    return response.content


def test_full_backup_restores_private_story_bodies_versions_notes_and_progress_after_review(client,db,test_user):
    novel,first,second=seed_source_less_book(db,test_user)
    archive=_zip_response(client,test_user,db)
    with ZipFile(BytesIO(archive)) as zipped:
        manifest=json.loads(zipped.read('nexus-backup.json'))
        assert manifest['format']=='nexus-full-backup' and manifest['version']==1
        assert len(manifest['chapter_assets'])==2
        assert all(asset['sha256'] and asset['size'] for asset in manifest['chapter_assets'])

    target_user=User(username='full-backup-target',password='hashed_password_here');db.add(target_user);db.commit()
    imported=client.post('/me/backup/import',headers={**bearer_headers(target_user.id,db),'Content-Type':'application/zip'},content=archive)
    assert imported.status_code==200,imported.text
    story=imported.json()['libraries'][0]['novels'][0]
    assert story['original_status']=='backup_review' and story['reading_review_id']
    target=db.get(Novel,story['novel_id'])
    assert target.url is None and target.scrape_status=='awaiting_original'
    placeholders=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=target.id).all()
    assert len(placeholders)==2 and all(not chapter.source_url and chapter.content_status==ContentStatus.MISSING for chapter in placeholders)
    review_id=story['reading_review_id'];headers=bearer_headers(target_user.id,db)
    review=client.get(f'/me/import-reading-reviews/{review_id}?limit=100',headers=headers).json()
    assert review['total']>=2
    assert any('full backup contains chapter text' in warning.lower() for warning in review['warnings'])
    mappings=[]
    for item in review['items']:
        key=item['backup_placeholder_key']
        if not key:
            # This legacy annotation has only a chapter number. Select the
            # empty same-number slot explicitly, as a user does in review.
            matches=[chapter for chapter in placeholders if chapter.chapter_number==item['reference']['chapter_number']]
            assert len(matches)==1
            key=matches[0].chapter_key
        mappings.append({'ref':item['reference']['ref'],'chapter_key':key,
            'confirm_changed_content':not item['archived_body_available'],
            'restore_archived_content':item['archived_body_available']})
    assert len(mappings)==review['total']
    preview=client.post(f'/me/import-reading-reviews/{review_id}/preview',headers=headers,json={'expected_revision':review['revision'],'mappings':mappings})
    assert preview.status_code==200,preview.text
    applied=client.post(f'/me/import-reading-reviews/{review_id}/apply',headers=headers,json={'review_token':preview.json()['review_token'],'operation_id':'full-backup-restore-1'})
    assert applied.status_code==200,applied.text
    restored=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=target.id).order_by(Chapter.chapter_number).all()
    active=next(chapter for chapter in restored if chapter.chapter_number==1)
    archived=next(chapter for chapter in restored if chapter.chapter_number==99)
    assert active.content_status==ContentStatus.PRESENT and active.document['content_version']==source_version(first)
    assert [block['id'] for block in active.document['blocks']]==[block['id'] for block in first.document['blocks']]
    assert any(block.get('role')=='author_note' and block.get('role_provenance')=='source' for block in active.document['blocks'])
    reader=client.get(f'/chapter/content/library/{target.library_id}/{target.id}/1?expected_chapter_key={active.chapter_key}',headers=headers)
    assert reader.status_code==200,reader.text
    assert reader.json()['document']['plain_text']==active.document['plain_text'] and reader.json()['content']==active.content
    assert archived.archived and archived.content=='The preserved epilogue.'
    versions=db.query(ChapterVersion).filter_by(chapter_key=active.chapter_key).all()
    assert len(versions)==1 and versions[0].content=='The earlier retained original.' and versions[0].source_url=='https://example.org/book/chapter'
    original_response=client.get(f'/chapter/versions/{target.id}/1/{versions[0].content_version}?expected_chapter_key={active.chapter_key}',headers=headers)
    assert original_response.status_code==200 and original_response.json()['content']=='The earlier retained original.'
    progress=db.query(ReadingProgress).filter_by(user_id=target_user.id,novel_id=target.id).one()
    note=db.query(ReadingAnnotation).filter_by(user_id=target_user.id,novel_id=target.id).one()
    personal=db.query(NovelPersonalData).filter_by(user_id=target_user.id,novel_id=target.id).one()
    assert progress.chapter_key==active.chapter_key and progress.position==7
    assert note.chapter_key==active.chapter_key and note.note=='Keep this private note'
    assert personal.notes=='Private story note'
    assert client.get(f'/me/import-reading-reviews/{review_id}',headers=headers).json()['applied']==review['total']


def test_full_backup_rejects_unsafe_archive_paths_and_keeps_present_content(client,db,test_user):
    unsafe=BytesIO()
    with ZipFile(unsafe,'w',ZIP_DEFLATED) as archive:archive.writestr('../outside.json','{}')
    response=client.post('/me/backup/import',headers={**bearer_headers(test_user.id,db),'Content-Type':'application/zip'},content=unsafe.getvalue())
    assert response.status_code==422

    novel,chapter,_=seed_source_less_book(db,test_user)
    backup=_zip_response(client,test_user,db)
    chapter.content='Locally edited chapter';chapter.document=from_text(chapter.content);db.commit()
    response=client.post('/me/backup/import',headers={**bearer_headers(test_user.id,db),'Content-Type':'application/zip'},content=backup)
    assert response.status_code==200,response.text
    story=response.json()['libraries'][0]['novels'][0];review_id=story['reading_review_id'];headers=bearer_headers(test_user.id,db)
    review=client.get(f'/me/import-reading-reviews/{review_id}?limit=100',headers=headers).json()
    archived_item=next(item for item in review['items'] if item['archived_body_available'] and item['reference']['chapter_number']==1)
    target=chapter
    preview=client.post(f'/me/import-reading-reviews/{review_id}/preview',headers=headers,json={'expected_revision':review['revision'],'mappings':[{'ref':archived_item['reference']['ref'],'chapter_key':target.chapter_key,'restore_archived_content':True}]})
    assert preview.status_code==409
    db.refresh(chapter);assert chapter.content=='Locally edited chapter' and chapter.content_status==ContentStatus.PRESENT


def test_full_backup_retained_original_validation_rolls_back_current_body_restore(client,db,test_user):
    seed_source_less_book(db,test_user)
    original=_zip_response(client,test_user,db)
    with ZipFile(BytesIO(original)) as source:
        entries={info.filename:source.read(info.filename) for info in source.infolist()}
    manifest=json.loads(entries['nexus-backup.json'])
    asset=next(row for row in manifest['chapter_assets'] if json.loads(entries[row['path']]).get('chapter_number')==1)
    body=json.loads(entries[asset['path']])
    body['versions'][0]['source_version']='0'*64
    encoded=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
    from hashlib import sha256
    entries[asset['path']]=encoded
    asset['size']=len(encoded);asset['sha256']=sha256(encoded).hexdigest()
    entries['nexus-backup.json']=json.dumps(manifest,ensure_ascii=False,separators=(',',':')).encode()
    malformed=BytesIO()
    with ZipFile(malformed,'w',ZIP_DEFLATED) as archive:
        for name,value in entries.items():archive.writestr(name,value)

    target_user=User(username='full-backup-rollback-target',password='hashed_password_here');db.add(target_user);db.commit()
    imported=client.post('/me/backup/import',headers={**bearer_headers(target_user.id,db),'Content-Type':'application/zip'},content=malformed.getvalue())
    assert imported.status_code==200,imported.text
    story=imported.json()['libraries'][0]['novels'][0];review_id=story['reading_review_id'];headers=bearer_headers(target_user.id,db)
    review=client.get(f'/me/import-reading-reviews/{review_id}?limit=100',headers=headers).json()
    item=next(row for row in review['items'] if row['archived_body_available'] and row['reference']['chapter_number']==1)
    target=db.get(Novel,story['novel_id'])
    slot=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=target.id,chapter_number=1).one()
    preview=client.post(f'/me/import-reading-reviews/{review_id}/preview',headers=headers,json={'expected_revision':review['revision'],'mappings':[{'ref':item['reference']['ref'],'chapter_key':slot.chapter_key,'restore_archived_content':True}]})
    assert preview.status_code==200,preview.text
    response=client.post(f'/me/import-reading-reviews/{review_id}/apply',headers=headers,json={'review_token':preview.json()['review_token'],'operation_id':'rollback-invalid-retained'})
    assert response.status_code==422
    db.refresh(slot)
    assert slot.content_status==ContentStatus.MISSING and not slot.content and not slot.document
    assert db.query(ChapterVersion).filter_by(chapter_key=slot.chapter_key).count()==0
