"""Saving a user's reading position, shared by the reader and the activity inbox."""

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress


def save_reading_progress(db: Session, *, user_id: int, chapter: Chapter, position: int, percent: float) -> ReadingProgress:
    """Store the user's position in ``chapter`` and add a compact daily history point. Commits."""
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == user_id,
        ReadingProgress.novel_id == chapter.novel_id,
    ).first()
    if not progress:
        progress = ReadingProgress(user_id=user_id, novel_id=chapter.novel_id)
        db.add(progress)
    progress.chapter_id = chapter.id
    progress.chapter_number = chapter.chapter_number
    progress.position = max(position, 0)
    progress.percent = min(max(percent, 0), 100)
    # Persist a compact history point once per chapter/day. It powers streaks
    # and velocity without recording raw scrolling or text selection data.
    today = date.today()
    history = db.query(ReadingHistory).filter(
        ReadingHistory.user_id == user_id,
        ReadingHistory.novel_id == chapter.novel_id,
        ReadingHistory.chapter_number == chapter.chapter_number,
        func.date(ReadingHistory.reading_date) == today.isoformat(),
    ).first()
    if history:
        history.max_percent = max(history.max_percent or 0, round(progress.percent))
    else:
        db.add(ReadingHistory(
            user_id=user_id,
            novel_id=chapter.novel_id,
            chapter_number=chapter.chapter_number,
            reading_date=datetime.combine(today, datetime.min.time()),
            max_percent=round(progress.percent),
        ))
    db.commit()
    db.refresh(progress)
    return progress
