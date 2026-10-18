from datetime import UTC, datetime
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from config.database import get_db
from app.auth.dependencies import get_current_user, require_admin
from config.settings import settings
from app.models.download_job import ChapterDownloadJob
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services.activity_service import unread_story_count
from app.schemas.operations import OperationCounts, OperationsSummary, ServiceStatus
from app.services import metadata_client
from .catalog_scrape import CatalogAdministrator, administrator as schedule_administrator, reauthorize

router = APIRouter(prefix="/operations", tags=["operations"])

_METADATA_SNAPSHOT_TTL = 5.0
_metadata_snapshot: tuple[float, OperationCounts, dict[str, int], int] | None = None
_metadata_status_snapshot: tuple[float, ServiceStatus] | None = None


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
    headers = {"X-API-Key": settings.METADATA_API_KEY} if settings.METADATA_API_KEY else {}
    return httpx.get(
        f"{settings.METADATA_SERVER_URL}{path}",
        timeout=httpx.Timeout(3.0, connect=1.0),
        headers=headers,
    )


def _metadata_proxy(method: str, path: str, **kwargs):
    try:
        headers = dict(kwargs.pop("headers", {}) or {})
        if settings.METADATA_API_KEY:
            headers.setdefault("X-API-Key", settings.METADATA_API_KEY)
        response = httpx.request(
            method,
            f"{settings.METADATA_SERVER_URL}{path}",
            timeout=httpx.Timeout(3.0, connect=1.0),
            headers=headers,
            **kwargs,
        )
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
    global _metadata_status_snapshot
    now = time.monotonic()
    if _metadata_status_snapshot and now - _metadata_status_snapshot[0] < 5.0:
        return _metadata_status_snapshot[1]
    checked_at = datetime.now(UTC)
    try:
        response = _metadata_get("/ready")
        if response.status_code == 200:
            value = ServiceStatus(status="online", detail="Metadata API and database ready", checked_at=checked_at)
        else:
            value = ServiceStatus(status="degraded", detail=f"Readiness returned HTTP {response.status_code}", checked_at=checked_at)
    except httpx.HTTPError:
        value = ServiceStatus(status="offline", detail="Metadata service did not respond before the timeout", checked_at=checked_at)
    _metadata_status_snapshot = (now, value)
    return value


