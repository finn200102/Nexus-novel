from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import NovelSearch
from app.models.user import User
from app.auth.dependencies import get_current_user
from scripts.get_trending import get_royalroad_trending
from typing import List

router = APIRouter(
    prefix="/discovery",
    tags=["discovery"],
    responses={404: {"description": "Not found"}},
)

@router.get("/trending", response_model=List[NovelSearch], status_code=status.HTTP_200_OK)
def trending(source: str = "royalroad", current_user: User = Depends(get_current_user)):
    if source == "royalroad":
        novels = get_royalroad_trending()
    else:
        raise HTTPException(status_code=400, detail=f"Source '{source}' not supported")
    return novels




