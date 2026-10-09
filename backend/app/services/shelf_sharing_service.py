"""Shared shelves between users of one instance (household feature).

Policy ("never redistribute", backlog theme F): a shared shelf exposes
catalog references only — title, author, cover link, source link, and the
owner's notes when the owner opts in. It never exposes the owner's library
novel ids, chapter text, EPUBs or audio; every content endpoint keeps
checking library ownership. A recipient adds a story to their own library
and downloads it themselves.

Permissions: ``view`` lists the shelf; ``collaborate`` may also put stories
from the recipient's own library on it and take off the ones they added.
"""

import asyncio

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.shelf import SHARE_PERMISSIONS, Shelf, ShelfNovel, ShelfShare
from app.models.user import User
from app.services import content_limit_service, metadata_client
from app.services.library_organization_service import owned_novel, owned_shelf


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shelf not found")


def share_targets(db: Session, user: User) -> list[dict]:
    """Other active users of the instance, for the share dialog's picker."""
    users = (
        db.query(User)
        .filter(User.id != user.id, User.is_disabled.is_(False))
        .order_by(func.lower(User.username))
        .all()
    )
    return [{"id": row.id, "username": row.username} for row in users]


def _present_share(share: ShelfShare, username: str) -> dict:
    return {"user_id": share.user_id, "username": username, "permission": share.permission}


def list_shares(db: Session, owner: User, shelf_id: int) -> dict:
    shelf = owned_shelf(db, owner, shelf_id)
    rows = (
        db.query(ShelfShare, User.username)
        .join(User, ShelfShare.user_id == User.id)
        .filter(ShelfShare.shelf_id == shelf.id)
        .order_by(func.lower(User.username))
        .all()
    )
    return {
        "shelf_id": shelf.id,
        "share_notes": bool(shelf.share_notes),
        "shares": [_present_share(share, username) for share, username in rows],
    }


def set_share(db: Session, owner: User, shelf_id: int, user_id: int, permission: str) -> dict:
    shelf = owned_shelf(db, owner, shelf_id)
    if permission not in SHARE_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown permission")
    if user_id == owner.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You already own this shelf")
    target = db.get(User, user_id)
    if target is None or target.is_disabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    share = db.query(ShelfShare).filter(ShelfShare.shelf_id == shelf.id, ShelfShare.user_id == target.id).first()
    if share is None:
        share = ShelfShare(shelf_id=shelf.id, user_id=target.id, permission=permission)
        db.add(share)
    else:
        share.permission = permission
    db.commit()
    return list_shares(db, owner, shelf.id)


def set_share_notes(db: Session, owner: User, shelf_id: int, share_notes: bool) -> None:
    shelf = owned_shelf(db, owner, shelf_id)
    shelf.share_notes = share_notes
    db.commit()


def remove_share(db: Session, actor: User, shelf_id: int, user_id: int) -> None:
    """The owner stops sharing with someone, or a recipient leaves the shelf."""
    shelf = db.get(Shelf, shelf_id)
    if shelf is None or (shelf.user_id != actor.id and user_id != actor.id):
        raise _not_found()
    deleted = (
        db.query(ShelfShare)
        .filter(ShelfShare.shelf_id == shelf.id, ShelfShare.user_id == user_id)
        .delete(synchronize_session=False)
    )
    if not deleted and shelf.user_id != actor.id:
        raise _not_found()
    db.commit()


def access(db: Session, user: User, shelf_id: int) -> tuple[Shelf, str]:
    """The shelf and the user's role on it: owner, view or collaborate. 404 otherwise."""
    shelf = db.get(Shelf, shelf_id)
    if shelf is None:
        raise _not_found()
    if shelf.user_id == user.id:
        return shelf, "owner"
    share = db.query(ShelfShare).filter(ShelfShare.shelf_id == shelf.id, ShelfShare.user_id == user.id).first()
    if share is None:
        raise _not_found()
    return shelf, share.permission


def share_counts(db: Session, shelf_ids: list[int]) -> dict[int, int]:
    if not shelf_ids:
        return {}
    rows = (
        db.query(ShelfShare.shelf_id, func.count(ShelfShare.id))
        .filter(ShelfShare.shelf_id.in_(shelf_ids))
        .group_by(ShelfShare.shelf_id)
        .all()
    )
    return {shelf_id: count for shelf_id, count in rows}


def shared_with_me(db: Session, user: User) -> list[dict]:
    rows = (
        db.query(Shelf, ShelfShare.permission, User.id, User.username)
        .join(ShelfShare, ShelfShare.shelf_id == Shelf.id)
        .join(User, Shelf.user_id == User.id)
        .filter(ShelfShare.user_id == user.id, User.is_disabled.is_(False))
        .order_by(func.lower(User.username), Shelf.position, Shelf.name)
        .all()
    )
    counts = dict(
        db.query(ShelfNovel.shelf_id, func.count(ShelfNovel.id))
        .filter(ShelfNovel.shelf_id.in_([shelf.id for shelf, *_ in rows] or [-1]))
        .group_by(ShelfNovel.shelf_id)
        .all()
    )
    return [
        {
            "id": shelf.id,
            "name": shelf.name,
            "owner": {"id": owner_id, "username": owner_name},
            "permission": permission,
            "share_notes": bool(shelf.share_notes),
            "story_count": counts.get(shelf.id, 0),
        }
        for shelf, permission, owner_id, owner_name in rows
    ]


