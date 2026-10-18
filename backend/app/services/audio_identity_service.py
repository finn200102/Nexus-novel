"""Immutable recording provenance and live-dispatch chapter guards."""
from fastapi import HTTPException
from sqlalchemy.orm import load_only
from app.models import Chapter, Library, Novel, User
from app.models.chapter_manifest import ChapterManifestState
from app.services.chapter_identity_service import check_write, source_version


def capture(db, user_id, chapter, expected=None):
    return check_write(db, user_id, chapter, require_content_version=True, **(expected or {}))


def chapter_for_job(db, job, *, lock=False, metadata_only=False):
    query = db.query(Chapter).join(Novel, Novel.id == Chapter.novel_id).join(
        Library, Library.id == Novel.library_id).filter(
        Chapter.id == job.chapter_id, Chapter.novel_id == job.novel_id,
        Novel.library_id == job.library_id, Library.user_id == job.user_id).execution_options(
        include_archived_chapters=True).populate_existing()
    if metadata_only:
        query = query.options(load_only(Chapter.id, Chapter.chapter_key, Chapter.chapter_number, Chapter.archived, Chapter.novel_id))
    if lock:
        query = query.with_for_update(of=Chapter)
    return query.first()


def fields(db, job, chapter=None):
    chapter = chapter if chapter is not None else chapter_for_job(db, job, metadata_only=True)
    state = db.query(ChapterManifestState).filter_by(novel_id=job.novel_id).populate_existing().first()
    same = bool(not job.identity_inferred and chapter is not None and job.chapter_key and chapter.chapter_key == job.chapter_key
                and state is not None and job.manifest_epoch == state.manifest_epoch)
    return {'chapter_id': job.chapter_id,
        'chapter_number': chapter.chapter_number if same else None,
        'chapter_key': chapter.chapter_key if same else None,
        'manifest_epoch': state.manifest_epoch if same else None,
        'manifest_revision': str(state.revision) if same else None,
        'source_chapter_key': job.chapter_key, 'source_manifest_epoch': job.manifest_epoch,
        'source_manifest_revision': job.manifest_revision,
        'chapter_archived': bool(chapter is not None and chapter.archived),
        'source_identity_current': same, 'source_identity_inferred': bool(job.identity_inferred),
        'chapter_title_snapshot': job.chapter_title_snapshot, 'chapter_number_snapshot': job.chapter_number_snapshot}


def require_dispatch(db, job):
    """An accepted job follows its UUID, never a changed numeric address.

    Appending unrelated chapters may advance the revision. Epoch, chapter UUID,
    active membership and the original text must still match exactly.
    """
    chapter = chapter_for_job(db, job, lock=True)
    state = db.query(ChapterManifestState).filter_by(novel_id=job.novel_id).populate_existing().with_for_update().first()
    enabled = db.query(User.id).filter(User.id == job.user_id, User.is_disabled.is_(False)).first()
    if (enabled is None or job.identity_inferred or chapter is None or chapter.archived or not job.chapter_key or not job.manifest_epoch
            or not job.manifest_revision or not job.source_version or state is None
            or job.chapter_key != chapter.chapter_key or job.manifest_epoch != state.manifest_epoch
            or source_version(chapter) != job.source_version):
        raise HTTPException(409, detail={'code': 'audio_identity_review_required',
            'message': 'This recording request no longer matches its original active chapter. Review the current chapter before creating new narration; existing recordings remain available.'})
    return chapter
