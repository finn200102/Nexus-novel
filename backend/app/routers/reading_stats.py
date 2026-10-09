from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.chapter import Chapter
from app.models.user import User
import app.services.novel_services as novel_services
from app.services import reading_stats_service as stats
from config.database import get_db

router = APIRouter(prefix="/stats", tags=["reading stats"], responses={404: {"description": "Not found"}})


class ReadingTimeUpdate(BaseModel):
    novel_id: int
    chapter_id: int
    seconds: int = Field(ge=0)
    words_read_estimate: int = Field(default=0, ge=0)


@router.post("/reading-time")
def record_reading_time(
    payload: ReadingTimeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, payload.novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    if not db.query(Chapter.id).filter(Chapter.id == payload.chapter_id, Chapter.novel_id == novel.id).first():
        raise HTTPException(status_code=404, detail="Chapter not found")
    recorded = stats.record_reading_time(
        db, user_id=current_user.id, novel_id=novel.id,
        seconds=payload.seconds, words=payload.words_read_estimate,
    )
    return {"recorded_seconds": recorded}


@router.get("/summary")
def reading_summary(
    range: Literal["week", "month", "year", "all"] = Query(default="week"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return stats.get_summary(db, user_id=current_user.id, range_name=range)
