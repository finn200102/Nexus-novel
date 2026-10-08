"""Durable import jobs (WP-4): many stories into one library, one at a time.

A job is created by the API with its items already listed (URL lists, CSV,
EPUB source URLs, /me/import) or with a public list to expand (AO3
bookmarks, FanFiction.net favorites). The worker expands lists page by page
through the metadata server's live listings (each page one paced request)
and then processes items sequentially: start the metadata scrape, create the
library entry, and wait for the scrape like the add-novel flow does. Every
item ends as linked, duplicate, unsupported or failed with a reason. A
restarted worker resumes the unfinished items.
"""

import asyncio
import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Callable
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.import_job import ImportJob, ImportJobItem
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.routers.novel import get_site_name_from_url, scrape_novel_background, supported_src
from app.services import metadata_client
import app.services.novel_services as novel_services

logger = get_logger(__name__)

URL_SOURCES = ("url_list", "rr_list", "epub", "user_data")
LIST_SOURCES = {"ao3_bookmarks": ("archive", "bookmarks"), "ffn_favorites": ("fanfiction", "favorites")}
FINAL_ITEM_STATUSES = ("linked", "duplicate", "unsupported", "failed")
ACTIVE_JOB_STATUSES = ("queued", "expanding", "running")
MAX_ITEMS_PER_JOB = 2000
MAX_LIST_PAGES = 100

_URL_RE = re.compile(r"""https?://[^\s,;"'<>()\[\]]+""", re.IGNORECASE)
# Royal Road follow lists pasted from the site often carry bare paths.
_RR_ID_RE = re.compile(r"/fiction/(\d+)")

# (novel_id, metadata_id, session_factory, loop) -> None; waits for the scrape.
ScrapeRunner = Callable[..., None]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def url_key(url: str | None) -> str:
    if not url:
        return ""
    key = url.strip().split("#", 1)[0].rstrip("/").lower()
    return key.replace("http://", "https://", 1)


def extract_urls(text: str, *, royalroad_paths: bool = False) -> list[str]:
    """Every story URL in pasted text or CSV, in order of appearance."""
    urls = [match.rstrip(".") for match in _URL_RE.findall(text or "")]
    if royalroad_paths:
        known = {fiction_id for url in urls for fiction_id in _RR_ID_RE.findall(url)}
        for fiction_id in _RR_ID_RE.findall(text or ""):
            if fiction_id not in known:
                urls.append(f"https://www.royalroad.com/fiction/{fiction_id}")
                known.add(fiction_id)
    return urls


