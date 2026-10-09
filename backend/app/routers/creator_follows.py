"""Follow authors and series across sites, and their new-work updates."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.creator_follow import CreatorFollow
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services import metadata_client
from app.services.creator_follow_service import (
    NEW_WORK_EVENTS,
    FollowTargetRejected,
    follow,
    present,
    unfollow,
)
from config.database import get_db

router = APIRouter(prefix="/following", tags=["following"])


class FollowRequest(BaseModel):
    kind: str = Field(pattern="^(author|series)$")
    site: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    metadata_author_id: int | None = None


@router.get("")
def list_following(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(CreatorFollow)
        .filter(CreatorFollow.user_id == current_user.id)
        .order_by(CreatorFollow.kind, CreatorFollow.name, CreatorFollow.id)
        .all()
    )
    return [present(row) for row in rows]


@router.post("", status_code=201)
async def create_follow(body: FollowRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        row = await follow(
            db, user_id=current_user.id, kind=body.kind, site=body.site, key=body.key,
            name=body.name, metadata_author_id=body.metadata_author_id,
        )
    except FollowTargetRejected as exc:
        raise HTTPException(status_code=422, detail=f"This {body.kind} cannot be followed on {body.site}") from exc
    return present(row)


@router.delete("/{follow_id}", status_code=204)
async def delete_follow(follow_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(CreatorFollow).filter(CreatorFollow.id == follow_id, CreatorFollow.user_id == current_user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Not following this")
    await unfollow(db, row)


@router.get("/new-works")
def new_works(
    unread_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """New works by followed authors and new entries in followed series."""
    query = db.query(NovelUpdateEvent).filter(
        NovelUpdateEvent.user_id == current_user.id,
        NovelUpdateEvent.event_type.in_(NEW_WORK_EVENTS),
    )
    if unread_only:
        query = query.filter(NovelUpdateEvent.read_at.is_(None))
    rows = query.order_by(NovelUpdateEvent.created_at.desc(), NovelUpdateEvent.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "message": row.message,
            "created_at": row.created_at,
            "read_at": row.read_at,
            **{key: (row.details or {}).get(key) for key in ("title", "url", "site", "metadata_id", "author", "follow")},
        }
        for row in rows
    ]


@router.post("/new-works/read")
def mark_new_works_read(
    event_ids: list[int] | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Mark the given new-work events read, or all of them without ids."""
    query = db.query(NovelUpdateEvent).filter(
        NovelUpdateEvent.user_id == current_user.id,
        NovelUpdateEvent.event_type.in_(NEW_WORK_EVENTS),
        NovelUpdateEvent.read_at.is_(None),
    )
    if event_ids:
        query = query.filter(NovelUpdateEvent.id.in_(event_ids))
    now = datetime.utcnow()
    updated = 0
    for row in query.all():
        row.read_at = now
        updated += 1
    db.commit()
    return {"updated": updated}


@router.get("/authors/{metadata_author_id}")
async def author_page(metadata_author_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """An author's works across sites, with the user's follow per site profile."""
    try:
        data = await metadata_client.get_author_works(metadata_author_id)
    except RuntimeError as exc:
        status = 404 if "HTTP 404" in str(exc) else 502
        raise HTTPException(status_code=status, detail="Author not found" if status == 404 else str(exc)) from exc
    follows = {
        (row.site, row.target_key): row.id
        for row in db.query(CreatorFollow).filter(CreatorFollow.user_id == current_user.id, CreatorFollow.kind == "author")
    }
    for profile in data.get("profiles", []):
        profile["follow_id"] = follows.get((profile.get("site"), profile.get("key")))
    return data
