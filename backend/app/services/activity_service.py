from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.download_job import ChapterDownloadJob
from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent


def _bounds(start_date: date | None, end_date: date | None) -> tuple[datetime, datetime]:
    end = end_date or datetime.now(UTC).date()
    start = start_date or (end - timedelta(days=30))
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def activity_events(db: Session, *, user_id: int, library_id: int, start_date: date | None = None, end_date: date | None = None, unread_only: bool = False, event_type: str | None = None, limit: int = 100):
    start, end = _bounds(start_date, end_date)
    query = db.query(NovelUpdateEvent, Novel.title).join(Novel, Novel.id == NovelUpdateEvent.novel_id).filter(
        NovelUpdateEvent.user_id == user_id,
        Novel.library_id == library_id,
        NovelUpdateEvent.created_at >= start,
        NovelUpdateEvent.created_at < end,
    )
    if unread_only:
        query = query.filter(NovelUpdateEvent.read_at.is_(None))
    if event_type:
        query = query.filter(NovelUpdateEvent.event_type == event_type)
    return query.order_by(NovelUpdateEvent.created_at.desc()).limit(min(max(limit, 1), 250)).all()


def activity_days(db: Session, *, user_id: int, library_id: int, start_date: date | None = None, end_date: date | None = None):
    start, end = _bounds(start_date, end_date)
    rows = activity_events(db, user_id=user_id, library_id=library_id, start_date=start.date(), end_date=(end - timedelta(days=1)).date(), limit=2500)
    days = defaultdict(lambda: {"event_count": 0, "chapter_count": 0, "stories_resumed": 0, "source_failures": 0, "downloads_completed": 0})
    for event, _ in rows:
        key = event.created_at.date()
        day = days[key]
        day["event_count"] += 1
        day["chapter_count"] += event.chapter_count or 0
        day["stories_resumed"] += 1 if event.event_type == "story_resumed" else 0
        day["source_failures"] += 1 if event.event_type == "source_failed" else 0
    completed = db.query(ChapterDownloadJob.finished_at).filter(
        ChapterDownloadJob.user_id == user_id,
        ChapterDownloadJob.library_id == library_id,
        ChapterDownloadJob.status == "completed",
        ChapterDownloadJob.finished_at >= start,
        ChapterDownloadJob.finished_at < end,
    ).all()
    for (finished_at,) in completed:
        days[finished_at.date()]["downloads_completed"] += 1
    return [{"date": key, **days[key]} for key in sorted(days)]
