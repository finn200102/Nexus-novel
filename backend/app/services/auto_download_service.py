"""Queue downloads ahead of a user's reading position when new chapters arrive."""

from sqlalchemy.orm import Session

from app.models.chapter import Chapter, ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.services.library_organization_service import DEFAULT_KEEP_AHEAD, MAX_KEEP_AHEAD, MIN_KEEP_AHEAD, followed_categories_of
from app.services.reading_order import last_finished_number

# Upper bound on jobs one new-chapter event may queue, however large keep_ahead is.
AUTO_DOWNLOAD_RUN_CAP = 50


def queue_auto_downloads(db: Session, *, user_id: int, library_id: int, novel: Novel) -> int:
    """Queue the next ``keep_ahead`` undownloaded followed chapters after the user's position.

    Does nothing unless the user turned auto-download on for this novel. Chapters
    that already have a queued or processing job are not queued again. Returns
    the number of jobs added; the caller commits.
    """
    personal = db.query(NovelPersonalData).filter(
        NovelPersonalData.user_id == user_id,
        NovelPersonalData.novel_id == novel.id,
    ).first()
    if personal is None or not personal.auto_download:
        return 0
    keep_ahead = min(max(personal.keep_ahead or DEFAULT_KEEP_AHEAD, MIN_KEEP_AHEAD), MAX_KEEP_AHEAD)

    query = db.query(Chapter).filter(
        Chapter.novel_id == novel.id,
        Chapter.category.in_(followed_categories_of(personal)),
        Chapter.content_status != ContentStatus.PRESENT,
    )
    position = last_finished_number(db, user_id, novel.id)
    if position is not None:
        query = query.filter(Chapter.chapter_number > position)
    window = query.order_by(Chapter.chapter_number).limit(keep_ahead).all()

    db.flush()  # jobs queued earlier in this session must count as active
    active = {
        chapter_id
        for (chapter_id,) in db.query(ChapterDownloadJob.chapter_id).filter(
            ChapterDownloadJob.user_id == user_id,
            ChapterDownloadJob.novel_id == novel.id,
            ChapterDownloadJob.status.in_({"queued", "processing"}),
        ).all()
    }
    to_queue = [chapter for chapter in window if chapter.id not in active][:AUTO_DOWNLOAD_RUN_CAP]
    for chapter in to_queue:
        db.add(ChapterDownloadJob(user_id=user_id, library_id=library_id, novel_id=novel.id, chapter_id=chapter.id))
    return len(to_queue)
