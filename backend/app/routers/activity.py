from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.download_job import ChapterDownloadJob
from app.models.novel import Novel
from app.models.user import User
from app.models.update_event import NovelUpdateEvent
from app.schemas.activity import ActivityDay, ActivityEventResponse, ActivitySummary, InboxNovelResponse
from app.services.activity_service import activity_days, activity_events, catch_up, inbox, mark_novel_read
from app.services.library_organization_service import owned_novel

router = APIRouter(prefix="/activity", tags=["activity"])


@router.post("/read-all")
def mark_all_read(library_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Update events belong to a novel, and the novel to a library.
    library_novels = db.query(Novel.id).filter(Novel.library_id == library_id)
    updated = db.query(NovelUpdateEvent).filter(
        NovelUpdateEvent.user_id == current_user.id,
        NovelUpdateEvent.novel_id.in_(library_novels),
        NovelUpdateEvent.read_at.is_(None),
        NovelUpdateEvent.notification_visible.is_(True),
    ).update({NovelUpdateEvent.read_at: datetime.now(UTC)}, synchronize_session=False)
    db.commit()
    return {"updated": updated}


@router.get("/inbox", response_model=list[InboxNovelResponse])
def get_inbox(library_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Unread updates per novel, newest first, counting only followed-category chapters."""
    return inbox(db, user_id=current_user.id, library_id=library_id)


@router.post("/inbox/{novel_id}/read")
def mark_inbox_novel_read(novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    novel = owned_novel(db, current_user, novel_id)
    updated = mark_novel_read(db, current_user.id, novel.id)
    db.commit()
    return {"updated": updated}


@router.post("/inbox/{novel_id}/caught-up")
def mark_inbox_novel_caught_up(novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    novel = owned_novel(db, current_user, novel_id)
    return catch_up(db, current_user.id, novel)


@router.get("/feed", response_model=list[ActivityEventResponse])
def feed(library_id: int, start_date: date | None = None, end_date: date | None = None, unread_only: bool = False, event_type: str | None = None, limit: int = Query(default=100, ge=1, le=250), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [ActivityEventResponse(id=event.id, novel_id=event.novel_id, novel_title=title, event_type=event.event_type, chapter_count=event.chapter_count, first_chapter_number=event.first_chapter_number, last_chapter_number=event.last_chapter_number, message=event.message, details=event.details or {}, notification_visible=event.notification_visible, read_at=event.read_at, created_at=event.created_at) for event, title in activity_events(db, user_id=current_user.id, library_id=library_id, start_date=start_date, end_date=end_date, unread_only=unread_only, event_type=event_type, limit=limit)]


@router.get("/calendar", response_model=list[ActivityDay])
def calendar(library_id: int, start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return activity_days(db, user_id=current_user.id, library_id=library_id, start_date=start_date, end_date=end_date)


@router.get("/summary", response_model=ActivitySummary)
def summary(library_id: int, start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=6))
    rows = activity_events(db, user_id=current_user.id, library_id=library_id, start_date=start, end_date=end, limit=2500)
    completed = db.query(ChapterDownloadJob.id).filter(ChapterDownloadJob.user_id == current_user.id, ChapterDownloadJob.library_id == library_id, ChapterDownloadJob.status == "completed", ChapterDownloadJob.finished_at.isnot(None)).all()
    return ActivitySummary(start_date=start, end_date=end, event_count=len(rows), chapter_count=sum(event.chapter_count or 0 for event, _ in rows), stories_resumed=sum(event.event_type == "story_resumed" for event, _ in rows), source_failures=sum(event.event_type == "source_failed" for event, _ in rows), downloads_completed=len(completed), unread_count=sum(event.read_at is None and event.notification_visible for event, _ in rows))