async def _ratings(user: User, metadata_ids: set[int]) -> dict[int, dict]:
    """Catalog facts used for the viewer's content limits; only fetched for limited profiles."""
    if not content_limit_service.is_limited(user) or not metadata_ids:
        return {}

    async def one(metadata_id: int) -> dict:
        try:
            data = await metadata_client.get_novel_metadata(metadata_id)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    ids = sorted(metadata_ids)
    found = await asyncio.gather(*(one(metadata_id) for metadata_id in ids))
    return dict(zip(ids, found))


async def shelf_stories(db: Session, user: User, shelf_id: int) -> dict:
    """The shelf's stories as catalog references, filtered by the viewer's content limits."""
    shelf, role = access(db, user, shelf_id)
    owner = db.get(User, shelf.user_id)
    rows = (
        db.query(ShelfNovel, Novel)
        .join(Novel, ShelfNovel.novel_id == Novel.id)
        .filter(ShelfNovel.shelf_id == shelf.id)
        .order_by(ShelfNovel.position, ShelfNovel.id)
        .all()
    )
    notes: dict[int, str] = {}
    if shelf.share_notes or role == "owner":
        notes = {
            row.novel_id: row.notes
            for row in db.query(NovelPersonalData).filter(
                NovelPersonalData.user_id == shelf.user_id,
                NovelPersonalData.novel_id.in_([novel.id for _, novel in rows] or [-1]),
            )
            if row.notes
        }
    adders = {
        row.id: row.username
        for row in db.query(User).filter(User.id.in_({entry.added_by_user_id for entry, _ in rows if entry.added_by_user_id} or {-1}))
    }
    mine = {
        metadata_id
        for (metadata_id,) in db.query(Novel.metadata_id)
        .join(Library, Novel.library_id == Library.id)
        .filter(Library.user_id == user.id, Novel.metadata_id.isnot(None))
    }
    catalog = await _ratings(user, {int(novel.metadata_id) for _, novel in rows if novel.metadata_id})
    limited = content_limit_service.is_limited(user)

    stories = []
    seen: set[int] = set()
    for entry, novel in rows:
        if novel.metadata_id and novel.metadata_id in seen:
            continue
        if limited and not content_limit_service.item_allowed(user, catalog.get(int(novel.metadata_id or 0), {})):
            continue
        if novel.metadata_id:
            seen.add(novel.metadata_id)
        by_owner = entry.added_by_user_id is None
        stories.append({
            # Catalog references only: no library or novel ids of someone else's copy.
            "entry_id": entry.id,
            "metadata_id": novel.metadata_id,
            "title": novel.title,
            "author": novel.author,
            "cover_url": novel.img_url,
            "site": novel.novel_site,
            "source_url": novel.source_url or novel.url,
            "added_by": owner.username if by_owner and owner else adders.get(entry.added_by_user_id),
            "added_by_me": (by_owner and shelf.user_id == user.id) or entry.added_by_user_id == user.id,
            "notes": notes.get(novel.id) if by_owner else None,
            "in_my_library": bool(novel.metadata_id and novel.metadata_id in mine),
        })
    return {
        "id": shelf.id,
        "name": shelf.name,
        "owner": {"id": shelf.user_id, "username": owner.username if owner else None},
        "permission": role,
        "share_notes": bool(shelf.share_notes),
        "stories": stories,
    }


def add_own_novel(db: Session, user: User, shelf_id: int, novel_id: int) -> None:
    """A collaborator puts a story from their own library on a shared shelf."""
    shelf, role = access(db, user, shelf_id)
    if role not in ("owner", "collaborate"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This shelf is shared with you view-only")
    novel = owned_novel(db, user, novel_id)
    exists = db.query(ShelfNovel).filter(ShelfNovel.shelf_id == shelf.id, ShelfNovel.novel_id == novel.id).first()
    if exists is None:
        last = db.query(func.max(ShelfNovel.position)).filter(ShelfNovel.shelf_id == shelf.id).scalar()
        db.add(ShelfNovel(
            shelf_id=shelf.id,
            novel_id=novel.id,
            position=(last or 0) + 1,
            added_by_user_id=None if role == "owner" else user.id,
        ))
        db.commit()


def remove_entry(db: Session, user: User, shelf_id: int, entry_id: int) -> None:
    """The owner removes any entry; a collaborator only the entries they added."""
    shelf, role = access(db, user, shelf_id)
    entry = db.query(ShelfNovel).filter(ShelfNovel.id == entry_id, ShelfNovel.shelf_id == shelf.id).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not on this shelf")
    if role != "owner" and not (role == "collaborate" and entry.added_by_user_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the shelf owner can remove this story")
    db.delete(entry)
    db.commit()
