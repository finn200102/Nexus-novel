from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.user_data import UserDataDocument
from app.services import calibre_service
from app.services.user_data_service import export_user_data, import_user_data
from app.services.full_backup_service import export_full_backup, import_full_backup

router = APIRouter(
    prefix="/me",
    tags=["user data"],
    responses={401: {"description": "Not authenticated"}},
)


@router.get("/export")
def export_my_data(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Download every library, follow state, progress, history and annotation as JSON."""
    document = export_user_data(db, current_user)
    filename = f"nexus-export-{datetime.now(UTC):%Y%m%d}.json"
    return JSONResponse(document, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/backup")
def export_my_full_backup(library: str | None = Query(None,max_length=100), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Download private account data plus owned chapter bodies and retained originals."""
    archive = export_full_backup(db, current_user, library)

    def chunks():
        try:
            while block := archive.read(64 * 1024):
                yield block
        finally:
            archive.close()

    filename = f"nexus-full-backup-{datetime.now(UTC):%Y%m%d}.zip"
    return StreamingResponse(chunks(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


@router.post("/backup/import")
async def import_my_full_backup(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Validate a bounded private backup and stage its chapter bodies for review."""
    from app.services.full_backup_service import MAX_UPLOAD_BYTES
    content_type=request.headers.get("content-type","application/octet-stream").split(";",1)[0].strip().lower()
    if content_type not in ("application/zip","application/octet-stream"):
        raise HTTPException(415,"Upload a Nexus full-backup ZIP archive.")
    content_length=request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length)>MAX_UPLOAD_BYTES:
        raise HTTPException(413,"The backup exceeds the 256 MiB upload limit.")
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>MAX_UPLOAD_BYTES:raise HTTPException(413,"The backup exceeds the 256 MiB upload limit.")
        chunks.append(chunk)
    return import_full_backup(db,current_user,b"".join(chunks))


@router.get("/export/calibre")
def export_calibre(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Zip of the EPUBs of your downloaded novels, with OPF metadata Calibre reads on import."""
    archive = calibre_service.export_calibre_zip(db, current_user)

    def chunks():
        try:
            while block := archive.read(64 * 1024):
                yield block
        finally:
            archive.close()

    filename = f"nexus-calibre-{datetime.now(UTC):%Y%m%d}.zip"
    return StreamingResponse(chunks(), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import")
def import_my_data(
    document: UserDataDocument,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply an export document idempotently and return a per-item report.

    Missing novels are queued on import jobs (``import_job_ids``); their
    metadata scrapes run in the worker, one at a time.
    """
    return import_user_data(db, current_user, document)
