from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.jwt import verify_token
from app.services.user_services import get_user_by_id
from app.models.account import UserSession
from app.models.user import User

# OAuth2 scheme for token extraction from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


@dataclass
class Authenticated:
    user: User
    session: UserSession


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_auth(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Authenticated:
    """Resolve the bearer access token to its user and still-active session.

    Checking the session on every request makes sign-out, "sign out other
    devices", password resets and disabling an account take effect at once
    instead of when the access token expires.
    """
    token_data = verify_token(token)
    session = db.get(UserSession, token_data["session_id"])
    if session is None or session.revoked_at is not None or session.user_id != token_data["user_id"]:
        raise _unauthorized("Session ended. Please sign in again.")
    user = get_user_by_id(db, token_data["user_id"])
    if user is None or user.is_disabled:
        raise _unauthorized("User not found")
    return Authenticated(user=user, session=session)


def get_current_user(auth: Authenticated = Depends(get_current_auth)) -> User:
    return auth.user


def require_admin(current_user: User = Depends(get_current_user)):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return current_user
