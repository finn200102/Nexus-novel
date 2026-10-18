import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.import_job import ImportJob
from app.models.import_job import ImportJobItem
from app.models.novel import Novel
from app.models.user import User
from app.routers.novel import check_library
from app.services import calibre_service
from app.services import import_job_service as imports

router = APIRouter(
    prefix="/imports",
    tags=["imports"],
    responses={401: {"description": "Not authenticated"}},
)

MAX_TEXT_CHARS = 1_000_000
MAX_EPUB_FILES = 100
MAX_EPUB_BYTES = 30 * 1024 * 1024
MAX_CALIBRE_BYTES = calibre_service.MAX_CALIBRE_BYTES


class UrlImportRequest(BaseModel):
    library_id: int
    text: str = Field(..., max_length=MAX_TEXT_CHARS, description="Pasted URLs, a CSV export or a Royal Road follow list")
    source: str = Field("url_list", pattern="^(url_list|rr_list)$")


class EpubFile(BaseModel):
    name: str = Field(..., max_length=300)
    data_base64: str = Field(..., max_length=MAX_EPUB_BYTES * 4 // 3 + 4)


class EpubImportRequest(BaseModel):
    library_id: int
    files: list[EpubFile] = Field(..., min_length=1, max_length=MAX_EPUB_FILES)


class CalibreImportRequest(BaseModel):
    library_id: int
    data_base64: str = Field(..., max_length=MAX_CALIBRE_BYTES * 4 // 3 + 4, description="Base64 of a Calibre metadata.db")


class ListImportRequest(BaseModel):
    library_id: int
    source: str = Field(..., pattern="^(ao3_bookmarks|ffn_favorites)$")
    user: str = Field(..., min_length=1, max_length=100, description="AO3 username or FanFiction.net numeric user id")


def _created(db: Session, job: ImportJob) -> dict:
    return imports.job_to_dict(db, job)


def _url_entries(request: UrlImportRequest) -> list[dict]:
    urls = imports.extract_urls(request.text, royalroad_paths=request.source == "rr_list")
    if not urls:
        raise HTTPException(422, detail="No URLs found")
    if len(urls) > imports.MAX_ITEMS_PER_JOB:
        raise HTTPException(422, detail=f"Split this list into batches of at most {imports.MAX_ITEMS_PER_JOB} links. Nothing was imported.")
    return [{"url": url} for url in urls]


@router.post("/urls/preview")
def preview_urls(request: UrlImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Classify a pasted batch without creating entries or contacting sources."""
    library = check_library(db, request.library_id, current_user)
    existing = {imports.url_key(novel.url): novel for novel in db.query(Novel).filter(Novel.library_id == library.id).all() if novel.url}
    seen = set()
    items, counts = [], {}
    for position, entry in enumerate(_url_entries(request)):
        url = entry["url"]
        key = imports.url_key(url)
        item_status, reason = "ready", None
        if not imports.accepted_src(url) or len(url) > 500:
            item_status, reason = "unsupported", "Link is invalid or longer than 500 characters."
        elif key in seen:
            item_status, reason = "duplicate", "Listed more than once in this import."
        elif key in existing:
            item_status, reason = "duplicate", "Already in this library."
        seen.add(key)
        known = existing.get(key)
        items.append({"position": position, "url": url, "title": known.title if known else None, "status": item_status, "reason": reason})
        counts[item_status] = counts.get(item_status, 0) + 1
    return {"library_id": library.id, "total_items": len(items), "items": items, "counts": counts,
            "warnings": ["This preview checks links and duplicates. Source availability and household content limits are checked during import."]}


@router.post("/urls", status_code=status.HTTP_202_ACCEPTED)
def import_urls(request: UrlImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue every story URL found in pasted text or CSV."""
    library = check_library(db, request.library_id, current_user)
    entries = _url_entries(request)
    for entry in entries:
        if len(entry["url"]) > 500:
            entry.update(url=None, status="unsupported", reason="Link is longer than 500 characters.")
    job = imports.create_job(db, current_user, library, request.source, entries=entries)
    return _created(db, job)


@router.post("/epub", status_code=status.HTTP_202_ACCEPTED)
def import_epubs(request: EpubImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue the original stories of EPUB files (FanFicFare, FicHub and similar)."""
    library = check_library(db, request.library_id, current_user)
    entries = []
    if sum(len(upload.data_base64) for upload in request.files) > 80 * 1024 * 1024:
        raise HTTPException(422, detail="Split this upload into batches smaller than 60 MB")
    for upload in request.files:
        try:
            data = base64.b64decode(upload.data_base64, validate=True)
        except (binascii.Error, ValueError):
            entries.append({"label": upload.name, "status": "failed", "reason": "file is not valid base64"})
            continue
        if len(data) > MAX_EPUB_BYTES:
            entries.append({"label": upload.name, "status": "failed", "reason": "file is larger than 30 MB"})
            continue
        url = imports.epub_source_url(data)
        if url:
            entries.append({"label": upload.name, "url": url})
        else:
            from app.services.local_epub import import_local_epub
            try:
                with db.begin_nested():
                    result = import_local_epub(db, current_user, library, data)
                entries.append({"label": upload.name, **result})
            except ValueError as exc:
                entries.append({"label": upload.name, "status": "failed", "reason": str(exc)})
    job = imports.create_job(db, current_user, library, "epub", entries=entries)
    return _created(db, job)


@router.post("/calibre", status_code=status.HTTP_202_ACCEPTED)
def import_calibre(request: CalibreImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue the stories of a Calibre library (metadata.db) with their tags, rating and read state."""
    library = check_library(db, request.library_id, current_user)
    try:
        data = base64.b64decode(request.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="metadata.db is not valid base64")
    try:
        books = calibre_service.read_calibre_library(data)
    except calibre_service.CalibreFormatError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if not books:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The Calibre library has no books")
    entries, personal = calibre_service.calibre_entries(books)
    job = imports.create_job(db, current_user, library, "calibre", entries=entries, params={"calibre": personal})
    return _created(db, job)


@router.post("/list", status_code=status.HTTP_202_ACCEPTED)
def import_list(request: ListImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue a public list: AO3 bookmarks of a user, or FanFiction.net favorites of a profile."""
    library = check_library(db, request.library_id, current_user)
    user = request.user.strip()
    if request.source == "ffn_favorites" and not user.isdigit():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use the numeric FanFiction.net user id")
    job = imports.create_job(db, current_user, library, request.source, params={"user": user})
    return _created(db, job)


@router.get("")
def list_imports(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    jobs = (
        db.query(ImportJob)
        .filter(ImportJob.user_id == current_user.id)
        .order_by(ImportJob.id.desc())
        .limit(limit)
        .all()
    )
    return [imports.job_to_dict(db, job) for job in jobs]


def _own_job(db: Session, job_id: int, user: User) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    return job


@router.get("/{job_id}")
def get_import(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The job with a per-item report."""
    return imports.job_to_dict(db, _own_job(db, job_id, current_user), items=True)


@router.post("/{job_id}/cancel")
def cancel_import(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _own_job(db, job_id, current_user)
    if job.status in imports.ACTIVE_JOB_STATUSES:
        job.status = "cancelled"
        job.finished_at = imports.utc_now()
        db.commit()
    return imports.job_to_dict(db, job)


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_import(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _own_job(db, job_id, current_user)
    check_library(db, job.library_id, current_user)
    if job.status in imports.ACTIVE_JOB_STATUSES:
        raise HTTPException(409, detail="Wait for this import to stop before retrying it.")
    retryable = db.query(ImportJobItem).filter(ImportJobItem.job_id == job.id,
        ImportJobItem.status.in_(["failed", "queued", "running"]), ImportJobItem.url.isnot(None)).all()
    resume_list = job.status == "failed" and job.source in imports.LIST_SOURCES and job.next_page is not None
    if not retryable and not resume_list:
        raise HTTPException(422, detail="There are no failed links to retry. Re-upload invalid EPUB files after correcting them.")
    for item in retryable:
        item.status, item.reason = "queued", None
    job.status = "expanding" if resume_list else "queued"
    job.finished_at, job.error = None, None
    db.commit()
    return imports.job_to_dict(db, job, items=True)
