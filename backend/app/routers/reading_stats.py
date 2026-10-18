from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.chapter import Chapter
from app.models.user import User
import app.services.novel_services as novel_services
from app.services import reading_stats_service as stats
from config.database import get_db
from app.services import reading_activity_service as activity
from app.schemas.reading_activity import (ActivityWrite,GoalWrite,ReadingTimeResponse,StatsSummaryResponse,
    ReadingActivityPreferenceResponse,ReadingGoalResponse,CalendarYearReviewResponse)

router = APIRouter(prefix="/stats", tags=["reading stats"], responses={404: {"description": "Not found"}})


class ReadingTimeUpdate(BaseModel):
    novel_id: int
    chapter_id: int
    seconds: int = Field(ge=0)
    words_read_estimate: int = Field(default=0, ge=0)


@router.post("/reading-time", response_model=ReadingTimeResponse, response_model_exclude_unset=True)
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


@router.get("/summary", response_model=StatsSummaryResponse, response_model_exclude_unset=True)
def reading_summary(
    range: Literal["week", "month", "year", "all"] = Query(default="week"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return stats.get_summary(db, user_id=current_user.id, range_name=range)



def _private(response):response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/preferences', response_model=ReadingActivityPreferenceResponse, response_model_exclude_unset=True)
def preferences(response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    _private(response);return activity.preference(db,user.id,activity.ACTIVITY_SCOPE)


@router.put('/preferences', response_model=ReadingActivityPreferenceResponse, response_model_exclude_unset=True)
def update_preferences(value:ActivityWrite,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    _private(response);return activity.write(db,user.id,activity.ACTIVITY_SCOPE,value)


@router.get('/goals/{year}', response_model=ReadingGoalResponse, response_model_exclude_unset=True)
def goal(year:int,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    activity.validate_year(year);_private(response);return activity.preference(db,user.id,f'reading_goal:{year}')


@router.put('/goals/{year}', response_model=ReadingGoalResponse, response_model_exclude_unset=True)
def update_goal(year:int,value:GoalWrite,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    activity.validate_year(year);_private(response);return activity.write(db,user.id,f'reading_goal:{year}',value)


@router.get('/review/{year}', response_model=CalendarYearReviewResponse, response_model_exclude_unset=True)
def year_review(year:int,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    _private(response);return activity.review(db,user.id,year)
