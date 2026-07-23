from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends
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


def _metadata_get(path: str):
    return httpx.get(f"{settings.METADATA_SERVER_URL}{path}", timeout=1.0)


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
