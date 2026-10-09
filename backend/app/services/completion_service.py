"""Completion transitions: tell users who asked when a novel is finished."""

from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.update_event import NovelUpdateEvent

COMPLETE_STATUSES = frozenset({"complete", "completed"})


def is_complete_status(value: str | None) -> bool:
    return (value or "").strip().lower() in COMPLETE_STATUSES


def create_completion_events(db: Session, novel: Novel, old_status: str | None, new_status: str | None) -> int:
    """Create a "completed" event for each opted-in user, only on the ongoing -> complete transition.

    The caller commits. Returns the number of events added.
    """
    if is_complete_status(old_status) or not is_complete_status(new_status):
        return 0
    rows = (
        db.query(NovelPersonalData)
        .filter(NovelPersonalData.novel_id == novel.id, NovelPersonalData.notify_when_complete.is_(True))
        .all()
    )
    already = {
        user_id
        for (user_id,) in db.query(NovelUpdateEvent.user_id).filter(
            NovelUpdateEvent.novel_id == novel.id, NovelUpdateEvent.event_type == "completed"
        )
    }
    created = 0
    for row in rows:
        if row.user_id in already:
            continue
        db.add(NovelUpdateEvent(
            user_id=row.user_id,
            novel_id=novel.id,
            event_type="completed",
            message=f"{novel.title or 'This story'} is finished.",
            details={"status": new_status},
            notification_visible=True,
        ))
        created += 1
    return created