def _metadata_operations() -> tuple[OperationCounts, dict[str, int], int]:
    global _metadata_snapshot
    now = time.monotonic()
    if _metadata_snapshot and now - _metadata_snapshot[0] < _METADATA_SNAPSHOT_TTL:
        return _metadata_snapshot[1], _metadata_snapshot[2], _metadata_snapshot[3]
    jobs = OperationCounts()
    health: dict[str, int] = {}
    schedules = 0
    try:
        job_response = _metadata_get("/api/jobs/summary")
        if job_response.status_code == 200:
            statuses = job_response.json()
            jobs = OperationCounts(
                queued=int(statuses.get("queued", 0)),
                running=int(statuses.get("running", 0)),
                completed=int(statuses.get("completed", 0)),
                failed=int(statuses.get("failed", 0)),
                cancelled=int(statuses.get("cancelled", 0)),
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
    _metadata_snapshot = (now, jobs, health, schedules)
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

    unread_updates = unread_story_count(db, user_id=current_user.id, library_id=library_id)
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


_SCHEDULE_PRIVATE = {"Cache-Control":"private, no-store"}
_AO3_REFRESH_ERRORS = frozenset({
    "AO3 refreshes require an explicit reader action; recurring refreshes are unavailable",
    "AO3 refreshes require an explicit reader action",
})


async def _schedule_proxy(admin: CatalogAdministrator, method: str, path: str, **kwargs):
    # Release the auth read snapshot before I/O and fence the response with a
    # fresh session/account/admin check, including upstream error responses.
    await run_in_threadpool(reauthorize, admin)
    try:
        response = await metadata_client._request(method,path,admin=True,timeout=httpx.Timeout(10.0,connect=2.0),**kwargs)
        result = response.json() if response.content else {"success":True}
    except Exception as exc:
        await run_in_threadpool(reauthorize, admin)
        cause = exc.__cause__
        if isinstance(cause,httpx.HTTPStatusError):
            status = cause.response.status_code
            try:
                payload = cause.response.json()
                detail = payload.get("detail") if isinstance(payload,dict) else None
            except ValueError:
                detail = None
            if status==400 and isinstance(detail,str) and detail in _AO3_REFRESH_ERRORS:
                error={"code":"user_initiated_refresh_required","message":"AO3 refreshes require an explicit reader action. Recurring refresh schedules and background schedule runs are unavailable."}
            else:
                error={"code":"refresh_schedule_rejected","message":{400:"These refresh schedule settings are not allowed. Review the source policy and schedule limits.",403:"The metadata service could not authorize this administrator action.",404:"This refresh schedule is no longer available.",409:"The refresh schedule changed. Refresh the list before trying again.",422:"Review the refresh interval, batch size, and source."}.get(status,"The refresh schedule service could not complete this action.")}
            raise HTTPException(status if 400<=status<600 else 502,detail=error,headers=_SCHEDULE_PRIVATE) from exc
        timeout = isinstance(cause,httpx.TimeoutException) or isinstance(exc,httpx.TimeoutException)
        raise HTTPException(504 if timeout else 503,detail={"code":"refresh_schedule_timeout" if timeout else "refresh_schedule_unavailable","message":"The refresh schedule service did not respond in time. Refresh its status before retrying." if timeout else "The refresh schedule service is unavailable. Existing schedules are retained."},headers=_SCHEDULE_PRIVATE) from exc
    await run_in_threadpool(reauthorize, admin)
    return result


@router.get("/schedules")
async def list_refresh_schedules(admin: CatalogAdministrator = Depends(schedule_administrator)):
    return await _schedule_proxy(admin,"GET","/api/refresh-schedules/")


@router.post("/schedules",status_code=201)
async def create_refresh_schedule(request: RefreshScheduleCreate,admin: CatalogAdministrator = Depends(schedule_administrator)):
    return await _schedule_proxy(admin,"POST","/api/refresh-schedules/",json=request.model_dump())


@router.patch("/schedules/{schedule_id}")
async def update_refresh_schedule(schedule_id: str,request: RefreshScheduleUpdate,admin: CatalogAdministrator = Depends(schedule_administrator)):
    return await _schedule_proxy(admin,"PATCH",f"/api/refresh-schedules/{schedule_id}",json=request.model_dump(exclude_none=True))


@router.post("/schedules/{schedule_id}/run")
async def run_refresh_schedule(schedule_id: str,admin: CatalogAdministrator = Depends(schedule_administrator)):
    return await _schedule_proxy(admin,"POST",f"/api/refresh-schedules/{schedule_id}/run")


@router.delete("/schedules/{schedule_id}")
async def delete_refresh_schedule(schedule_id: str,admin: CatalogAdministrator = Depends(schedule_administrator)):
    return await _schedule_proxy(admin,"DELETE",f"/api/refresh-schedules/{schedule_id}")


@router.get("/metadata-jobs")
def list_metadata_jobs(
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_admin),
):
    params = {"limit": limit}
    if status:
        params["status"] = status
    if job_type:
        params["job_type"] = job_type
    return _metadata_proxy("GET", "/api/jobs/", params=params)


@router.post("/metadata-jobs/{job_id}/retry")
def retry_metadata_job(job_id: str, current_user: User = Depends(require_admin)):
    return _metadata_proxy("POST", f"/api/jobs/{job_id}/retry")


@router.delete("/metadata-jobs/{job_id}")
def cancel_metadata_job(job_id: str, current_user: User = Depends(require_admin)):
    return _metadata_proxy("DELETE", f"/api/jobs/{job_id}")


@router.post("/metadata-jobs/{job_id}/archive")
def archive_metadata_job(job_id: str, current_user: User = Depends(require_admin)):
    return _metadata_proxy("POST", f"/api/jobs/{job_id}/archive")


@router.post("/metadata-jobs/archive-failed")
def archive_failed_metadata_jobs(current_user: User = Depends(require_admin)):
    return _metadata_proxy("POST", "/api/jobs/archive-failed")


@router.get("/source-health")
def list_source_health(current_user: User = Depends(require_admin)):
    return _metadata_proxy("GET", "/api/jobs/source-health")


@router.get("/source-policy")
def source_policy(hours: int = Query(default=24, ge=1, le=720), current_user: User = Depends(require_admin)):
    return _metadata_proxy("GET", "/source-policy/summary", params={"hours": hours})


@router.post("/source-health/{site}/reset")
def reset_source_health(site: str, current_user: User = Depends(require_admin)):
    return _metadata_proxy("POST", f"/api/jobs/source-health/{site}/reset")
