"""Sign-in sessions with rotating refresh tokens.

A session is one signed-in device. The browser holds its current refresh
token in an HttpOnly, SameSite=Strict cookie and keeps the short-lived access
token in memory only. Every refresh exchanges the token for a new one; the
database only stores SHA-256 hashes.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.logging_config import get_logger
from app.models.account import RefreshToken, UserSession
from app.models.user import User
from config.settings import settings

logger = get_logger(__name__)

REFRESH_COOKIE = "nexus_refresh"
# Two tabs may refresh with the same cookie at once. The slower one presents a
# token that was rotated a moment ago; within this window that is treated as a
# race, not as a stolen token.
ROTATION_GRACE = timedelta(seconds=30)


class InvalidRefreshToken(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def client_ip(request: Request) -> str:
    # nginx sets X-Real-IP to the connecting address and overwrites any value
    # a client sent; the API itself is only published on loopback.
    forwarded = request.headers.get("x-real-ip", "").strip()
    if forwarded:
        return forwarded[:64]
    return request.client.host if request.client else "unknown"


def _refresh_expiry() -> datetime:
    return utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def _issue_refresh_token(db: Session, session: UserSession) -> str:
    raw = new_secret()
    db.add(RefreshToken(session_id=session.id, token_hash=hash_secret(raw), expires_at=_refresh_expiry()))
    return raw


def _touch(session: UserSession, request: Request | None) -> None:
    session.last_seen_at = utcnow()
    if request is not None:
        session.ip_address = client_ip(request)
        session.user_agent = (request.headers.get("user-agent") or "")[:255] or None


def start_session(db: Session, user: User, request: Request | None = None) -> tuple[UserSession, str]:
    """Create a session for ``user``; returns it and its first refresh token.

    The caller commits.
    """
    session = UserSession(user_id=user.id)
    _touch(session, request)
    db.add(session)
    db.flush()
    return session, _issue_refresh_token(db, session)


def rotate_refresh_token(db: Session, raw: str | None, request: Request | None = None) -> tuple[UserSession, str]:
    """Exchange a refresh token for its successor and commit."""
    if not raw:
        raise InvalidRefreshToken()
    now = utcnow()
    token = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_secret(raw)).first()
    if token is None:
        raise InvalidRefreshToken()
    session = db.get(UserSession, token.session_id)
    if session is None or session.revoked_at is not None or token.expires_at <= now:
        raise InvalidRefreshToken()
    user = db.get(User, session.user_id)
    if user is None or user.is_disabled:
        raise InvalidRefreshToken()

    if token.rotated_at is not None and now - token.rotated_at > ROTATION_GRACE:
        # A token that was already exchanged is back: either the cookie was
        # copied or a client replayed it. End the session on every device.
        session.revoked_at = now
        db.commit()
        logger.warning("refresh_token_reuse_detected", user_id=session.user_id, session_id=session.id)
        raise InvalidRefreshToken()
    if token.rotated_at is None:
        db.query(RefreshToken).filter(
            RefreshToken.id == token.id, RefreshToken.rotated_at.is_(None)
        ).update({RefreshToken.rotated_at: now}, synchronize_session=False)
    # Rotated tokens are only needed for reuse detection.
    db.query(RefreshToken).filter(
        RefreshToken.session_id == session.id,
        RefreshToken.rotated_at < now - timedelta(days=1),
    ).delete(synchronize_session=False)

    _touch(session, request)
    successor = _issue_refresh_token(db, session)
    db.commit()
    return session, successor


def session_for_refresh_token(db: Session, raw: str | None) -> UserSession | None:
    if not raw:
        return None
    token = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_secret(raw)).first()
    return db.get(UserSession, token.session_id) if token else None


def revoke_session(db: Session, session: UserSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()


def revoke_user_sessions(db: Session, user_id: int, keep_session_id: int | None = None) -> int:
    query = db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if keep_session_id is not None:
        query = query.filter(UserSession.id != keep_session_id)
    return query.update({UserSession.revoked_at: utcnow()}, synchronize_session=False)


def _cookie_secure(request: Request) -> bool:
    mode = settings.REFRESH_COOKIE_SECURE.strip().lower()
    if mode in {"true", "1", "yes"}:
        return True
    if mode in {"false", "0", "no"}:
        return False
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return scheme.split(",")[0].strip() == "https"


def set_refresh_cookie(response: Response, request: Request, raw: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(request),
        path="/",
    )


def clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path="/", httponly=True, samesite="strict", secure=_cookie_secure(request)
    )


def token_response(user: User, session: UserSession, message: str = "Login successful") -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "message": message,
        "access_token": create_access_token({"sub": str(user.id), "sid": session.id}),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "is_admin": bool(user.is_admin),
    }
