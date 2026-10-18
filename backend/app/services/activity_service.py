from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.chapter_manifest import ChapterManifestState

from app.models.chapter import Chapter
from app.models.user import User
from app.models.reading_progress import ReadingProgress
from app.models.download_job import ChapterDownloadJob
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.update_event import NovelUpdateEvent
from app.services.library_organization_service import followed_categories_of
from app.services.reading_order import last_finished_number, next_unread_chapter
from app.services.reading_progress_service import save_server_selected_position


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


def _event_chapter_numbers(event: NovelUpdateEvent) -> set[int]:
    numbers = (event.details or {}).get("chapter_numbers")
    if numbers:
        return {int(number) for number in numbers}
    return set()


def _unread_visible_events(db: Session, user_id: int, *, novel_id: int | None = None, library_id: int | None = None):
    query = db.query(NovelUpdateEvent, Novel.title).join(Novel, Novel.id == NovelUpdateEvent.novel_id).filter(
        NovelUpdateEvent.user_id == user_id,
        NovelUpdateEvent.read_at.is_(None),
        NovelUpdateEvent.notification_visible.is_(True),
    )
    if novel_id is not None:
        query = query.filter(NovelUpdateEvent.novel_id == novel_id)
    if library_id is not None:
        query = query.filter(Novel.library_id == library_id)
    return query.order_by(NovelUpdateEvent.created_at.desc(), NovelUpdateEvent.id.desc())


def inbox(db: Session, *, user_id: int, library_id: int) -> list[dict]:
    """Unread update events grouped per novel, newest first.

    Only chapters in the user's followed categories count. Novels whose unread
    events only mention other categories are left out of the inbox.
    """
    groups: dict[int, dict] = {}
    for event, title in _unread_visible_events(db, user_id, library_id=library_id).all():
        group = groups.setdefault(event.novel_id, {"title": title, "events": []})
        group["events"].append(event)

    rows = []
    for novel_id, group in groups.items():
        novel = db.get(Novel, novel_id)
        personal = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user_id, NovelPersonalData.novel_id == novel_id).first()
        keys=set();numbers=set();ranges=[]
        for event in group['events']:
            details=event.details or {}
            if 'chapter_keys' in details:
                if isinstance(details['chapter_keys'],list):keys.update(key for key in details['chapter_keys'] if isinstance(key,str))
                continue  # Explicit UUID evidence never falls back to numeric labels.
            numbers.update(_event_chapter_numbers(event))
            if not details.get('chapter_numbers') and event.first_chapter_number is not None and event.last_chapter_number is not None:
                ranges.append((event.first_chapter_number,event.last_chapter_number))
        query=db.query(Chapter.chapter_number).filter(Chapter.novel_id==novel_id,
            Chapter.category.in_(followed_categories_of(personal)))
        # Keep the legacy gate inside each SQL statement so a concurrent review
        # cannot turn an earlier "legacy allowed" read into a replacement join.
        legacy_allowed=~db.query(ChapterManifestState.novel_id).filter(
            ChapterManifestState.novel_id==novel_id,ChapterManifestState.identity_required.is_(True)).exists()
        found=set()
        for values,column,legacy in ((sorted(keys),Chapter.chapter_key,False),(sorted(numbers),Chapter.chapter_number,True)):
            for start in range(0,len(values),500):
                selected=query.filter(column.in_(values[start:start+500]))
                if legacy:selected=selected.filter(legacy_allowed)
                found.update(number for number, in selected.all())
        for start in range(0,len(ranges),100):
            intervals=[Chapter.chapter_number.between(low,high) for low,high in ranges[start:start+100]]
            found.update(number for number, in query.filter(legacy_allowed,or_(*intervals)).all())
        new_numbers=sorted(found)
        if not new_numbers:
            continue
        next_chapter = next_unread_chapter(db, user_id, novel)
        rows.append({
            "novel_id": novel_id,
            "title": group["title"],
            "new_chapter_count": len(new_numbers),
            "first_new_chapter_number": new_numbers[0],
            "latest_at": group["events"][0].created_at,
            "event_ids": [event.id for event in group["events"]],
            "next_unread_chapter_id": next_chapter.id if next_chapter else None,
            "next_unread_chapter_number": next_chapter.chapter_number if next_chapter else None,
        })
    return rows


def unread_story_count(db: Session, *, user_id: int, library_id: int) -> int:
    """The one unread-updates count: story groups in the inbox.

    Bell badge, Home "New chapters", Activity inbox and the operations summary
    all use this so they can never disagree.
    """
    return len(inbox(db, user_id=user_id, library_id=library_id)) + len(_unread_new_work_keys(db, user_id))


def _unread_new_work_keys(db: Session, user_id: int) -> set[str]:
    """One key per unread author/series new-work event, so a work counts once.

    New-work events have no novel (they are not tied to a library), so they sit
    outside the inbox groups. Events without a work_key count on their own.
    """
    from app.services.creator_follow_service import NEW_WORK_EVENTS

    rows = db.query(NovelUpdateEvent.id, NovelUpdateEvent.details).filter(
        NovelUpdateEvent.user_id == user_id,
        NovelUpdateEvent.event_type.in_(NEW_WORK_EVENTS),
        NovelUpdateEvent.read_at.is_(None),
        NovelUpdateEvent.notification_visible.is_(True),
    ).all()
    return {str((details or {}).get("work_key") or f"event:{event_id}") for event_id, details in rows}


def mark_novel_read(db: Session, user_id: int, novel_id: int) -> int:
    """Mark the novel's unread visible events read. Does not commit."""
    ids = [event.id for event, _ in _unread_visible_events(db, user_id, novel_id=novel_id).all()]
    if not ids:
        return 0
    return db.query(NovelUpdateEvent).filter(NovelUpdateEvent.id.in_(ids)).update(
        {NovelUpdateEvent.read_at: datetime.now(UTC)}, synchronize_session=False
    )


def catch_up(db: Session, user_id: int, novel: Novel) -> dict:
    """Mark the novel's unread events read and move progress to its latest followed chapter.

    Progress only moves forward: a user already past the latest followed chapter
    keeps their place.
    """
    db.query(User).filter_by(id=user_id).with_for_update().first()
    current_progress=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel.id).populate_existing().first()
    if current_progress is None:
        from app.services.reading_run_service import current_run,restore_progress
        current_progress=restore_progress(current_run(db,user_id,novel.id))
    personal = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user_id, NovelPersonalData.novel_id == novel.id).first()
    latest = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel.id, Chapter.category.in_(followed_categories_of(personal)))
        .order_by(Chapter.chapter_number.desc())
        .with_for_update()
        .first()
    )
    updated = mark_novel_read(db, user_id, novel.id)
    progress_chapter = None
    if latest is not None:
        furthest = last_finished_number(db, user_id, novel.id)
        if furthest is None or latest.chapter_number > furthest:
            from app.services.chapter_identity_service import manifest_state,state_fields
            header=state_fields(manifest_state(db,novel.id,lock=True))
            save_server_selected_position(db, user_id=user_id, chapter=latest, position=0, percent=100,
                expected_chapter_key=latest.chapter_key,expected_manifest_epoch=header['manifest_epoch'],expected_manifest_revision=header['manifest_revision'],
                expected_revision=(current_progress.revision or 0) if current_progress else 0,
                reading_run_key=current_progress.reading_run_key if current_progress else None)
            progress_chapter = latest.chapter_number
    db.commit()
    return {"updated": updated, "progress_chapter_number": progress_chapter}
