"""Followed chapter ordering from run-scoped checkpoints.

Modern runs do not infer reading across gaps. Inferred legacy positions retain
their old Continue policy; recorded checkpoint counts remain separate.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session, defer

from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.chapter_manifest import ChapterManifestState
from app.services.reading_run_service import current_run,restore_progress
from app.services.library_organization_service import followed_categories_of
from app.services.reading_checkpoint_service import category_expression


def next_unread_chapter(db: Session, user_id: int, novel: Novel) -> Chapter | None:
    """Current run's first followed chapter lacking a recorded completion."""
    progress=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel.id).first()
    run=current_run(db,user_id,novel.id,progress)
    if progress is None:progress=restore_progress(run)
    return next_unread_for_run(db,user_id,novel.id,progress,run)


def next_unread_for_run(db,user_id,novel_id,progress,run):
    """Shared current/journal policy; never loads private chapter bodies."""
    personal=db.query(NovelPersonalData).filter_by(user_id=user_id,novel_id=novel_id).first()
    categories=followed_categories_of(personal)
    query=db.query(Chapter).options(defer(Chapter.content),defer(Chapter.document)).filter(
        Chapter.novel_id==novel_id,category_expression().in_(categories))
    identity_required=bool(db.query(ChapterManifestState.identity_required).filter_by(novel_id=novel_id).scalar())
    if identity_required or (run is not None and (run.requires_run_key or not run.started_at_inferred)):
        from app.services.reading_checkpoint_service import checkpoint_rows
        checkpoints=checkpoint_rows(db,user_id,novel_id,progress,run)
        query=query.outerjoin(checkpoints,checkpoints.c.chapter_number==Chapter.chapter_number).filter(func.coalesce(checkpoints.c.max_percent,0)<95)
    else:
        # Retain explicitly inferred legacy Continue positions. Recorded
        # completion COUNTS remain conservative even for these old positions.
        numbers=[]
        if progress is not None:
            number=_current_progress_number(db,progress,novel_id)
            if number is not None:numbers.append(number)
        history=db.query(func.max(ReadingHistory.chapter_number)).filter_by(user_id=user_id,novel_id=novel_id)
        history=history.filter(ReadingHistory.reading_run_key==run.run_key) if run is not None else history.filter(ReadingHistory.reading_run_key.is_(None))
        maximum=history.scalar()
        if maximum is not None:numbers.append(maximum)
        if numbers:query=query.filter(Chapter.chapter_number>max(numbers))
    return query.order_by(Chapter.chapter_number,Chapter.id).first()


def last_finished_number(db: Session, user_id: int, novel_id: int) -> int | None:
    """Furthest chapter number the user has reached, or None if they never read this novel."""
    numbers: list[int] = []

    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == user_id, ReadingProgress.novel_id == novel_id).first()
    run = current_run(db,user_id,novel_id,progress)
    if progress is None:progress=restore_progress(run)
    identity_required=bool(db.query(ChapterManifestState.identity_required).filter_by(novel_id=novel_id).scalar())
    if identity_required or (run is not None and (run.requires_run_key or not run.started_at_inferred)):
        from app.services.reading_checkpoint_service import checkpoint_rows
        checkpoints=checkpoint_rows(db,user_id,novel_id,progress,run)
        return db.query(func.max(checkpoints.c.chapter_number)).filter(checkpoints.c.max_percent>=95).scalar()
    if progress is not None:
        current = _current_progress_number(db, progress, novel_id)
        if current is not None:
            numbers.append(current)

    history_query = (
        db.query(func.max(ReadingHistory.chapter_number))
        .filter(ReadingHistory.user_id == user_id, ReadingHistory.novel_id == novel_id)
    )
    if run is not None:history_query=history_query.filter(ReadingHistory.reading_run_key==run.run_key)
    history_max=history_query.scalar()
    if history_max is not None:
        numbers.append(history_max)

    return max(numbers) if numbers else None


def _current_progress_number(db: Session, progress: ReadingProgress, novel_id: int) -> int | None:
    """Resolve current owned UUID, retaining numeric fallback only before review."""
    key=getattr(progress,'chapter_key',None)
    if key is not None:
        return db.query(Chapter.chapter_number).filter_by(novel_id=novel_id,chapter_key=key).scalar()
    required=bool(db.query(ChapterManifestState.identity_required).filter_by(novel_id=novel_id).scalar())
    if required:return None
    chapter = db.query(Chapter).filter_by(id=progress.chapter_id,novel_id=novel_id).first() if progress.chapter_id is not None else None
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
