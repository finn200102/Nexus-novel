"""Fence delegated source text before I/O and before private publication."""
from fastapi import HTTPException
from app.models import Chapter,Novel,Library,User
from app.models.download_job import ChapterDownloadJob,download_identity
from app.services.chapter_identity_service import manifest_state,sqlite_transaction,source_version


def capture(db,chapter,*,user_id,library_id):
    value=download_identity(db.connection(),chapter_id=chapter.id,novel_id=chapter.novel_id,library_id=library_id,user_id=user_id)
    if value is None:raise HTTPException(404,'Owned chapter identity not found')
    return value


def matches(current,expected):
    return isinstance(expected,dict) and all(current.get(key)==expected.get(key) for key in (
        'chapter_key','manifest_epoch','metadata_source','metadata_manifest_key','metadata_chapter_key','site_chapter_id','source_url','metadata_id'))


def fenced_chapter(db,*,user_id,library_id,novel_id,chapter_id,expected,job_id=None,lease_owner=None,attempt=None,lock=False):
    if lock:sqlite_transaction(db,write=True)
    query=db.query(User).filter_by(id=user_id).populate_existing()
    if lock:query=query.with_for_update()
    user=query.first()
    if user is None or user.is_disabled:return None
    if job_id is not None:
        query=db.query(ChapterDownloadJob).filter_by(id=job_id,user_id=user_id,novel_id=novel_id,chapter_id=chapter_id).populate_existing()
        if lock:query=query.with_for_update()
        job=query.first()
        if not job or job.status!='processing' or job.lease_owner!=lease_owner or job.attempt_count!=attempt:return None
    query=db.query(Chapter).join(Novel,Novel.id==Chapter.novel_id).join(Library,Library.id==Novel.library_id).filter(
        Chapter.id==chapter_id,Chapter.novel_id==novel_id,Novel.library_id==library_id,Library.user_id==user_id).populate_existing()
    if lock:query=query.with_for_update(of=Chapter)
    chapter=query.first()
    if not chapter or chapter.content_status.value!='PROCESSING':return None
    manifest_state(db,novel_id,lock=lock)
    current=capture(db,chapter,user_id=user_id,library_id=library_id)
    if not matches(current,expected):return None
    if not (expected.get('metadata_manifest_key') and expected.get('metadata_chapter_key') and isinstance(expected.get('metadata_source'),dict)):
        return None
    return chapter


def publish(db,*,value,expected_source_version,**identity):
    chapter=fenced_chapter(db,**identity,lock=True)
    if chapter is None or source_version(chapter)!=expected_source_version:
        db.rollback();return False
    from app.services.chapter_services import update_chapter
    update_chapter(db,chapter.id,value)
    return True
