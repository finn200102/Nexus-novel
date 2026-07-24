from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from config.settings import settings
from app.models.download_job import ChapterDownloadJob
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.schemas.operations import OperationCounts, OperationsSummary, ServiceStatus

router = APIRouter(prefix="/operations", tags=["operations"])


class RefreshScheduleCreate(BaseModel):
    site: str | None = None
    interval_minutes: int = Field(default=360, ge=15, le=10080)
    batch_size: int = Field(default=100, ge=1, le=1000)
    enabled: bool = True


class RefreshScheduleUpdate(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    batch_size: int | None = Field(default=None, ge=1, le=1000)
    enabled: bool | None = None


def _metadata_get(path: str):
    return httpx.get(f"{settings.METADATA_SERVER_URL}{path}", timeout=3.0)


def _metadata_proxy(method: str, path: str, **kwargs):
    try:
        response = httpx.request(method, f"{settings.METADATA_SERVER_URL}{path}", timeout=3.0, **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Metadata service unavailable: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail or "Metadata request failed")
    if not response.content:
        return {"success": True}
    return response.json()


def _metadata_status() -> ServiceStatus:
    checked_at = datetime.now(UTC)
    try:
        response = _metadata_get("/ready")
        if response.status_code == 200:
            return ServiceStatus(status="online", detail="Metadata API and database ready", checked_at=checked_at)
        return ServiceStatus(status="degraded", detail=f"Readiness returned HTTP {response.status_code}", checked_at=checked_at)
    except httpx.HTTPError as exc:
        return ServiceStatus(status="offline", detail=str(exc), checked_at=checked_at)


def _metadata_operations() -> tuple[OperationCounts, dict[str, int], int]:
    jobs = OperationCounts()
    health: dict[str, int] = {}
    schedules = 0
    try:
        job_response = _metadata_get("/api/jobs/?limit=500")
        if job_response.status_code == 200:
            statuses = [item.get("status") for item in job_response.json().get("data", [])]
            jobs = OperationCounts(
                queued=sum(status == "queued" for status in statuses),
                running=sum(status == "running" for status in statuses),
                completed=sum(status == "completed" for status in statuses),
                failed=sum(status == "failed" for status in statuses),
                cancelled=sum(status == "cancelled" for status in statuses),
            )
        health_response = _metadata_get("/api/jobs/source-health")
        if health_response.status_code == 200:
            for item in health_response.json():
                status = item.get("status", "unknown")
                health[status] = health.get(status, 0) + 1
        schedule_response = _metadata_get("/api/refresh-schedules/")
        if schedule_response.status_code == 200:
            schedules = len(schedule_response.json())
    except httpx.HTTPError:
        pass
    return jobs, health, schedules


@router.get("/summary", response_model=OperationsSummary)
def summary(
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    followed_query = (
        db.query(UserNovelFollow)
        .join(Novel, Novel.id == UserNovelFollow.novel_id)
        .filter(UserNovelFollow.user_id == current_user.id, Novel.library_id == library_id)
    )
    followed_stories = followed_query.count()
    reading_stories = followed_query.filter(UserNovelFollow.state == "reading").count()

    unread_updates = (
        db.query(NovelUpdateEvent)
        .join(Novel, Novel.id == NovelUpdateEvent.novel_id)
        .filter(
            NovelUpdateEvent.user_id == current_user.id,
            Novel.library_id == library_id,
            NovelUpdateEvent.read_at.is_(None),
            NovelUpdateEvent.notification_visible.is_(True),
        )
        .count()
    )
    source_failures = (
        db.query(NovelUpdateEvent)
        .join(Novel, Novel.id == NovelUpdateEvent.novel_id)
        .filter(
            NovelUpdateEvent.user_id == current_user.id,
            Novel.library_id == library_id,
            NovelUpdateEvent.event_type == "source_failed",
        )
        .count()
    )

    jobs = (
        db.query(ChapterDownloadJob.status, func.count(ChapterDownloadJob.id))
        .filter(
            ChapterDownloadJob.user_id == current_user.id,
            ChapterDownloadJob.library_id == library_id,
        )
        .group_by(ChapterDownloadJob.status)
        .all()
    )
    counts = {status: count for status, count in jobs}
    metadata_jobs, source_health, refresh_schedules = _metadata_operations()
    return OperationsSummary(
        library_id=library_id,
        followed_stories=followed_stories,
        reading_stories=reading_stories,
        unread_updates=unread_updates,
        source_failures=source_failures,
        downloads=OperationCounts(
            queued=counts.get("queued", 0) + counts.get("retry_wait", 0),
            running=counts.get("processing", 0),
            completed=counts.get("completed", 0),
            failed=counts.get("failed", 0),
            cancelled=counts.get("cancelled", 0),
        ),
        metadata_server=_metadata_status(),
        metadata_jobs=metadata_jobs,
        source_health=source_health,
        refresh_schedules=refresh_schedules,
        generated_at=datetime.now(UTC),
    )


@router.get("/schedules")
def list_refresh_schedules(current_user: User = Depends(get_current_user)):
    return _metadata_proxy("GET", "/api/refresh-schedules/")


@router.post("/schedules", status_code=201)
def create_refresh_schedule(
    request: RefreshScheduleCreate,
    current_user: User = Depends(get_current_user),
):
    return _metadata_proxy("POST", "/api/refresh-schedules/", json=request.model_dump())


@router.patch("/schedules/{schedule_id}")
def update_refresh_schedule(
    schedule_id: str,
    request: RefreshScheduleUpdate,
    current_user: User = Depends(get_current_user),
):
    return _metadata_proxy(
        "PATCH",
        f"/api/refresh-schedules/{schedule_id}",
        json=request.model_dump(exclude_none=True),
    )


@router.post("/schedules/{schedule_id}/run")
def run_refresh_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
):
    return _metadata_proxy("POST", f"/api/refresh-schedules/{schedule_id}/run")


@router.delete("/schedules/{schedule_id}")
def delete_refresh_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
):
    return _metadata_proxy("DELETE", f"/api/refresh-schedules/{schedule_id}")


@router.get("/metadata-jobs")
def list_metadata_jobs(
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    params = {"limit": limit}
    if status:
        params["status"] = status
    if job_type:
        params["job_type"] = job_type
    return _metadata_proxy("GET", "/api/jobs/", params=params)


@router.post("/metadata-jobs/{job_id}/retry")
def retry_metadata_job(job_id: str, current_user: User = Depends(get_current_user)):
    return _metadata_proxy("POST", f"/api/jobs/{job_id}/retry")


@router.delete("/metadata-jobs/{job_id}")
def cancel_metadata_job(job_id: str, current_user: User = Depends(get_current_user)):
    return _metadata_proxy("DELETE", f"/api/jobs/{job_id}")


@router.post("/metadata-jobs/{job_id}/archive")
def archive_metadata_job(job_id: str, current_user: User = Depends(get_current_user)):
    return _metadata_proxy("POST", f"/api/jobs/{job_id}/archive")


@router.get("/source-health")
def list_source_health(current_user: User = Depends(get_current_user)):
    return _metadata_proxy("GET", "/api/jobs/source-health")


@router.post("/source-health/{site}/reset")
def reset_source_health(site: str, current_user: User = Depends(get_current_user)):
    return _metadata_proxy("POST", f"/api/jobs/source-health/{site}/reset")
