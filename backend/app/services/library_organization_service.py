"""Shelves, personal notes/ratings/tags, and library sort orders.

Every function takes the acting user and only touches rows that user owns.
Novels are checked through their library, so another user's novel id is
reported as not found.
"""

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.models.reading_progress import ReadingProgress
from app.models.shelf import Shelf, ShelfNovel
from app.models.user import User

SHELF_NAME_MAX = 120
USER_TAG_MAX = 60
USER_TAG_LIMIT = 30
SORT_OPTIONS = ("default", "updated_since_read", "personal_rating")
DEFAULT_FOLLOWED_CATEGORIES = ("story",)


def owned_novel(db: Session, user: User, novel_id: int) -> Novel:
    novel = (
        db.query(Novel)
        .join(Library, Novel.library_id == Library.id)
        .filter(Novel.id == novel_id, Library.user_id == user.id)
        .first()
    )
    if novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
    return novel


def library_novel_ids(db: Session, user: User, library_id: int) -> list[int]:
    library = db.query(Library).filter(Library.id == library_id, Library.user_id == user.id).first()
    if library is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library not found")
    return [row.id for row in db.query(Novel.id).filter(Novel.library_id == library.id).all()]


def owned_shelf(db: Session, user: User, shelf_id: int) -> Shelf:
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id, Shelf.user_id == user.id).first()
    if shelf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shelf not found")
    return shelf


def clean_shelf_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Shelf name is required")
    return cleaned[:SHELF_NAME_MAX]


def clean_user_tag(tag: str) -> str:
    return " ".join((tag or "").split()).casefold()[:USER_TAG_MAX]


# ---------------------------------------------------------------- shelves


def shelf_novel_ids(db: Session, shelf: Shelf) -> list[int]:
    rows = (
        db.query(ShelfNovel)
        .filter(ShelfNovel.shelf_id == shelf.id)
        .order_by(ShelfNovel.position, ShelfNovel.id)
        .all()
    )
    return [row.novel_id for row in rows]


def present_shelf(db: Session, shelf: Shelf) -> dict:
    return {
        "id": shelf.id,
        "name": shelf.name,
        "position": shelf.position,
        "novel_ids": shelf_novel_ids(db, shelf),
    }


def list_shelves(db: Session, user: User) -> list[dict]:
    shelves = db.query(Shelf).filter(Shelf.user_id == user.id).order_by(Shelf.position, Shelf.name).all()
    return [present_shelf(db, shelf) for shelf in shelves]


def _name_taken(db: Session, user: User, name: str, *, except_id: int | None = None) -> bool:
    """Shelf names are unique per user, ignoring case."""
    wanted = name.casefold()
    return any(
        shelf.name.casefold() == wanted and shelf.id != except_id
        for shelf in db.query(Shelf).filter(Shelf.user_id == user.id).all()
    )


def create_shelf(db: Session, user: User, name: str) -> Shelf:
    cleaned = clean_shelf_name(name)
    if _name_taken(db, user, cleaned):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shelf with this name already exists")
    last = db.query(func.max(Shelf.position)).filter(Shelf.user_id == user.id).scalar()
    shelf = Shelf(user_id=user.id, name=cleaned, position=(last or 0) + 1)
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return shelf


