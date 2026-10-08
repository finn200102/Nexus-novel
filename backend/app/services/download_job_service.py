from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.chapter import Chapter, ContentStatus
from app.models.download_job import ChapterDownloadJob

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
    db.add_all(jobs)
    db.flush()
    return jobs


def claim_job(db: Session, job_id: int, *, worker_id: str | None = None) -> ChapterDownloadJob | None:
    # SQLAlchemy's DateTime columns are stored without timezone information in
    # the existing PostgreSQL schema. Normalize the comparison value so queued
    # jobs do not fail before the downloader gets a chance to run.
    now = datetime.now(UTC).replace(tzinfo=None)
    job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job_id).first()
    if not job or job.status not in {"queued", "retry_wait"}:
        return None
    if job.next_attempt_at and job.next_attempt_at > now:
        return None
    job.status = "processing"
    job.attempt_count = (job.attempt_count or 0) + 1
    job.last_attempt_at = now
    job.started_at = job.started_at or now
    job.next_attempt_at = None
    job.error = None
    db.commit()
    db.refresh(job)
    return job


def complete_job(db: Session, job: ChapterDownloadJob) -> None:
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


def cancel_job(db: Session, job: ChapterDownloadJob, reason: str = "Cancelled by user") -> None:
    now = datetime.now(UTC)
    job.status = "cancelled"
    job.cancelled_at = now
    job.finished_at = now
    job.next_attempt_at = None
    job.cancellation_reason = reason[:500]
    db.commit()


def retry_job(db: Session, job: ChapterDownloadJob) -> None:
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
