from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from config.database import SessionLocal, get_db
from app.auth.dependencies import get_current_user
from app.models.download_job import ChapterDownloadJob
from app.models.chapter import Chapter, ContentStatus
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.routers.chapter import run_queued_download
from app.schemas.download import DownloadJobAction, DownloadJobResponse, DownloadQueueRequest
from app.services.download_job_service import ACTIVE_STATUSES, cancel_job, queue_missing_chapters, retry_job

router = APIRouter(prefix="/downloads", tags=["downloads"])


def _owned_job(db: Session, job_id: int, user: User) -> ChapterDownloadJob:
    job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job_id, ChapterDownloadJob.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found")
    return job


@router.get("/jobs", response_model=list[DownloadJobResponse])
def list_download_jobs(library_id: int | None = None, novel_id: int | None = None, status: str | None = None, limit: int = Query(default=100, ge=1, le=250), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.user_id == current_user.id)
    if library_id is not None:
        query = query.filter(ChapterDownloadJob.library_id == library_id)
    if novel_id is not None:
        query = query.filter(ChapterDownloadJob.novel_id == novel_id)
    if status:
        query = query.filter(ChapterDownloadJob.status == status)
    return query.order_by(ChapterDownloadJob.created_at.desc()).limit(limit).all()


@router.post("/jobs", response_model=list[DownloadJobResponse], status_code=202)
def queue_download_jobs(request: DownloadQueueRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    library = db.query(Library).filter(Library.id == request.library_id, Library.user_id == current_user.id).first()
    novel = db.query(Novel).filter(Novel.id == request.novel_id, Novel.library_id == request.library_id).first()
    if not library or not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    jobs = queue_missing_chapters(db, user_id=current_user.id, library_id=library.id, novel_id=novel.id, count=request.count)
    db.commit()
    for job in jobs:
        background_tasks.add_task(run_queued_download, job.id, SessionLocal)
    return jobs


@router.post("/jobs/{job_id}/retry", response_model=DownloadJobResponse)
def retry_download_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    if job.status not in {"failed", "cancelled", "retry_wait"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    retry_job(db, job)
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=DownloadJobResponse)
def cancel_download_job(job_id: int, action: DownloadJobAction | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    if job.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Download job is not active")
    chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
    if chapter and chapter.content_status == ContentStatus.PROCESSING:
        chapter.content_status = ContentStatus.MISSING
        chapter.download_started_at = None
        chapter.download_finished_at = None
        chapter.download_error = None
    cancel_job(db, job, (action.reason if action else None) or "Cancelled by user")
    db.refresh(job)
    return job