def update_shelf(db: Session, user: User, shelf_id: int, *, name: str | None, position: int | None) -> Shelf:
    shelf = owned_shelf(db, user, shelf_id)
    if name is not None:
        cleaned = clean_shelf_name(name)
        if _name_taken(db, user, cleaned, except_id=shelf.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shelf with this name already exists")
        shelf.name = cleaned
    if position is not None:
        shelf.position = position
    db.commit()
    db.refresh(shelf)
    return shelf


def delete_shelf(db: Session, user: User, shelf_id: int) -> None:
    shelf = owned_shelf(db, user, shelf_id)
    db.delete(shelf)
    db.commit()


def add_novel_to_shelf(db: Session, user: User, shelf_id: int, novel_id: int) -> Shelf:
    shelf = owned_shelf(db, user, shelf_id)
    novel = owned_novel(db, user, novel_id)
    existing = db.query(ShelfNovel).filter(ShelfNovel.shelf_id == shelf.id, ShelfNovel.novel_id == novel.id).first()
    if existing is None:
        last = db.query(func.max(ShelfNovel.position)).filter(ShelfNovel.shelf_id == shelf.id).scalar()
        db.add(ShelfNovel(shelf_id=shelf.id, novel_id=novel.id, position=(last or 0) + 1))
        db.commit()
    return shelf


def remove_novel_from_shelf(db: Session, user: User, shelf_id: int, novel_id: int) -> Shelf:
    shelf = owned_shelf(db, user, shelf_id)
    db.query(ShelfNovel).filter(ShelfNovel.shelf_id == shelf.id, ShelfNovel.novel_id == novel_id).delete(synchronize_session=False)
    db.commit()
    return shelf


def shelf_ids_by_novel(db: Session, user: User, novel_ids: list[int] | None = None) -> dict[int, list[int]]:
    query = (
        db.query(ShelfNovel.novel_id, ShelfNovel.shelf_id)
        .join(Shelf, ShelfNovel.shelf_id == Shelf.id)
        .filter(Shelf.user_id == user.id)
    )
    if novel_ids is not None:
        query = query.filter(ShelfNovel.novel_id.in_(novel_ids))
    grouped: dict[int, list[int]] = {}
    for novel_id, shelf_id in query.order_by(Shelf.position, Shelf.id).all():
        grouped.setdefault(novel_id, []).append(shelf_id)
    return grouped


def novel_ids_on_shelf(db: Session, user: User, shelf_id: int) -> set[int]:
    owned_shelf(db, user, shelf_id)
    return {row.novel_id for row in db.query(ShelfNovel.novel_id).filter(ShelfNovel.shelf_id == shelf_id).all()}


# ---------------------------------------------------------------- personal data


def get_personal(db: Session, user: User, novel_id: int) -> dict:
    row = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user.id, NovelPersonalData.novel_id == novel_id).first()
    tags = [t.tag for t in db.query(NovelUserTag).filter(NovelUserTag.user_id == user.id, NovelUserTag.novel_id == novel_id).order_by(NovelUserTag.tag).all()]
    return {
        "novel_id": novel_id,
        "notes": row.notes if row else None,
        "rating": row.rating if row else None,
        "user_tags": tags,
        "followed_categories": followed_categories_of(row),
    }


def followed_categories_of(row: NovelPersonalData | None) -> list[str]:
    """The categories a user follows for a novel; story chapters unless set otherwise."""
    return list(row.followed_categories) if row and row.followed_categories else list(DEFAULT_FOLLOWED_CATEGORIES)


def clean_followed_categories(categories: list[str]) -> list[str]:
    cleaned: list[str] = []
    for category in categories:
        value = (category or "").strip().lower()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned or any(len(value) > 32 for value in cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Follow at least one category (max 32 characters each)",
        )
    return cleaned


def set_personal(
    db: Session,
    user: User,
    novel_id: int,
    *,
    notes: str | None,
    rating: int | None,
    user_tags: list[str],
    followed_categories: list[str] | None = None,
) -> dict:
    """``followed_categories=None`` leaves the stored categories untouched."""
    owned_novel(db, user, novel_id)
    if rating is not None and not 1 <= rating <= 5:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rating must be between 1 and 5")
    categories = clean_followed_categories(followed_categories) if followed_categories is not None else None
    cleaned_tags: list[str] = []
    for tag in user_tags:
        value = clean_user_tag(tag)
        if value and value not in cleaned_tags:
            cleaned_tags.append(value)
    if len(cleaned_tags) > USER_TAG_LIMIT:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"At most {USER_TAG_LIMIT} tags per novel")

    row = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user.id, NovelPersonalData.novel_id == novel_id).first()
    text = (notes or "").strip() or None
    if row is None:
        row = NovelPersonalData(user_id=user.id, novel_id=novel_id)
        db.add(row)
    row.notes = text
    row.rating = rating
    if categories is not None:
        row.followed_categories = categories
    db.query(NovelUserTag).filter(NovelUserTag.user_id == user.id, NovelUserTag.novel_id == novel_id).delete(synchronize_session=False)
    for tag in cleaned_tags:
        db.add(NovelUserTag(user_id=user.id, novel_id=novel_id, tag=tag))
    db.commit()
    return get_personal(db, user, novel_id)


