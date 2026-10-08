from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import source_status_service
from config.database import get_db

router = APIRouter(prefix="/sources", tags=["sources"], responses={404: {"description": "Not found"}})


@router.get("/status")
async def get_source_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Health of only the sites this user has novels from. Cached 60 s upstream."""
    return await source_status_service.sites_status(db, current_user)
