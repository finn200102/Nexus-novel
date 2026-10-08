"""Which chapter a user should read next, given their followed categories.

The "last finished" chapter is the furthest point the user has reached, taken
from their reading progress and daily reading history. Progress is matched to
the chapter's current number through ``site_chapter_id`` so renumbered
chapters keep their place.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.services.library_organization_service import followed_categories_of


def next_unread_chapter(db: Session, user_id: int, novel: Novel) -> Chapter | None:
    """The first chapter in a followed category after the user's furthest read chapter.

    Returns None when the user is caught up on every followed chapter.
    """
    personal = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user_id, NovelPersonalData.novel_id == novel.id).first()
    categories = followed_categories_of(personal)

    query = db.query(Chapter).filter(Chapter.novel_id == novel.id, Chapter.category.in_(categories))
    last_finished = last_finished_number(db, user_id, novel.id)
    if last_finished is not None:
        query = query.filter(Chapter.chapter_number > last_finished)
    return query.order_by(Chapter.chapter_number).first()


def last_finished_number(db: Session, user_id: int, novel_id: int) -> int | None:
    """Furthest chapter number the user has reached, or None if they never read this novel."""
    numbers: list[int] = []

    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == user_id, ReadingProgress.novel_id == novel_id).first()
    if progress is not None:
        current = _current_progress_number(db, progress, novel_id)
        if current is not None:
            numbers.append(current)

    history_max = (
        db.query(func.max(ReadingHistory.chapter_number))
        .filter(ReadingHistory.user_id == user_id, ReadingHistory.novel_id == novel_id)
        .scalar()
    )
    if history_max is not None:
        numbers.append(history_max)

    return max(numbers) if numbers else None


def _current_progress_number(db: Session, progress: ReadingProgress, novel_id: int) -> int | None:
    """Progress chapter's number now: matched by site_chapter_id, else the stored number."""
    chapter = db.get(Chapter, progress.chapter_id) if progress.chapter_id is not None else None
    if chapter is not None and chapter.site_chapter_id is not None:
        match = (
            db.query(Chapter.chapter_number)
            .filter(Chapter.novel_id == novel_id, Chapter.site_chapter_id == chapter.site_chapter_id)
            .first()
        )
        if match is not None:
            return match[0]
    if chapter is not None:
        return chapter.chapter_number
    return progress.chapter_number


def attach_next_unread(db: Session, user_id: int, novels: list[Novel]) -> None:
    """Set ``next_unread_chapter_id`` / ``next_unread_chapter_number`` on each novel.

    One query per novel, which is fine for library pages of up to 100 novels.
    """
    for novel in novels:
        chapter = next_unread_chapter(db, user_id, novel)
        novel.next_unread_chapter_id = chapter.id if chapter else None
        novel.next_unread_chapter_number = chapter.chapter_number if chapter else None
