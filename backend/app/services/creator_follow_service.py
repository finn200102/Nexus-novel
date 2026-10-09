"""Following authors and series across sites (F1).

Follows live here; the metadata server only learns how many readers follow
each target, refreshes followed targets daily and sends ``author_new_work`` /
``series_new_work`` webhook events. Each event becomes one update event per
follower, deduplicated per work, so a work in a followed series by a followed
author shows up once.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.creator_follow import CreatorFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent
from app.services import metadata_client

KINDS = ("author", "series")
NEW_WORK_EVENTS = ("author_new_work", "series_new_work")
# How far back a user's new-work events are checked for a duplicate work.
DEDUPE_WINDOW = 500


class FollowTargetRejected(ValueError):
    """The metadata server cannot follow this target (unsupported site or kind)."""


def present(follow: CreatorFollow) -> dict:
    return {
        "id": follow.id,
        "kind": follow.kind,
        "site": follow.site,
        "key": follow.target_key,
        "name": follow.name,
        "metadata_author_id": follow.metadata_author_id,
        "metadata_target_id": follow.metadata_target_id,
        "created_at": follow.created_at,
    }


def _followers(db: Session, kind: str, site: str, key: str) -> list[CreatorFollow]:
    return db.query(CreatorFollow).filter(
        CreatorFollow.kind == kind, CreatorFollow.site == site, CreatorFollow.target_key == key
    ).all()


async def sync_target(db: Session, kind: str, site: str, key: str, name: str | None) -> dict:
    """Report the current follower count; remembers the server's target id."""
    followers = _followers(db, kind, site, key)
    target = await metadata_client.put_follow_target(kind, site, key, name, len(followers))
    for follow in followers:
        follow.metadata_target_id = target.get("id")
    db.commit()
    return target


async def follow(
    db: Session, *, user_id: int, kind: str, site: str, key: str, name: str | None, metadata_author_id: int | None = None,
) -> CreatorFollow:
    key = key.strip()
    if kind not in KINDS or not site or not key:
        raise FollowTargetRejected("kind must be author or series, with a site and key")
    existing = db.query(CreatorFollow).filter(
        CreatorFollow.user_id == user_id, CreatorFollow.kind == kind,
        CreatorFollow.site == site, CreatorFollow.target_key == key,
    ).first()
    if existing:
        return existing
    created = CreatorFollow(
        user_id=user_id, kind=kind, site=site, target_key=key, name=(name or None), metadata_author_id=metadata_author_id,
    )
    db.add(created)
    db.commit()
    try:
        await sync_target(db, kind, site, key, name)
    except RuntimeError as exc:
        if "HTTP 422" in str(exc):
            db.delete(created)
            db.commit()
            raise FollowTargetRejected(str(exc)) from exc
        # The server is down: keep the follow; the next follow/unfollow of the
        # target re-sends the count.
    db.refresh(created)
    return created


async def unfollow(db: Session, follow_row: CreatorFollow) -> None:
    kind, site, key, name = follow_row.kind, follow_row.site, follow_row.target_key, follow_row.name
    db.delete(follow_row)
    db.commit()
    try:
        await sync_target(db, kind, site, key, name)
    except RuntimeError:
        pass


def _already_has_work(db: Session, user_id: int, work_key: str, metadata_id: int | None) -> bool:
    if metadata_id:
        in_library = (
            db.query(Novel.id)
            .join(Library, Novel.library_id == Library.id)
            .filter(Library.user_id == user_id, Novel.metadata_id == metadata_id)
            .first()
        )
        if in_library:
            return True
    recent = (
        db.query(NovelUpdateEvent.details)
        .filter(NovelUpdateEvent.user_id == user_id, NovelUpdateEvent.event_type.in_(NEW_WORK_EVENTS))
        .order_by(NovelUpdateEvent.id.desc())
        .limit(DEDUPE_WINDOW)
        .all()
    )
    return any((details or {}).get("work_key") == work_key for (details,) in recent)


def handle_new_work_event(db: Session, event_type: str, payload: dict) -> int:
    """Create one update event per follower of the target. Does not commit."""
    target = payload.get("target") or {}
    work = payload.get("work") or {}
    kind = target.get("kind")
    if event_type not in NEW_WORK_EVENTS or kind not in KINDS or not work.get("url"):
        return 0
    site = target.get("site") or payload.get("site")
    key = str(target.get("key") or "")
    query = db.query(CreatorFollow).filter(CreatorFollow.kind == kind, CreatorFollow.site == site)
    follows = query.filter(CreatorFollow.target_key == key).all() if key else []
    if not follows and target.get("id"):
        follows = query.filter(CreatorFollow.metadata_target_id == target["id"]).all()

    metadata_id = work.get("metadata_id") or None
    work_key = f"metadata:{metadata_id}" if metadata_id else f"url:{work['url']}"
    created = 0
    for follow_row in follows:
        if _already_has_work(db, follow_row.user_id, work_key, metadata_id):
            continue
        name = follow_row.name or target.get("name")
        title = work.get("title") or "A new work"
        message = f"New work by {name}: {title}" if kind == "author" else f"New in {name}: {title}"
        db.add(NovelUpdateEvent(
            user_id=follow_row.user_id,
            novel_id=None,
            event_type=event_type,
            message=message,
            details={
                "work_key": work_key,
                "title": title,
                "url": work["url"],
                "site": site,
                "metadata_id": metadata_id,
                "author": work.get("author"),
                "follow": {"id": follow_row.id, "kind": kind, "name": name},
            },
            notification_visible=True,
        ))
        db.flush()
        created += 1
    return created
