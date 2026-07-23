from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.follow import UserNovelFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.routers.novel import get_or_create_follow
from app.schemas.follow import FollowSummary

router = APIRouter(prefix="/follows", tags=["follows"])


def _library(db: Session, library_id: int, user: User) -> Library:
    library = db.query(Library).filter(Library.id == library_id, Library.user_id == user.id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return library


@router.get("", response_model=list[FollowSummary])
def list_follows(library_id: int, state: str | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _library(db, library_id, current_user)
    query = db.query(UserNovelFollow, Novel).join(Novel, Novel.id == UserNovelFollow.novel_id).filter(
        UserNovelFollow.user_id == current_user.id,
        Novel.library_id == library_id,
    )
    if state:
        query = query.filter(UserNovelFollow.state == state)
    return [FollowSummary(novel_id=follow.novel_id, library_id=library_id, title=novel.title, author=novel.author, state=follow.state, followed_at=follow.followed_at, download_policy=follow.download_policy, download_count=follow.download_count, notification_policy=follow.notification_policy, notification_count=follow.notification_count) for follow, novel in query.order_by(UserNovelFollow.updated_at.desc()).all()]


@router.get("/{novel_id}", response_model=FollowSummary)
def get_follow(novel_id: int, library_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _library(db, library_id, current_user)
    novel = db.query(Novel).filter(Novel.id == novel_id, Novel.library_id == library_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    follow = get_or_create_follow(db, current_user.id, novel)
    db.commit()
    return FollowSummary(novel_id=novel.id, library_id=library_id, title=novel.title, author=novel.author, state=follow.state, followed_at=follow.followed_at, download_policy=follow.download_policy, download_count=follow.download_count, notification_policy=follow.notification_policy, notification_count=follow.notification_count)