def epub_source_url(data: bytes) -> str | None:
    """The original story URL recorded in an EPUB.

    FanFicFare and FicHub write it to ``dc:source`` or a URL ``dc:identifier``;
    otherwise the title page usually links it.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    with archive:
        names = archive.namelist()
        candidates: list[str] = []
        opf_path = None
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            opf_path = rootfile.get("full-path") if rootfile is not None else None
        except (KeyError, ElementTree.ParseError):
            opf_path = next((name for name in names if name.endswith(".opf")), None)
        if opf_path and opf_path in names:
            try:
                opf = ElementTree.fromstring(archive.read(opf_path))
                for tag in ("source", "identifier", "relation"):
                    for element in opf.iter(f"{{http://purl.org/dc/elements/1.1/}}{tag}"):
                        candidates.extend(extract_urls((element.text or "").removeprefix("url:")))
            except ElementTree.ParseError:
                pass
        if not any(supported_src(url) for url in candidates):
            pages = [name for name in names if name.lower().endswith((".xhtml", ".html", ".htm"))]
            for name in sorted(pages, key=lambda value: ("title" not in value.lower(), value))[:6]:
                candidates.extend(extract_urls(archive.read(name).decode("utf-8", "ignore")))
                if any(supported_src(url) for url in candidates):
                    break
    supported = [url for url in candidates if supported_src(url)]
    return (supported or candidates or [None])[0]


def _add_items(db: Session, job: ImportJob, entries: list[dict], seen: set[str]) -> int:
    """Append items; repeated URLs within the job are reported as duplicates."""
    position = job.total_items or 0
    added = 0
    for entry in entries:
        if position >= MAX_ITEMS_PER_JOB:
            break
        url = (entry.get("url") or "").strip() or None
        item = ImportJobItem(job_id=job.id, position=position, url=url, label=entry.get("label"),
                             title=entry.get("title"), novel_id=entry.get("novel_id"))
        key = url_key(url)
        if entry.get("status"):
            item.status, item.reason = entry["status"], entry.get("reason")
        elif key and key in seen:
            item.status, item.reason = "duplicate", "listed more than once in this import"
        if key:
            seen.add(key)
        db.add(item)
        position += 1
        added += 1
    job.total_items = position
    return added


def create_job(db: Session, user: User, library: Library, source: str, *, entries: list[dict] | None = None,
               params: dict | None = None, commit: bool = True) -> ImportJob:
    job = ImportJob(user_id=user.id, library_id=library.id, source=source, params=params or {},
                    status="expanding" if source in LIST_SOURCES else "queued",
                    next_page=1 if source in LIST_SOURCES else None, total_items=0)
    db.add(job)
    db.flush()
    _add_items(db, job, entries or [], set())
    if commit:
        db.commit()
        db.refresh(job)
    return job


def summarize(db: Session, job: ImportJob) -> dict:
    counts: dict[str, int] = {}
    for (status,) in db.query(ImportJobItem.status).filter(ImportJobItem.job_id == job.id):
        counts[status] = counts.get(status, 0) + 1
    return counts


def job_to_dict(db: Session, job: ImportJob, *, items: bool = False) -> dict:
    data = {
        "id": job.id,
        "library_id": job.library_id,
        "source": job.source,
        "params": job.params or {},
        "status": job.status,
        "total_items": job.total_items,
        "counts": summarize(db, job),
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
    if items:
        data["items"] = [
            {"position": item.position, "url": item.url, "label": item.label, "title": item.title,
             "status": item.status, "reason": item.reason, "novel_id": item.novel_id}
            for item in job.items
        ]
    return data


def _library_novel(db: Session, library_id: int, url: str) -> Novel | None:
    variants = {url, url.rstrip("/"), url.rstrip("/") + "/"}
    return db.query(Novel).filter(Novel.library_id == library_id, Novel.url.in_(variants)).first()


async def _start_metadata(url: str, site: str) -> tuple[int | None, str | None]:
    result = await metadata_client.scrape_novel_by_url(url, site)
    metadata_id = result.get("novel_id") if result else None
    if not result or not result.get("success") or not metadata_id:
        return None, (result or {}).get("message") or "Failed to start scraping"
    return int(metadata_id), None


async def _expand_list(db: Session, job: ImportJob) -> None:
    """Fetch one page of a public list and append its stories."""
    site, list_name = LIST_SOURCES[job.source]
    page = job.next_page or 1
    answer = await metadata_client.live_listing(
        "user-list", {"site": site, "list": list_name, "user": (job.params or {}).get("user", ""), "page": page})
    results = answer.get("results") or []
    seen = {url_key(url) for (url,) in db.query(ImportJobItem.url).filter(ImportJobItem.job_id == job.id)}
    if answer.get("error"):
        error = answer["error"]
        if page == 1:
            job.status, job.error, job.finished_at = "failed", f"{error.get('code')}: {error.get('message')}", utc_now()
            db.commit()
            return
        # A later page failing keeps what was listed so far.
        job.error = f"stopped at page {page}: {error.get('code')}"
        results = []
    new = [{"url": row.get("url"), "title": row.get("title")} for row in results if row.get("url")]
    fresh = [entry for entry in new if url_key(entry["url"]) not in seen]
    _add_items(db, job, new, seen)
    last_page = (not fresh or site == "fanfiction" or page >= MAX_LIST_PAGES
                 or job.total_items >= MAX_ITEMS_PER_JOB or bool(answer.get("error")))
    job.next_page = None if last_page else page + 1
    if last_page:
        job.status = "running"
    db.commit()


async def _process_item(db: Session, job: ImportJob, item: ImportJobItem, session_factory, scrape: ScrapeRunner,
                        loop: asyncio.AbstractEventLoop | None) -> None:
    if item.novel_id is None:
        url = item.url
        site = get_site_name_from_url(url) if url else None
        if not url:
            item.status, item.reason = "unsupported", item.reason or "no story URL found"
            return
        if not supported_src(url) or not site:
            item.status, item.reason = "unsupported", "not a supported source URL"
            return
        existing = _library_novel(db, job.library_id, url)
        if existing is not None:
            item.status, item.novel_id, item.title = "duplicate", existing.id, existing.title
            item.reason = "already in this library"
            return
        metadata_id, failure = await _start_metadata(url, site)
        if metadata_id is None:
            item.status, item.reason = "failed", failure
            return
        title = item.title or url.rstrip("/").split("/")[-1].replace("-", " ").title()
        novel = novel_services.create_novel(db, {
            "title": title, "url": url, "library_id": job.library_id, "metadata_id": metadata_id,
            "novel_site": site, "scrape_status": "pending",
        })
        item.novel_id = novel.id
        item.status = "running"
        db.commit()

    novel = db.get(Novel, item.novel_id)
    if novel is None:
        item.status, item.reason = "failed", "library entry was deleted during the import"
        return
    if novel.metadata_id is None:
        # Created by /me/import: the metadata scrape starts here, one at a time.
        site = novel.novel_site or get_site_name_from_url(novel.url or "")
        if not novel.url or not site or not supported_src(novel.url):
            item.status, item.reason = "unsupported", "not a supported source URL"
            return
        metadata_id, failure = await _start_metadata(novel.url, site)
        if metadata_id is None:
            novel.scrape_status, novel.scrape_error = "failed", failure
            item.status, item.reason = "failed", failure
            return
        novel.metadata_id = metadata_id
        item.status = "running"
        db.commit()
    if novel.scrape_status != "completed":
        novel_id, metadata_id = int(novel.id), int(novel.metadata_id)
        await asyncio.to_thread(scrape, novel_id, metadata_id, session_factory, loop)
        db.expire(novel)
    if novel.scrape_status == "completed":
        item.status, item.reason, item.title = "linked", None, novel.title
    else:
        item.status, item.reason = "failed", novel.scrape_error or "metadata scrape failed"


async def run_import_job(job_id: int, session_factory, *, scrape: ScrapeRunner = scrape_novel_background,
                         loop: asyncio.AbstractEventLoop | None = None, should_stop: Callable[[], bool] = lambda: False) -> None:
    """Run one job until it finishes, is cancelled, or ``should_stop`` says so."""
    db = session_factory()
    try:
        job = db.get(ImportJob, job_id)
        if job is None or job.status not in ACTIVE_JOB_STATUSES:
            return
        job.started_at = job.started_at or utc_now()
        db.commit()
        while job.status == "expanding" and not should_stop():
            await _expand_list(db, job)
            db.refresh(job)
        while job.status == "running" or job.status == "queued":
            if job.status == "queued":
                job.status = "running"
                db.commit()
            if should_stop():
                return
            item = (
                db.query(ImportJobItem)
                .filter(ImportJobItem.job_id == job.id, ImportJobItem.status.notin_(FINAL_ITEM_STATUSES))
                .order_by(ImportJobItem.position.asc())
                .first()
            )
            if item is None:
                job.status, job.finished_at = "finished", utc_now()
                db.commit()
                return
            try:
                await _process_item(db, job, item, session_factory, scrape, loop)
            except Exception as exc:  # one bad item never stops the job
                db.rollback()
                logger.error("Import item failed", job_id=job.id, position=item.position, error=str(exc))
                item = db.get(ImportJobItem, item.id)
                item.status, item.reason = "failed", str(exc)[:500]
            db.commit()
            db.refresh(job)  # sees a cancellation made through the API
    finally:
        db.close()


def next_job_id(db: Session) -> int | None:
    job = (
        db.query(ImportJob)
        .filter(ImportJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(ImportJob.created_at.asc(), ImportJob.id.asc())
        .first()
    )
    return job.id if job else None
