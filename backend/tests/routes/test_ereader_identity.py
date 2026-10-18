"""Stored file positions have immutable provenance but never approve AI evidence."""
from uuid import uuid4
import pytest
from sqlalchemy import text
from app.models import Novel,Chapter,ReadingProgress,ReadingHistory,ReadingRunEvent
from app.models.ereader import EpubBuild
from app.models.chapter import ContentStatus
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.services import epub_service,ereader_identity_service as identity
from app.services.chapter_document import from_text
from app.services.reading_run_service import action
from app.schemas.reading_runs import ReadingRunAction
from config.settings import settings


def story(db,library,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'DOWNLOAD_PATH',str(tmp_path))
    novel=Novel(title='Signed spine',library_id=library.id);db.add(novel);db.flush()
    rows=[]
    for number in [-2,0,7]:
        doc=from_text(f'Original content for {number}.')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=f'Chapter {number}',content=doc['plain_text'],document=doc,content_status=ContentStatus.PRESENT)
        db.add(chapter);rows.append(chapter)
    db.commit();built=epub_service.ensure_build(db,novel)
    return novel,rows,built


def test_exact_build_points_are_idempotent_and_inferred_without_receipts_or_completion(db,test_user,test_library,monkeypatch,tmp_path):
    novel,rows,built=story(db,test_library,monkeypatch,tmp_path)
    assert [value['chapter_number'] for value in built.build.spine_identity]==[-2,0,7]
    assert identity.inferred(db,test_user.id,built.build,2,1,operation='device-last') is None;db.commit()
    progress=db.query(ReadingProgress).one();revision=progress.revision
    assert progress.chapter_key==rows[-1].chapter_key and progress.current_identity_inferred
    assert progress.percent==100 and progress.furthest_identity_inferred
    assert db.query(ChapterReadReceipt).count()==0
    assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==0
    assert db.query(ReadingHistory).one().identity_inferred and db.query(ReadingHistory).one().verified_percent==0
    assert identity.inferred(db,test_user.id,built.build,2,1,operation='device-last') is None;db.commit()
    assert progress.revision==revision and db.query(ReadingHistory).count()==1


@pytest.mark.parametrize('change',['body','archive','replacement','owner','source'])
def test_old_file_never_reattaches_to_changed_source_or_owner(db,test_user,test_library,monkeypatch,tmp_path,change):
    novel,rows,built=story(db,test_library,monkeypatch,tmp_path);row=rows[-1]
    if change=='body':row.document=from_text('Changed prose.')
    elif change=='archive':row.archived=True
    elif change=='owner':test_user.storage_id=str(uuid4())
    elif change=='source':novel.source_url='https://different-source.invalid/story'
    else:
        pk,doc=row.id,row.document
        db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(row)
        db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=7,title='Chapter 7',content=doc['plain_text'],document=doc,content_status=ContentStatus.PRESENT))
    db.commit()
    assert identity.inferred(db,test_user.id,built.build,2,.8,operation='old-device') is not None
    assert db.query(ReadingProgress).count()==0 and db.query(ChapterReadReceipt).count()==0


def test_same_time_same_pk_replacement_cannot_reuse_epub_and_old_private_file_is_retained(db,test_library,monkeypatch,tmp_path):
    novel,rows,first=story(db,test_library,monkeypatch,tmp_path);original=first.path.read_bytes();row=rows[-1]
    pk,doc,stamp=row.id,row.document,row.updated_at
    db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(row)
    db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=7,title='Chapter 7',document=doc,content=doc['plain_text'],content_status=ContentStatus.PRESENT,updated_at=stamp));db.commit()
    second=epub_service.ensure_build(db,novel)
    assert first.build.fingerprint!=second.build.fingerprint and original!=second.path.read_bytes()
    assert first.path.read_bytes()==original and db.query(EpubBuild).count()==2


def test_legacy_file_stays_unknown_and_reread_does_not_adopt_old_first_run_book(db,test_user,test_library,monkeypatch,tmp_path):
    novel,rows,built=story(db,test_library,monkeypatch,tmp_path)
    assert identity.inferred(db,test_user.id,built.build,0,.2,operation='first-device') is None;db.commit()
    progress=db.query(ReadingProgress).one()
    action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=progress.revision,operation_id='new-run',reading_run_key=progress.reading_run_key),'start')
    assert identity.inferred(db,test_user.id,built.build,2,.9,operation='late-old-device')=='reading_run_changed'
    fresh=db.query(ReadingProgress).one();assert fresh.chapter_number==-2 and fresh.percent==0
    built.build.spine_identity=None;db.commit()
    assert identity.inferred(db,test_user.id,built.build,0,.4,operation='unknown')=='book_identity_unknown'


def test_koreader_unknown_legacy_build_keeps_bookmark_without_mutating_reading_state(client,db,test_user,test_library,auth_headers,monkeypatch,tmp_path):
    import hashlib
    novel,rows,built=story(db,test_library,monkeypatch,tmp_path)
    secret=client.post('/app-passwords',headers=auth_headers,json={'label':'KOReader','scope':'kosync'}).json()['secret']
    headers={'x-auth-user':test_user.username,'x-auth-key':hashlib.md5(secret.encode()).hexdigest()}
    built.build.spine_identity=None;built.build.owner_storage_id=None;db.commit()
    payload={'document':built.build.partial_md5,'progress':'/body/DocFragment[3]/body/p[1]','percentage':1.0,'device':'KOReader','device_id':'owned'}
    response=client.put('/kosync/syncs/progress',headers=headers,json=payload)
    assert response.status_code==200,response.text
    assert response.json()['nexus_progress']=='review_required' and response.json()['review_reason']=='book_identity_unknown'
    from app.models.ereader import KosyncProgress
    stored=db.query(KosyncProgress).one()
    assert stored.progress==payload['progress'] and stored.percentage==1
    assert db.query(ReadingProgress).count()==0 and db.query(ChapterReadReceipt).count()==0
    assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==0


def test_cached_build_releases_locks_and_never_renders_archived_chapters(db,test_user,test_library,monkeypatch,tmp_path):
    novel,rows,built=story(db,test_library,monkeypatch,tmp_path)
    again=epub_service.ensure_build(db,novel)
    assert again.path==built.path and not db.in_transaction()
    rows[1].archived=True;db.commit()
    active=epub_service.ensure_build(db,novel)
    assert active.build.spine==[-2,7] and [item['chapter_key'] for item in active.build.spine_identity]==[rows[0].chapter_key,rows[-1].chapter_key]
    from zipfile import ZipFile
    with ZipFile(active.path) as archive:
        assert len([name for name in archive.namelist() if name.startswith('OEBPS/chapter-')])==2


def test_kobo_confirmation_rejects_noncanonical_identity_and_revision():
    from pydantic import ValidationError
    from app.schemas.ereader_identity import KoboVersionConfirmation
    good=dict(expected_fingerprint='a'*64,expected_manifest_epoch='12345678-1234-1234-1234-123456789abc',expected_manifest_revision='1',reading_run_key=None)
    for bad in [dict(expected_manifest_epoch='-'*36),dict(expected_manifest_revision='9'*20),dict(expected_manifest_revision='01'),dict(reading_run_key=True),dict(reading_run_key='bad')]:
        with pytest.raises(ValidationError):KoboVersionConfirmation(**(good|bad))
