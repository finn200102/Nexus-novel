"""Per-user export and idempotent import of reading data.

Import rules:
* Libraries are matched by name, novels by source URL inside the library.
* Missing novels are created through the same path as the add-novel flow;
  their metadata scrape runs in the background.
* Follow state is set to the exported value.
* Progress keeps the furthest position (chapter, then percent).
* History keeps one row per chapter and day, with the higher percent.
* Annotations are deduplicated by content. They need the chapter to exist
  locally, so they are reported as deferred until a later import finds it.
* Saved searches are created when missing. A name that already exists with
  different content is reported as a conflict and left unchanged.

Running an import twice leaves the second run with nothing to change.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time
from typing import Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.saved_search import SavedSearch
from app.models.follow import UserNovelFollow
from app.models.user import User
from app.routers.novel import (
    get_existing_follow,
    get_or_create_follow,
    get_site_name_from_url,
    supported_src,
)
from app.schemas.user_data import EXPORT_FORMAT, EXPORT_VERSION, UserDataDocument
from app.services import metadata_client
import app.services.novel_services as novel_services

# Called once a new novel row is committed: (novel_id, metadata_id).
ScheduleScrape = Callable[[int, int], None]


def _clamp_percent(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _chapter(db: Session, novel_id: int, chapter_number: int) -> Chapter | None:
    return (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
        .first()
    )


# ---------------------------------------------------------------- export


def export_user_data(db: Session, user: User) -> dict:
    libraries = db.query(Library).filter(Library.user_id == user.id).order_by(Library.name).all()

    progress_by_novel = {
        row.novel_id: row
        for row in db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id).all()
    }
    follow_by_novel = {
        row.novel_id: row
        for row in db.query(UserNovelFollow).filter(UserNovelFollow.user_id == user.id).all()
    }
    history_by_novel: dict[int, list[ReadingHistory]] = defaultdict(list)
    for row in (
        db.query(ReadingHistory)
        .filter(ReadingHistory.user_id == user.id)
        .order_by(ReadingHistory.reading_date, ReadingHistory.chapter_number)
        .all()
    ):
        history_by_novel[row.novel_id].append(row)
    annotations_by_novel: dict[int, list[ReadingAnnotation]] = defaultdict(list)
    for row in db.query(ReadingAnnotation).filter(ReadingAnnotation.user_id == user.id).all():
        annotations_by_novel[row.novel_id].append(row)

    library_documents = []
    for library in libraries:
        novels = []
        for novel in sorted(library.novels, key=lambda item: item.url or ""):
            # Novels without a source URL cannot be re-linked on import.
            if not novel.url:
                continue
            follow = follow_by_novel.get(novel.id)
            progress = progress_by_novel.get(novel.id)
            followed_at = follow.followed_at if follow else novel.followed_at
            novels.append({
                "url": novel.url,
                "title": novel.title,
                "site": novel.novel_site,
                "metadata_id": novel.metadata_id,
                "follow_state": follow.state if follow else novel.follow_state,
                "followed_at": followed_at.isoformat() if followed_at else None,
                "progress": {
                    "chapter_number": progress.chapter_number,
                    "position": progress.position,
                    "percent": progress.percent,
                } if progress and progress.chapter_number is not None else None,
                "history": [
                    {
                        "chapter_number": row.chapter_number,
                        "date": row.reading_date.date().isoformat(),
                        "max_percent": row.max_percent,
                    }
                    for row in history_by_novel.get(novel.id, [])
                ],
                "annotations": sorted(
                    [
                        {
                            "chapter_number": row.chapter.chapter_number,
                            "annotation_type": row.annotation_type,
                            "position": row.position,
                            "percent": row.percent,
                            "quote": row.quote,
                            "note": row.note,
                        }
                        for row in annotations_by_novel.get(novel.id, [])
                        if row.chapter is not None
                    ],
                    key=lambda item: (item["chapter_number"], item["position"], item["annotation_type"], item["quote"] or "", item["note"] or ""),
                ),
            })
        library_documents.append({"name": library.name, "novels": novels})

    saved_searches = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.id)
        .order_by(SavedSearch.name)
        .all()
    )
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "libraries": library_documents,
        "saved_searches": [
            {"name": item.name, "filters": item.filters or {}, "notify_on_match": bool(item.notify_on_match)}
            for item in saved_searches
        ],
    }


# ---------------------------------------------------------------- import


def _apply_follow(db: Session, user: User, novel: Novel, item) -> str | None:
    if not item.follow_state:
        return None
    existed = get_existing_follow(db, user.id, novel) is not None
    follow = get_or_create_follow(db, user.id, novel)
    status_value = "unchanged" if existed and follow.state == item.follow_state else "updated"
    follow.state = item.follow_state
    if follow.followed_at is None and item.followed_at:
        follow.followed_at = _naive_utc(item.followed_at)
    novel.follow_state = follow.state
    novel.followed_at = follow.followed_at
    return status_value


def _apply_progress(db: Session, user: User, novel: Novel, item) -> str | None:
    if item is None:
        return None
    chapter = _chapter(db, novel.id, item.chapter_number)
    row = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.user_id == user.id, ReadingProgress.novel_id == novel.id)
        .first()
    )
    incoming = (item.chapter_number, _clamp_percent(item.percent))
    if row is None:
        row = ReadingProgress(
            user_id=user.id,
            novel_id=novel.id,
            chapter_id=chapter.id if chapter else None,
            chapter_number=item.chapter_number,
            position=max(item.position, 0),
            percent=incoming[1],
        )
        db.add(row)
        return "applied"

    result = "unchanged"
    if incoming > (row.chapter_number or 0, row.percent or 0.0):
        row.chapter_number = item.chapter_number
        row.chapter_id = chapter.id if chapter else None
        row.position = max(item.position, 0)
        row.percent = incoming[1]
        result = "applied"
    elif row.chapter_id is None and chapter is not None:
        # Progress recorded before the chapter was scraped: link it now.
        row.chapter_id = chapter.id
    return result


def _apply_history(db: Session, user: User, novel: Novel, points) -> dict:
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    existing = {
        (row.chapter_number, row.reading_date.date()): row
        for row in db.query(ReadingHistory)
        .filter(ReadingHistory.user_id == user.id, ReadingHistory.novel_id == novel.id)
        .all()
    }
    for point in points:
        day = date.fromisoformat(point.day)
        percent = min(max(int(point.max_percent), 0), 100)
        key = (point.chapter_number, day)
        row = existing.get(key)
        if row is None:
            row = ReadingHistory(
                user_id=user.id,
                novel_id=novel.id,
                chapter_number=point.chapter_number,
                reading_date=datetime.combine(day, time.min),
                max_percent=percent,
            )
            db.add(row)
            existing[key] = row
            counts["added"] += 1
        elif percent > (row.max_percent or 0):
            row.max_percent = percent
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    return counts


def _annotation_key(chapter_id: int, annotation_type: str, position: int, quote: str | None, note: str | None) -> tuple:
    return (chapter_id, annotation_type, position, quote or "", note or "")


def _apply_annotations(db: Session, user: User, novel: Novel, items) -> dict:
    counts = {"added": 0, "duplicate": 0, "deferred": 0}
    existing = {
        _annotation_key(row.chapter_id, row.annotation_type, row.position, row.quote, row.note)
        for row in db.query(ReadingAnnotation)
        .filter(ReadingAnnotation.user_id == user.id, ReadingAnnotation.novel_id == novel.id)
        .all()
    }
    for item in items:
        chapter = _chapter(db, novel.id, item.chapter_number)
        if chapter is None:
            counts["deferred"] += 1
            continue
        position = max(item.position, 0)
        key = _annotation_key(chapter.id, item.annotation_type, position, item.quote, item.note)
        if key in existing:
            counts["duplicate"] += 1
            continue
        db.add(ReadingAnnotation(
            user_id=user.id,
            novel_id=novel.id,
            chapter_id=chapter.id,
            annotation_type=item.annotation_type,
            position=position,
            percent=_clamp_percent(item.percent),
            quote=item.quote,
            note=item.note,
        ))
        existing.add(key)
        counts["added"] += 1
    return counts


async def _create_novel(db: Session, library: Library, item, schedule_scrape: ScheduleScrape) -> tuple[Novel | None, str | None]:
    if not supported_src(item.url):
        return None, "Not a supported source url"
    site_name = get_site_name_from_url(item.url)
    if not site_name:
        return None, "Could not determine site from URL"

    result = await metadata_client.scrape_novel_by_url(item.url, site_name)
    metadata_id = result.get("novel_id") if result else None
    if not result or not result.get("success") or not metadata_id:
        message = result.get("message", "Failed to start scraping") if result else "Failed to start scraping"
        return None, f"Failed to add novel: {message}"

    title = item.title or item.url.rstrip("/").split("/")[-1].replace("-", " ").title()
    novel = novel_services.create_novel(db, {
        "title": title,
        "url": item.url,
        "library_id": library.id,
        "metadata_id": metadata_id,
        "novel_site": site_name,
        "scrape_status": "pending",
    })
    schedule_scrape(int(novel.id), int(metadata_id))
    return novel, None


async def _import_novel(db: Session, user: User, library: Library, item, schedule_scrape: ScheduleScrape) -> dict:
    report: dict = {"url": item.url, "title": item.title, "status": None, "reason": None}
    novel = db.query(Novel).filter(Novel.library_id == library.id, Novel.url == item.url).first()
    if novel is None:
        novel, failure = await _create_novel(db, library, item, schedule_scrape)
        if novel is None:
            report["status"] = "failed"
            report["reason"] = failure
            return report
        report["status"] = "created"
    else:
        report["status"] = "linked"

    report["follow_state"] = _apply_follow(db, user, novel, item)
    report["progress"] = _apply_progress(db, user, novel, item.progress)
    report["history"] = _apply_history(db, user, novel, item.history)
    report["annotations"] = _apply_annotations(db, user, novel, item.annotations)
    return report


def _summarize(libraries: list[dict], saved_searches: list[dict]) -> dict:
    novels = [novel for library in libraries for novel in library["novels"]]

    def total(key: str, value: str) -> int:
        return sum(1 for novel in novels if novel.get(key) == value)

    def sum_of(key: str, sub: str) -> int:
        return sum((novel.get(key) or {}).get(sub, 0) for novel in novels)

    return {
        "libraries_created": sum(1 for library in libraries if library["status"] == "created"),
        "novels_created": total("status", "created"),
        "novels_linked": total("status", "linked"),
        "novels_failed": total("status", "failed"),
        "follow_states_updated": total("follow_state", "updated"),
        "progress_applied": total("progress", "applied"),
        "history_added": sum_of("history", "added"),
        "history_updated": sum_of("history", "updated"),
        "annotations_added": sum_of("annotations", "added"),
        "annotations_duplicate": sum_of("annotations", "duplicate"),
        "annotations_deferred": sum_of("annotations", "deferred"),
        "saved_searches_created": sum(1 for item in saved_searches if item["status"] == "created"),
        "saved_searches_conflicts": sum(1 for item in saved_searches if item["status"] == "conflict"),
    }


async def import_user_data(
    db: Session,
    user: User,
    document: UserDataDocument,
    schedule_scrape: ScheduleScrape,
) -> dict:
    if document.version != EXPORT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported export version {document.version}; this Nexus reads version {EXPORT_VERSION}",
        )

    library_reports = []
    for entry in document.libraries:
        library = (
            db.query(Library)
            .filter(Library.user_id == user.id, Library.name == entry.name)
            .first()
        )
        library_status = "existing"
        if library is None:
            library = Library(name=entry.name, user_id=user.id)
            db.add(library)
            db.flush()
            library_status = "created"
        novel_reports = []
        for item in entry.novels:
            novel_reports.append(await _import_novel(db, user, library, item, schedule_scrape))
        library_reports.append({"name": entry.name, "status": library_status, "novels": novel_reports})

    saved_reports = []
    existing_searches = {
        row.name: row
        for row in db.query(SavedSearch).filter(SavedSearch.user_id == user.id).all()
    }
    for item in document.saved_searches:
        row = existing_searches.get(item.name)
        if row is None:
            row = SavedSearch(
                user_id=user.id,
                name=item.name,
                filters=item.filters,
                notify_on_match=item.notify_on_match,
            )
            db.add(row)
            existing_searches[item.name] = row
            saved_status = "created"
        elif (row.filters or {}) == item.filters and bool(row.notify_on_match) == item.notify_on_match:
            saved_status = "unchanged"
        else:
            saved_status = "conflict"
        saved_reports.append({"name": item.name, "status": saved_status})

    db.commit()
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "summary": _summarize(library_reports, saved_reports),
        "libraries": library_reports,
        "saved_searches": saved_reports,
    }
