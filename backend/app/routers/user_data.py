from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.user_data import UserDataDocument
from app.services.user_data_service import export_user_data, import_user_data

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
