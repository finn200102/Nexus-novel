"""Translations are private artifacts of an immutable original chapter."""
from fastapi import HTTPException
from sqlalchemy.orm import load_only
from app.models import Chapter, Library, Novel, User
from app.models.chapter_manifest import ChapterManifestState
from app.services.chapter_identity_service import check_write, source_version


def capture(db, user_id, chapter, expected=None):
    return check_write(db,user_id,chapter,require_content_version=True,**(expected or {}))


def chapter_for_job(db,job,*,lock=False,metadata_only=False):
    query=db.query(Chapter).join(Novel,Novel.id==Chapter.novel_id).join(Library,Library.id==Novel.library_id).filter(
        Chapter.id==job.chapter_id,Chapter.novel_id==job.novel_id,Library.user_id==job.user_id).execution_options(
        include_archived_chapters=True).populate_existing()
    if metadata_only:
        query=query.options(load_only(Chapter.id,Chapter.chapter_number,Chapter.chapter_key,Chapter.archived,Chapter.title))
    if lock:query=query.with_for_update(of=Chapter)
    return query.first()


def fields(db,job):
    chapter=chapter_for_job(db,job,metadata_only=True)
    state=db.query(ChapterManifestState).filter_by(novel_id=job.novel_id).populate_existing().first()
    same=bool(not job.identity_inferred and chapter is not None and state is not None and job.chapter_key==chapter.chapter_key
              and job.chapter_key and job.manifest_epoch==state.manifest_epoch)
    version=db.query(Chapter.document['content_version'].as_string()).filter_by(id=job.chapter_id).execution_options(
        include_archived_chapters=True).scalar() if same else None
    return dict(chapter_number=chapter.chapter_number if same else None,chapter_title=chapter.title if same else None,
        chapter_key=chapter.chapter_key if same else None,manifest_epoch=state.manifest_epoch if same else None,
        manifest_revision=str(state.revision) if same else None,current_content_version=version,
        source_chapter_key=job.chapter_key,source_manifest_epoch=job.manifest_epoch,source_manifest_revision=job.manifest_revision,
        chapter_title_snapshot=job.chapter_title_snapshot,chapter_number_snapshot=job.chapter_number_snapshot,
        source_identity_inferred=bool(job.identity_inferred),source_identity_current=same,
        chapter_archived=bool(chapter is not None and chapter.archived))


def require_dispatch(db,job):
    db.query(User.id).filter_by(id=job.user_id).with_for_update().first()
    from app.auth.dependencies import require_current_session
    require_current_session(db,job.user_id)
    chapter=chapter_for_job(db,job,lock=True)
    state=db.query(ChapterManifestState).filter_by(novel_id=job.novel_id).populate_existing().with_for_update().first()
    owner=db.query(User.id).filter(User.id==job.user_id,User.is_disabled.is_(False)).first()
    if (owner is None or chapter is None or state is None or chapter.archived or job.identity_inferred
            or not job.chapter_key or not job.manifest_epoch or not job.manifest_revision
            or job.chapter_key!=chapter.chapter_key or job.manifest_epoch!=state.manifest_epoch
            or not job.source_version or source_version(chapter)!=job.source_version):
        raise HTTPException(409,detail={'code':'translation_identity_review_required',
            'message':'This request no longer proves its original active chapter. Review the current original before creating a new translation; saved variants remain private and available.'})
    return chapter


def require_retry(db,job):
    db.query(User.id).filter_by(id=job.user_id).with_for_update().first()
    return require_dispatch(db,job)


def require_captured(db,user_id,chapter_id,novel_id,captured):
    """Recheck an already authorized direct request without rebinding its address."""
    from types import SimpleNamespace
    return require_dispatch(db,SimpleNamespace(user_id=user_id,novel_id=novel_id,chapter_id=chapter_id,
        chapter_key=captured['chapter_key'],manifest_epoch=captured['manifest_epoch'],
        manifest_revision=captured['manifest_revision'],source_version=captured['source_version'],identity_inferred=False))
