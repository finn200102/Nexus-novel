"""Per-user export and idempotent import of reading data.

Import rules:
* Libraries are matched by name, novels by source URL inside the library.
* Missing novels are created in the library right away (so progress and
  notes attach to them) and queued on a durable import job; the worker
  starts their metadata scrapes one at a time (``import_job_ids``).
* Follow state is set to the exported value.
* Imported reading references are staged privately until their immutable chapter
  bindings are proven on this installation or individually reviewed. Numeric
  labels never select a destination chapter. Existing live places are retained.
* Reviewed history is inferred and never becomes a content-read receipt.
* Optional reading runs/events preserve historical facts with destination-
  scoped identities; importing the same file does not duplicate the journal.
* Unbound annotations, original quotes and versions remain in durable review
  payloads and portable exports until an explicit owned chapter is selected.
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
from datetime import UTC, datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.library import Library
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.reading_run import ReadingRun
from app.services import portable_reading_service
from app.services import import_reading_review_service as imported_reading
from app.services import smart_shelf_portable_service
from app.services import portable_story_service
from app.services.reading_run_service import restore_progress
from app.models.reader_preference import ReaderPreference
from app.models.blocklist import BlocklistEntry
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.models.saved_search import SavedSearch
from app.services.saved_search_service import imported as imported_search_filters
from app.models.shelf import Shelf, ShelfNovel
from app.models.follow import UserNovelFollow
from app.models.user import User
from app.routers.novel import (
    get_existing_follow,
    get_or_create_follow,
    get_site_name_from_url,
    accepted_src,
)
from app.schemas.user_data import EXPORT_FORMAT, EXPORT_VERSION, UserDataDocument
from app.services import import_job_service
from app.services.novel_title import clean_title
from app.services.blocklist_service import normalize_value
import app.services.library_organization_service as organization


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


# ---------------------------------------------------------------- export
LOCATOR_FIELDS = ("block_id", "text_offset", "text_quote", "quote_prefix", "quote_suffix", "locator_content_version", "locator_variant")


def export_user_data(db: Session, user: User) -> dict:
    libraries = db.query(Library).filter(Library.user_id == user.id).order_by(Library.name).all()

    progress_by_novel = {
        row.novel_id: row
        for row in db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id).all()
    }
    # A deleted chapter may have cascaded its old progress row; portable
    # exports use the same durable canonical snapshot as the progress endpoint.
    for run in db.query(ReadingRun).filter_by(user_id=user.id).filter(ReadingRun.archived_at.is_(None)).order_by(ReadingRun.ordinal):
        if run.novel_id not in progress_by_novel:
            restored=restore_progress(run)
            if restored is not None:progress_by_novel[run.novel_id]=restored
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
    entry_by_novel_id: dict[int, dict] = {}
    for library in libraries:
        novels = []
        for novel in sorted(library.novels, key=lambda item: item.url or ""):
            follow = follow_by_novel.get(novel.id)
            progress = progress_by_novel.get(novel.id)
            followed_at = follow.followed_at if follow else novel.followed_at
            novels.append({
                "url": novel.url,
                "portable_story": portable_story_service.export_identity(db,user,novel),
                "title": novel.title,
                "site": novel.novel_site,
                "metadata_id": novel.metadata_id,
                "follow_state": follow.state if follow else novel.follow_state,
                "followed_at": followed_at.isoformat() if followed_at else None,
                "progress": {
                    "chapter_number": progress.chapter_number,
                    "position": progress.position,
                    "percent": progress.percent,
                    "furthest_chapter_number": progress.furthest_chapter_number,
                    "furthest_percent": progress.furthest_percent,
                    **{field: getattr(progress, field) for field in LOCATOR_FIELDS},
                    **({"reading_run_key":progress.reading_run_key} if progress.reading_run_key else {}),
                } if progress and progress.chapter_number is not None else None,
                "history": [
                    {
                        "chapter_number": row.chapter_number,
                        "date": row.reading_date.date().isoformat(),
                        "max_percent": row.max_percent,
                        **({"reading_run_key":row.reading_run_key} if row.reading_run_key else {}),
                    }
                    for row in history_by_novel.get(novel.id, [])
                ],
                "annotations": sorted(
                    [
                        {
                            "chapter_number": row.chapter_number,
                            "chapter_ref": row.chapter_key,
                            "annotation_type": row.annotation_type,
                            "position": row.position,
                            "percent": row.percent,
                            "quote": row.quote,
                            "note": row.note,
                            **{field: getattr(row, field) for field in LOCATOR_FIELDS},
                        }
                        for row in annotations_by_novel.get(novel.id, [])
                    ],
                    key=lambda item: (item["chapter_number"] if item["chapter_number"] is not None else -(2**31), item["position"], item["annotation_type"], item["quote"] or "", item["note"] or ""),
                ),
            })
        for novel,entry in zip(sorted(library.novels,key=lambda item:item.url or ""),novels):entry_by_novel_id[novel.id]=entry
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
        novel.id: {'library':library.name,'url':novel.url,**({'portable_story':portable_story_service.export_identity(db,user,novel)} if novel.url is None else {})}
        for library in libraries for novel in library.novels
    }
    for novel_id, entry in entry_by_novel_id.items():
        runs=portable_reading_service.export_runs(db,user.id,novel_id)
        if runs:entry["reading_runs"]=runs
        personal = personal_by_novel.get(novel_id)
        tags = tags_by_novel.get(novel_id, [])
        has_notes_or_rating = personal is not None and (bool(personal.notes) or personal.rating is not None)
        if has_notes_or_rating or tags:
            entry["personal"] = {
                "notes": personal.notes if personal else None,
                "rating": personal.rating if personal else None,
                "user_tags": tags,
            }
    preferences = {row.scope: row for row in db.query(ReaderPreference).filter_by(user_id=user.id)}
    for novel_id, entry in entry_by_novel_id.items():
        preference = preferences.get(f"story:{novel_id}")
        if preference and preference.values.get("typography"):
            entry["reader_typography"] = preference.values["typography"]
        text_style = preferences.get(f"textstyle:{novel_id}")
        if text_style:
            entry["text_style_guide"] = text_style.values.get("style_guide", "")
        pronunciation = preferences.get(f"pronunciation:{novel_id}")
        if pronunciation:
            entry["pronunciation"] = pronunciation.values

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
                novel_url_by_id[row.novel_id]
                for row in members
                if row.novel_id in novel_url_by_id
            ],
        })
    blocklist = db.query(BlocklistEntry).filter(BlocklistEntry.user_id == user.id).order_by(BlocklistEntry.kind, BlocklistEntry.value).all()
    for novel_id,story_doc in entry_by_novel_id.items():
        local=db.get(Novel,novel_id)
        imported_reading.enrich_export(db,user,local,story_doc,progress_by_novel.get(local.id),history_by_novel.get(local.id,[]),annotations_by_novel.get(local.id,[]))
    for library_doc,library in zip(library_documents,libraries):
        library_doc['novels'].extend(portable_story_service.retained_conflicts(db,user,library))
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
        "smart_shelves": smart_shelf_portable_service.export_rows(db, user.id),
        "blocklist": [{"kind": row.kind, "value": row.value} for row in blocklist],
        "reader_preferences": preferences["global"].values if "global" in preferences else None,
        "discovery_preferences": preferences["discovery"].values if "discovery" in preferences else None,
        "pronunciation": preferences["pronunciation"].values if "pronunciation" in preferences else None,
        "activity_preferences": preferences['reading_activity'].values if 'reading_activity' in preferences else None,
        "reading_goals": [{'year':int(scope.split(':')[1]),'values':row.values} for scope,row in sorted(preferences.items())
            if scope.startswith('reading_goal:') and scope.split(':')[1].isdigit()],
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
            novel = novel_index.get(portable_story_service.reference_key(member.library,member.url,member.portable_story))
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


def title_from_url(url: str) -> str:
    """Readable fallback title from a story URL slug (percent-decoded, never raw)."""
    return clean_title("", url) or "Untitled story"


def _create_novel(db: Session, library: Library, item) -> tuple[Novel | None, str | None]:
    if item.url.startswith('nexus-local:'):
        # Private originals are not source-fetch URLs. Retain their story and
        # reading material while the user restores the original file separately.
        novel=Novel(title=clean_title(item.title,item.url) or 'Private original awaiting restoration',url=item.url,library_id=library.id,novel_site='local',site='local',scrape_status='awaiting_original',num_chapters=0,chapter_count=0)
        db.add(novel);db.flush();return novel,None
    if not accepted_src(item.url):
        return None, "Not a supported source url"
    site_name = get_site_name_from_url(item.url)
    if not site_name:
        return None, "Could not determine site from URL"
    title = clean_title(item.title, item.url) or "Untitled story"
    novel = Novel(title=title, url=item.url, library_id=library.id, novel_site=site_name, scrape_status="pending")
    db.add(novel)
    db.flush()
    return novel, None


def _import_novel(db: Session, user: User, library: Library, item, queued: list[Novel], private_originals=None) -> dict:
    report: dict = {"url": item.url, "title": item.title, "status": None, "reason": None}
    if item.url is None:
        novel,portable_status,link_id,failure=portable_story_service.resolve(db,user,library,item)
        report.update(status=portable_status,reason=failure,portable_link_id=link_id)
        if novel is None:return report
    else:
        novel = db.query(Novel).filter(Novel.library_id == library.id, Novel.url == item.url).first()
        if novel is None:
            novel, failure = _create_novel(db, library, item)
            if novel is None:
                report['status']='failed';report['reason']=failure;return report
            report['status']='created'
            if novel.novel_site!='local':queued.append(novel)
        else:report['status']='linked'
    report['novel_id']=novel.id
    if novel.scrape_status=='awaiting_original':report['original_status']='unavailable'
    backup_placeholder_keys={}
    if private_originals and novel.scrape_status=='awaiting_original':
        # A full backup may restore content into a clean private destination.
        # Create only empty, source-less chapter slots; body material remains
        # in the owner's import review until explicitly selected and applied.
        existing=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id).count()
        if existing==0:
            from app.models.chapter import ContentStatus
            placeholder_by_archive_key={}
            for body in private_originals.values():
                if body.get('kind')!='current':continue
                chapter=Chapter(novel_id=novel.id,chapter_number=body['chapter_number'],title=body.get('title'),
                    category=body.get('category') or 'story',source_url=None,site_chapter_id=None,
                    metadata_manifest_key=None,metadata_chapter_key=None,content=None,document=None,
                    content_status=ContentStatus.MISSING,archived=bool(body.get('archived')),
                    archived_at=datetime.now(UTC).replace(tzinfo=None) if body.get('archived') else None)
                db.add(chapter)
                placeholder_by_archive_key[str(body['chapter_key'])]=chapter
            db.flush()
            for chapter in placeholder_by_archive_key.values():db.refresh(chapter)
            for ref in item.chapter_refs:
                target=placeholder_by_archive_key.get(str(ref.chapter_key)) if ref.chapter_key else None
                if target is None and ref.source_version:
                    target=next((chapter for body_key,chapter in placeholder_by_archive_key.items()
                        if any(candidate.get('chapter_key')==body_key and candidate.get('source_version')==ref.source_version
                               for candidate in private_originals.values())),None)
                if target is not None:backup_placeholder_keys[ref.ref]=target.chapter_key
    report["follow_state"] = _apply_follow(db, user, novel, item)
    # Run facts are portable; numeric snapshots are not chapter authority.
    # Keep all original positions and locators durably in the private review.
    facts=item.model_copy(deep=True)
    facts.progress=None
    for run in facts.reading_runs:run.progress=None
    mapping,protected,run_report=portable_reading_service.import_runs(db,user,novel,facts)
    if item.reading_runs:report['reading_runs']=run_report
    before_progress=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=novel.id).first()
    before_history=db.query(ReadingHistory).filter_by(user_id=user.id,novel_id=novel.id).count()
    before_annotations=db.query(ReadingAnnotation).filter_by(user_id=user.id,novel_id=novel.id).count()
    review=imported_reading.stage(db,user,novel,item,mapping,private_originals=private_originals,backup_placeholder_keys=backup_placeholder_keys)
    db.flush()
    report['reading_review_id']=review.id if review else None
    if private_originals and review and novel.scrape_status=='awaiting_original' and any(body.get('kind')=='current' for body in private_originals.values()):
        report['original_status']='backup_review'
    nested=[]
    for raw in item.pending_reading_imports:
        if raw.get('pending_reading_imports'):raise HTTPException(422,'Nested reading import reviews are not supported')
        from app.schemas.user_data import ExportNovel
        from pydantic import ValidationError
        try:original=ExportNovel.model_validate(raw)
        except ValidationError:raise HTTPException(422,'A retained reading review is invalid. Its original imported material was not applied.') from None
        nested_facts=original.model_copy(deep=True);nested_facts.progress=None
        for run in nested_facts.reading_runs:run.progress=None
        nested_mapping,_,_=portable_reading_service.import_runs(db,user,novel,nested_facts)
        retained=imported_reading.stage(db,user,novel,original,nested_mapping)
        if retained:nested.append(retained.id)
    report['retained_reading_review_ids']=nested
    report['progress']=('applied' if before_progress is None and review and review.payload.get('_progress_outcome')=='applied' else 'review_required') if item.progress else 'unchanged'
    report['history']={'added':db.query(ReadingHistory).filter_by(user_id=user.id,novel_id=novel.id).count()-before_history,'unchanged':0,'review_required':len(item.history) if review and len(review.applied_refs or {})<len(review.payload['chapter_refs']) else 0}
    report['annotations']={'added':db.query(ReadingAnnotation).filter_by(user_id=user.id,novel_id=novel.id).count()-before_annotations,'unchanged':0,'deferred':len(item.annotations) if review and len(review.applied_refs or {})<len(review.payload['chapter_refs']) else 0,'review_required':len(item.annotations) if review and len(review.applied_refs or {})<len(review.payload['chapter_refs']) else 0}
    report["personal"] = _apply_personal(db, user, novel, item.personal) if item.personal else None
    report["reader_preferences"] = _apply_reader_preferences(db, user, {"typography": item.reader_typography.model_dump(exclude_none=True)}, novel) if item.reader_typography is not None else None
    report["text_style_guide"] = _apply_reader_preferences(db, user, {"style_guide": item.text_style_guide}, novel, scope=f"textstyle:{novel.id}") if item.text_style_guide is not None else None
    report["pronunciation"] = _apply_pronunciation(db, user, item.pronunciation, novel) if item.pronunciation is not None else None
    return report


def _apply_pronunciation(db, user, value, novel=None):
    values = {"rules": sorted([rule.model_dump() for rule in value.rules], key=lambda rule: rule["source"]),
              "inherit_account": value.inherit_account if novel else False}
    return _apply_reader_preferences(db, user, values, novel, scope=f"pronunciation:{novel.id}" if novel else "pronunciation")


def _apply_reader_preferences(db, user, values, novel=None, scope=None):
    scope = scope or (f"story:{novel.id}" if novel else "global")
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=scope).first()
    if row is not None:
        return "unchanged" if row.values == values else "kept_local"
    db.add(ReaderPreference(user_id=user.id, novel_id=novel.id if novel else None, scope=scope, revision=1, values=values))
    db.flush()
    return "applied"


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
        "novels_conflicts": total("status", "conflict"),
        "follow_states_updated": total("follow_state", "updated"),
        "progress_applied": total("progress", "applied"),
        "history_added": sum_of("history", "added"),
        "history_updated": sum_of("history", "updated"),
        "history_kept_local": sum_of("history", "kept_local"),
        "reading_runs_added": sum_of("reading_runs","added"),
        "reading_runs_unchanged": sum_of("reading_runs","unchanged"),
        "reading_runs_kept_local": sum_of("reading_runs","kept_local"),
        "reading_run_events_added": sum_of("reading_runs","events_added"),
        "reading_run_inferred_events_added": sum_of("reading_runs","inferred_events"),
        "reading_current_restored": sum_of("reading_runs","current_restored"),
        "progress_kept_local": total("progress","kept_local"),
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


def import_user_data(db: Session, user: User, document: UserDataDocument, *, private_backup_bodies=None) -> dict:
    from app.services.chapter_identity_service import sqlite_transaction
    from app.auth.dependencies import require_current_session
    sqlite_transaction(db,write=True)
    fresh=db.query(User).filter_by(id=user.id).populate_existing().with_for_update().first()
    if fresh is None or fresh.is_disabled:raise HTTPException(401,'Account is unavailable')
    require_current_session(db,user.id)
    if document.version not in (1, EXPORT_VERSION):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported export version {document.version}; this Nexus reads version {EXPORT_VERSION}",
        )

    portable_reading_service.prepare_import(db,user,document)
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
            body_key=portable_story_service.reference_key(entry.name,item.url,item.portable_story)
            originals=(private_backup_bodies or {}).get(body_key,{})
            report = _import_novel(db, user, library, item, queued, originals)
            novel_reports.append(report)
            db.flush()
            novel=db.get(Novel,report.get('novel_id')) if report.get('novel_id') is not None else None
            if novel is not None:
                novel_index[portable_story_service.reference_key(entry.name,item.url,item.portable_story)]=novel
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
        imported_filters = imported_search_filters(item.filters)
        row = existing_searches.get(item.name)
        if row is None:
            row = SavedSearch(
                user_id=user.id,
                name=item.name,
                filters=imported_filters,
                notify_on_match=item.notify_on_match,
            )
            db.add(row)
            existing_searches[item.name] = row
            saved_status = "created"
        elif (row.filters or {}) == imported_filters and bool(row.notify_on_match) == item.notify_on_match:
            saved_status = "unchanged"
        else:
            saved_status = "conflict"
        saved_reports.append({"name": item.name, "status": saved_status})

    shelf_reports = _import_shelves(db, user, document.shelves, novel_index)
    smart_shelf_reports = smart_shelf_portable_service.import_rows(db, user.id, document.smart_shelves)
    blocklist_reports = _import_blocklist(db, user, document.blocklist)
    preference_report = _apply_reader_preferences(db, user, document.reader_preferences.model_dump(exclude_none=True)) if document.reader_preferences is not None else None
    pronunciation_report = _apply_pronunciation(db, user, document.pronunciation) if document.pronunciation is not None else None
    discovery_report = _apply_reader_preferences(db, user, document.discovery_preferences.model_dump(), scope="discovery") if document.discovery_preferences is not None else None

    activity_report=_apply_reader_preferences(db,user,document.activity_preferences.model_dump(),scope='reading_activity') if document.activity_preferences is not None else None
    goal_reports=[{'year':entry.year,'status':_apply_reader_preferences(db,user,entry.values.model_dump(),scope=f'reading_goal:{entry.year}')} for entry in document.reading_goals]
    db.commit()
    summary=_summarize(library_reports,saved_reports,shelf_reports,blocklist_reports)
    summary.update(activity_preferences_applied=int(activity_report=='applied'),
        smart_shelves_created=sum(entry['status']=='created' for entry in smart_shelf_reports),
        smart_shelves_conflicts=sum(entry['status']=='conflict' for entry in smart_shelf_reports),
        reading_goals_applied=sum(entry['status']=='applied' for entry in goal_reports),
        reading_goals_kept_local=sum(entry['status']=='kept_local' for entry in goal_reports))
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "summary": summary,
        "libraries": library_reports,
        "saved_searches": saved_reports,
        "shelves": shelf_reports,
        "smart_shelves": smart_shelf_reports,
        "blocklist": blocklist_reports,
        "reader_preferences": preference_report,
        "discovery_preferences": discovery_report,
        "pronunciation": pronunciation_report,
        "activity_preferences": activity_report,
        "reading_goals": goal_reports,
        "import_job_ids": [job.id for job in import_jobs],
    }
