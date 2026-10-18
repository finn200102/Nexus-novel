from datetime import UTC, datetime, timedelta
from fastapi import HTTPException

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.chapter import Chapter, ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.services.job_lease import claim

ACTIVE_STATUSES = ("queued", "processing", "retry_wait")


def queue_missing_chapters(db: Session, *, user_id: int, library_id: int, novel_id: int, count: int) -> list[ChapterDownloadJob]:
    active_ids = {
        job.chapter_id
        for job in db.query(ChapterDownloadJob).filter(
            ChapterDownloadJob.user_id == user_id,
            ChapterDownloadJob.novel_id == novel_id,
            ChapterDownloadJob.status.in_(ACTIVE_STATUSES),
        ).all()
    }
    query = db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.content_status == ContentStatus.MISSING,
    )
    if active_ids:
        query = query.filter(~Chapter.id.in_(active_ids))
    remaining = max(count - len(active_ids), 0)
    if remaining == 0:
        return []
    chapters = query.order_by(Chapter.chapter_number.asc()).limit(remaining).all()
    jobs = [ChapterDownloadJob(
        user_id=user_id,
        library_id=library_id,
        novel_id=novel_id,
        chapter_id=chapter.id,
        max_attempts=3,
        next_attempt_at=datetime.now(UTC),
    ) for chapter in chapters]
    created = []
    for job in jobs:
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
            created.append(job)
        except IntegrityError:
            # Another request already queued this chapter. The database's
            # active-job constraint is authoritative, not the initial read.
            duplicate = db.query(ChapterDownloadJob.id).filter(
                ChapterDownloadJob.user_id == user_id,
                ChapterDownloadJob.chapter_id == job.chapter_id,
                ChapterDownloadJob.status.in_(["queued", "processing", "retry_wait"]),
            ).first()
            if duplicate:
                continue
            raise
    return created


def claim_job(db: Session, job_id: int, *, worker_id: str | None = None) -> ChapterDownloadJob | None:
    return claim(db, ChapterDownloadJob, job_id, worker_id=worker_id)


def complete_job(db: Session, job: ChapterDownloadJob) -> None:
    job.lease_owner = None
    job.lease_expires_at = None
    job.status = "completed"
    job.finished_at = datetime.now(UTC)
    job.next_attempt_at = None
    job.error = None
    job.error_code = None
    db.commit()


def fail_or_retry_job(
    db: Session,
    job: ChapterDownloadJob,
    error: str,
    *,
    error_code: str = "DOWNLOAD_FAILED",
    retryable: bool = True,
) -> None:
    job.lease_owner = None
    job.lease_expires_at = None
    now = datetime.now(UTC)
    job.error = error[:2000]
    job.error_code = error_code
    if not retryable or (job.attempt_count or 0) >= (job.max_attempts or 3):
        job.status = "failed"
        job.finished_at = now
        job.next_attempt_at = None
    else:
        delay_seconds = min(3600, 30 * (2 ** max((job.attempt_count or 1) - 1, 0)))
        job.status = "retry_wait"
        job.next_attempt_at = now + timedelta(seconds=delay_seconds)
    db.commit()


def fresh_owned_job(db,job):
    from app.models.user import User
    from app.services.chapter_identity_service import sqlite_transaction
    job_id,user_id=job.id,job.user_id
    sqlite_transaction(db,write=True)
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    current=db.query(ChapterDownloadJob).filter_by(id=job_id,user_id=user_id).populate_existing().with_for_update().first()
    if current is None:raise HTTPException(404,'Download job not found')
    return current


def cancel_job(db: Session, job: ChapterDownloadJob, reason: str = "Cancelled by user") -> None:
    job=fresh_owned_job(db,job)
    if job.status not in ACTIVE_STATUSES:raise HTTPException(409,'Download job is no longer active')
    from app.services.chapter_download_identity_service import capture,matches
    chapter=db.query(Chapter).filter_by(id=job.chapter_id,novel_id=job.novel_id).populate_existing().with_for_update().first()
    if chapter is not None and chapter.content_status==ContentStatus.PROCESSING:
        current=capture(db,chapter,user_id=job.user_id,library_id=job.library_id)
        if matches(current,job.chapter_identity):
            chapter.content_status=ContentStatus.MISSING
            chapter.download_started_at=None;chapter.download_finished_at=None;chapter.download_error=None
    job.lease_owner = None
    job.lease_expires_at = None
    now = datetime.now(UTC)
    job.status = "cancelled"
    job.cancelled_at = now
    job.finished_at = now
    job.next_attempt_at = None
    job.cancellation_reason = reason[:500]
    db.commit()


def retry_job(db: Session, job: ChapterDownloadJob) -> None:
    job=fresh_owned_job(db,job)
    if job.status not in {'failed','cancelled','retry_wait'}:raise HTTPException(409,'Only failed or cancelled downloads can be retried')
    from app.services.chapter_download_identity_service import capture,matches
    chapter=db.query(Chapter).filter_by(id=job.chapter_id,novel_id=job.novel_id).populate_existing().with_for_update().first()
    current=capture(db,chapter,user_id=job.user_id,library_id=job.library_id) if chapter is not None else None
    if current is None or not matches(current,job.chapter_identity) or not current.get('metadata_manifest_key') or not current.get('metadata_chapter_key') or not isinstance(current.get('metadata_source'),dict):
        raise HTTPException(409,detail={'code':'chapter_review_required','message':'Review the source binding and select the current chapter for a new download. This older job cannot be rebound by retry.','review_path':f'/chapter/novel/{job.novel_id}/manifest-state'})
    job.lease_owner = None
    job.lease_expires_at = None
    # A manual retry is a new retry cycle.  Keeping the old counter caused a
    # previously exhausted job to jump directly to impossible states such as
    # "attempt 4/3" and fail without receiving its renewed retry budget.
    job.status = "queued"
    job.attempt_count = 0
    job.next_attempt_at = datetime.now(UTC)
    job.started_at = None
    job.finished_at = None
    job.cancelled_at = None
    job.cancellation_reason = None
    job.error = None
    job.error_code = None
    db.commit()