def user_tag_vocabulary(db: Session, user: User, prefix: str = "", limit: int = 50) -> list[str]:
    """Distinct tags across the user's library, for autocomplete."""
    rows = (
        db.query(NovelUserTag.tag, func.count(NovelUserTag.id))
        .filter(NovelUserTag.user_id == user.id)
        .group_by(NovelUserTag.tag)
        .order_by(func.count(NovelUserTag.id).desc(), NovelUserTag.tag)
        .all()
    )
    wanted = clean_user_tag(prefix)
    return [tag for tag, _ in rows if not wanted or tag.startswith(wanted) or wanted in tag][:limit]


def personal_for_novels(db: Session, user: User, novel_ids: list[int]) -> dict[int, dict]:
    if not novel_ids:
        return {}
    result = {nid: {"novel_id": nid, "notes": None, "rating": None, "user_tags": [], "has_notes": False} for nid in novel_ids}
    for row in db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user.id, NovelPersonalData.novel_id.in_(novel_ids)).all():
        result[row.novel_id]["rating"] = row.rating
        result[row.novel_id]["has_notes"] = bool(row.notes)
    for row in db.query(NovelUserTag).filter(NovelUserTag.user_id == user.id, NovelUserTag.novel_id.in_(novel_ids)).order_by(NovelUserTag.tag).all():
        result[row.novel_id]["user_tags"].append(row.tag)
    return result


def novel_ids_with_user_tag(db: Session, user: User, tag: str) -> set[int]:
    wanted = clean_user_tag(tag)
    return {row.novel_id for row in db.query(NovelUserTag.novel_id).filter(NovelUserTag.user_id == user.id, NovelUserTag.tag == wanted).all()}


def novel_ids_with_min_rating(db: Session, user: User, minimum: int) -> set[int]:
    return {
        row.novel_id
        for row in db.query(NovelPersonalData.novel_id)
        .filter(NovelPersonalData.user_id == user.id, NovelPersonalData.rating >= minimum)
        .all()
    }


# ---------------------------------------------------------------- sorting


def sort_novels(db: Session, user: User, novels: list[Novel], sort_by: str) -> list[Novel]:
    """Order library novels for the sort options that depend on user data.

    ``updated_since_read``: novels with chapters past the user's last-read
    chapter come first; within each group, the most recently updated story leads.
    Novels the user has never opened sort as "no new chapters".
    ``personal_rating``: highest personal rating first, unrated last.
    """
    if sort_by == "personal_rating":
        ratings = personal_for_novels(db, user, [novel.id for novel in novels])
        return sorted(
            novels,
            key=lambda novel: (
                ratings[novel.id]["rating"] is None,
                -(ratings[novel.id]["rating"] or 0),
                (novel.title or "").casefold(),
            ),
        )
    if sort_by == "updated_since_read":
        ids = [novel.id for novel in novels]
        progress = {
            row.novel_id: row.chapter_number
            for row in db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id, ReadingProgress.novel_id.in_(ids)).all()
        }
        latest_chapter = dict(
            db.query(Chapter.novel_id, func.max(Chapter.chapter_number))
            .filter(Chapter.novel_id.in_(ids))
            .group_by(Chapter.novel_id)
            .all()
        ) if ids else {}

        def key(novel: Novel) -> tuple:
            last_read = progress.get(novel.id)
            newest = max(latest_chapter.get(novel.id) or 0, novel.num_chapters or 0, novel.chapter_count or 0)
            has_new = last_read is not None and newest > last_read
            updated: datetime = novel.updated_date or novel.publish_date or datetime.min
            return (has_new, updated, (novel.title or "").casefold())

        ordered = sorted(novels, key=key, reverse=True)
        return ordered
    return novels
