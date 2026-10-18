from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.routers.reader_tools import own_novel
from app.schemas.pronunciation import PronunciationWrite
from app.services.pronunciation_service import snapshot, write
from config.database import get_db

router = APIRouter(prefix="/audio/pronunciation", tags=["pronunciation"])


@router.get("")
def account_pronunciation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return snapshot(db, user.id)


@router.put("")
def save_account(value: PronunciationWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return write(db, user, value)


@router.get("/stories/{novel_id}")
def story_pronunciation(novel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    own_novel(db, user, novel_id)
    return snapshot(db, user.id, novel_id)


@router.put("/stories/{novel_id}")
def save_story(novel_id: int, value: PronunciationWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return write(db, user, value, novel_id)
