"""Per-user export and idempotent import of reading data.

Import rules:
* Libraries are matched by name, novels by source URL inside the library.
* Missing novels are created in the library right away (so progress and
  notes attach to them) and queued on a durable import job; the worker
  starts their metadata scrapes one at a time (``import_job_ids``).
* Follow state is set to the exported value.
* Progress keeps the furthest position (chapter, then percent).
* History keeps one row per chapter and day, with the higher percent.
* Annotations are deduplicated by content. They need the chapter to exist
  locally, so they are reported as deferred until a later import finds it.
* Saved searches are created when missing. A name that already exists with
  different content is reported as a conflict and left unchanged.
* Personal data (notes, rating, user tags): a value is applied only where the
  local copy has none. Tags are merged. A different local value is kept and
  reported as ``kept_local``.
* Shelves are matched by name and their members by (library, source URL).
  A member whose novel is not in the instance is reported as missing.
* Blocklist entries are added when missing.

Running an import twice leaves the second run with nothing to change.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.blocklist import BlocklistEntry
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.models.saved_search import SavedSearch
from app.models.shelf import Shelf, ShelfNovel
from app.models.follow import UserNovelFollow
from app.models.user import User
from app.routers.novel import (
    get_existing_follow,
    get_or_create_follow,
    get_site_name_from_url,
    supported_src,
)
from app.schemas.user_data import EXPORT_FORMAT, EXPORT_VERSION, UserDataDocument
from app.services import import_job_service
from app.services.blocklist_service import normalize_value
import app.services.library_organization_service as organization


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
    personal_by_novel = {
        row.novel_id: row
        for row in db.query(NovelPersonalData).filter(NovelPersonalData.user_id == user.id).all()
    }
    tags_by_novel: dict[int, list[str]] = defaultdict(list)
    for row in db.query(NovelUserTag).filter(NovelUserTag.user_id == user.id).order_by(NovelUserTag.tag).all():
        tags_by_novel[row.novel_id].append(row.tag)
    novel_url_by_id = {
        novel.id: (library.name, novel.url)
        for library in libraries
        for novel in library.novels
        if novel.url
    }
    entry_by_novel_id: dict[int, dict] = {}
    for library_document, library in zip(library_documents, libraries):
        for novel in library.novels:
            if not novel.url:
                continue
            for entry in library_document["novels"]:
                if entry["url"] == novel.url:
                    entry_by_novel_id[novel.id] = entry
                    break
    for novel_id, entry in entry_by_novel_id.items():
        personal = personal_by_novel.get(novel_id)
        tags = tags_by_novel.get(novel_id, [])
        has_notes_or_rating = personal is not None and (bool(personal.notes) or personal.rating is not None)
        if has_notes_or_rating or tags:
            entry["personal"] = {
                "notes": personal.notes if personal else None,
                "rating": personal.rating if personal else None,
                "user_tags": tags,
            }

    shelves = db.query(Shelf).filter(Shelf.user_id == user.id).order_by(Shelf.position, Shelf.name).all()
    shelf_documents = []
    for shelf in shelves:
        members = (
            db.query(ShelfNovel)
            .filter(ShelfNovel.shelf_id == shelf.id)
            .order_by(ShelfNovel.position, ShelfNovel.id)
            .all()
        )
        shelf_documents.append({
            "name": shelf.name,
            "position": shelf.position,
            "novels": [
                {"library": novel_url_by_id[row.novel_id][0], "url": novel_url_by_id[row.novel_id][1]}
                for row in members
                if row.novel_id in novel_url_by_id
            ],
        })
    blocklist = db.query(BlocklistEntry).filter(BlocklistEntry.user_id == user.id).order_by(BlocklistEntry.kind, BlocklistEntry.value).all()
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "libraries": library_documents,
        "saved_searches": [
            {"name": item.name, "filters": item.filters or {}, "notify_on_match": bool(item.notify_on_match)}
            for item in saved_searches
        ],
        "shelves": shelf_documents,
        "blocklist": [{"kind": row.kind, "value": row.value} for row in blocklist],
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


def _apply_personal(db: Session, user: User, novel: Novel, item) -> str:
    row = (
        db.query(NovelPersonalData)
        .filter(NovelPersonalData.user_id == user.id, NovelPersonalData.novel_id == novel.id)
        .first()
    )
    if row is None:
        row = NovelPersonalData(user_id=user.id, novel_id=novel.id)
        db.add(row)
    changed = False
    conflict = False
    if item.notes:
        if not row.notes:
            row.notes = item.notes
            changed = True
        elif row.notes != item.notes:
            conflict = True
    if item.rating is not None:
        if row.rating is None:
            row.rating = item.rating
            changed = True
        elif row.rating != item.rating:
            conflict = True

    existing_tags = {
        tag.tag
        for tag in db.query(NovelUserTag).filter(NovelUserTag.user_id == user.id, NovelUserTag.novel_id == novel.id).all()
    }
    for raw in item.user_tags:
        tag = organization.clean_user_tag(raw)
        if tag and tag not in existing_tags:
            db.add(NovelUserTag(user_id=user.id, novel_id=novel.id, tag=tag))
            existing_tags.add(tag)
            changed = True
    if changed:
        return "applied"
    return "kept_local" if conflict else "unchanged"


def _import_shelves(db: Session, user: User, entries, novel_index: dict[tuple[str, str], Novel]) -> list[dict]:
    reports = []
    shelves = {row.name: row for row in db.query(Shelf).filter(Shelf.user_id == user.id).all()}
    for entry in entries:
        name = organization.clean_shelf_name(entry.name)
        shelf = shelves.get(name)
        shelf_status = "existing"
        if shelf is None:
            shelf = Shelf(user_id=user.id, name=name, position=entry.position)
            db.add(shelf)
            db.flush()
            shelves[name] = shelf
            shelf_status = "created"
        links_added = links_existing = missing = 0
        for member in entry.novels:
            novel = novel_index.get((member.library, member.url))
            if novel is None:
                missing += 1
                continue
            exists = (
                db.query(ShelfNovel)
                .filter(ShelfNovel.shelf_id == shelf.id, ShelfNovel.novel_id == novel.id)
                .first()
            )
            if exists:
                links_existing += 1
                continue
            db.add(ShelfNovel(shelf_id=shelf.id, novel_id=novel.id, position=links_added + links_existing))
            links_added += 1
        reports.append({
            "name": name,
            "status": shelf_status,
            "links_added": links_added,
            "links_existing": links_existing,
            "links_missing": missing,
        })
    return reports


def _import_blocklist(db: Session, user: User, entries) -> list[dict]:
    reports = []
    existing = {
        (row.kind, row.value)
        for row in db.query(BlocklistEntry).filter(BlocklistEntry.user_id == user.id).all()
    }
    for entry in entries:
        value = normalize_value(entry.value)
        if not value:
            continue
        if (entry.kind, value) in existing:
            status_value = "unchanged"
        else:
            db.add(BlocklistEntry(user_id=user.id, kind=entry.kind, value=value))
            existing.add((entry.kind, value))
            status_value = "created"
        reports.append({"kind": entry.kind, "value": value, "status": status_value})
    return reports


def _create_novel(db: Session, library: Library, item) -> tuple[Novel | None, str | None]:
    if not supported_src(item.url):
        return None, "Not a supported source url"
    site_name = get_site_name_from_url(item.url)
    if not site_name:
        return None, "Could not determine site from URL"
    title = item.title or item.url.rstrip("/").split("/")[-1].replace("-", " ").title()
    novel = Novel(title=title, url=item.url, library_id=library.id, novel_site=site_name, scrape_status="pending")
    db.add(novel)
    db.flush()
    return novel, None


def _import_novel(db: Session, user: User, library: Library, item, queued: list[Novel]) -> dict:
    report: dict = {"url": item.url, "title": item.title, "status": None, "reason": None}
    novel = db.query(Novel).filter(Novel.library_id == library.id, Novel.url == item.url).first()
    if novel is None:
        novel, failure = _create_novel(db, library, item)
        if novel is None:
            report["status"] = "failed"
            report["reason"] = failure
            return report
        report["status"] = "created"
        queued.append(novel)
    else:
        report["status"] = "linked"

    report["follow_state"] = _apply_follow(db, user, novel, item)
    report["progress"] = _apply_progress(db, user, novel, item.progress)
    report["history"] = _apply_history(db, user, novel, item.history)
    report["annotations"] = _apply_annotations(db, user, novel, item.annotations)
    report["personal"] = _apply_personal(db, user, novel, item.personal) if item.personal else None
    return report


def _summarize(libraries: list[dict], saved_searches: list[dict], shelves: list[dict], blocklist: list[dict]) -> dict:
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
        "personal_applied": total("personal", "applied"),
        "personal_kept_local": total("personal", "kept_local"),
        "shelves_created": sum(1 for item in shelves if item["status"] == "created"),
        "shelf_links_added": sum(item["links_added"] for item in shelves),
        "shelf_links_missing": sum(item["links_missing"] for item in shelves),
        "blocklist_created": sum(1 for item in blocklist if item["status"] == "created"),
    }


def import_user_data(db: Session, user: User, document: UserDataDocument) -> dict:
    if document.version != EXPORT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported export version {document.version}; this Nexus reads version {EXPORT_VERSION}",
        )

    library_reports = []
    import_jobs = []
    novel_index: dict[tuple[str, str], Novel] = {}
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
        queued: list[Novel] = []
        for item in entry.novels:
            report = _import_novel(db, user, library, item, queued)
            novel_reports.append(report)
            db.flush()
            novel = db.query(Novel).filter(Novel.library_id == library.id, Novel.url == item.url).first()
            if novel is not None:
                novel_index[(entry.name, item.url)] = novel
        library_reports.append({"name": entry.name, "status": library_status, "novels": novel_reports})
        if queued:
            import_jobs.append(import_job_service.create_job(
                db, user, library, "user_data",
                entries=[{"url": novel.url, "title": novel.title, "novel_id": novel.id} for novel in queued],
                commit=False,
            ))

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

    shelf_reports = _import_shelves(db, user, document.shelves, novel_index)
    blocklist_reports = _import_blocklist(db, user, document.blocklist)

    db.commit()
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "summary": _summarize(library_reports, saved_reports, shelf_reports, blocklist_reports),
        "libraries": library_reports,
        "saved_searches": saved_reports,
        "shelves": shelf_reports,
        "blocklist": blocklist_reports,
        "import_job_ids": [job.id for job in import_jobs],
    }
