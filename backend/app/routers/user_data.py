import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config.database import SessionLocal, get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.routers.novel import scrape_novel_background
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
async def import_my_data(
    document: UserDataDocument,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply an export document idempotently and return a per-item report."""
    loop = asyncio.get_running_loop()

    def schedule_scrape(novel_id: int, metadata_id: int) -> None:
        background_tasks.add_task(scrape_novel_background, novel_id, metadata_id, SessionLocal, loop)

    return await import_user_data(db, current_user, document, schedule_scrape)
