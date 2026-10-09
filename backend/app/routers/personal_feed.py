# routers/personal_feed.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import Response as AtomResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.webhook import PersonalFeedStatus
from app.services import personal_feed_service
from config.database import get_db

router = APIRouter(tags=["personal feed"], responses={404: {"description": "Not found"}})


def _feed_url(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/feeds/{token}.atom"


@router.get("/personal-feed", response_model=PersonalFeedStatus)
def feed_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # The token is stored only as a hash, so the URL cannot be shown again.
    return {"active": personal_feed_service.get_token_row(db, current_user.id) is not None, "feed_url": None}


@router.post("/personal-feed/token", response_model=PersonalFeedStatus, status_code=status.HTTP_201_CREATED)
def rotate_feed_token(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or rotate the feed token. The old URL stops working at once."""
    token = personal_feed_service.rotate(db, current_user)
    return {"active": True, "feed_url": _feed_url(request, token)}


@router.delete("/personal-feed/token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_feed_token(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    personal_feed_service.revoke(db, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/feeds/{token_file}")
def personal_feed(token_file: str, request: Request, db: Session = Depends(get_db)):
    """Atom feed for the token in the URL. No session: the token is the credential."""
    if not token_file.endswith(".atom"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found")
    token = token_file[: -len(".atom")]
    user = personal_feed_service.user_for_token(db, request, token)
    base = str(request.base_url).rstrip("/")
    body = personal_feed_service.build_atom(db, user, base, _feed_url(request, token))
    return AtomResponse(
        content=body.encode("utf-8"),
        media_type="application/atom+xml",
        headers={"Cache-Control": "private, no-cache"},
    )
