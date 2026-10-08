import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.import_job import ImportJob
from app.models.user import User
from app.routers.novel import check_library
from app.services import import_job_service as imports

router = APIRouter(
    prefix="/imports",
    tags=["imports"],
    responses={401: {"description": "Not authenticated"}},
)

MAX_TEXT_CHARS = 1_000_000
MAX_EPUB_FILES = 100
MAX_EPUB_BYTES = 30 * 1024 * 1024


class UrlImportRequest(BaseModel):
    library_id: int
    text: str = Field(..., max_length=MAX_TEXT_CHARS, description="Pasted URLs, a CSV export or a Royal Road follow list")
    source: str = Field("url_list", pattern="^(url_list|rr_list)$")


class EpubFile(BaseModel):
    name: str = Field(..., max_length=300)
    data_base64: str


class EpubImportRequest(BaseModel):
    library_id: int
    files: list[EpubFile] = Field(..., min_length=1, max_length=MAX_EPUB_FILES)


class ListImportRequest(BaseModel):
    library_id: int
    source: str = Field(..., pattern="^(ao3_bookmarks|ffn_favorites)$")
    user: str = Field(..., min_length=1, max_length=100, description="AO3 username or FanFiction.net numeric user id")


def _created(db: Session, job: ImportJob) -> dict:
    return imports.job_to_dict(db, job)


@router.post("/urls", status_code=status.HTTP_202_ACCEPTED)
def import_urls(request: UrlImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue every story URL found in pasted text or CSV."""
    library = check_library(db, request.library_id, current_user)
    urls = imports.extract_urls(request.text, royalroad_paths=request.source == "rr_list")
    if not urls:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No URLs found")
    job = imports.create_job(db, current_user, library, request.source, entries=[{"url": url} for url in urls])
    return _created(db, job)


@router.post("/epub", status_code=status.HTTP_202_ACCEPTED)
def import_epubs(request: EpubImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue the original stories of EPUB files (FanFicFare, FicHub and similar)."""
    library = check_library(db, request.library_id, current_user)
    entries = []
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
            entries.append({"label": upload.name, "status": "unsupported", "reason": "no source URL in the EPUB"})
    job = imports.create_job(db, current_user, library, "epub", entries=entries)
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
