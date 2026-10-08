"""App passwords for e-readers (OPDS downloads and KOReader sync).

An app password is a random string shown once. The database keeps
``bcrypt(md5(app password))``. OPDS clients send the app password in HTTP Basic
auth and the server hashes it with MD5 before checking. KOReader already sends
``md5(password)`` as ``x-auth-key``, so both paths reach the same stored value.
The account password is never accepted here.
"""

import hashlib
import re
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import rate_limit
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import client_ip, utcnow
from app.models.ereader import AppPassword
from app.models.user import User
from app.services.user_services import get_user_by_username

SCOPES = ("opds", "kosync")
MD5_HEX = re.compile(r"^[0-9a-f]{32}$")
MAX_PER_USER = 25

APP_AUTH_FAILURES_PER_IP = rate_limit.Limit("appauth:ip", 60, timedelta(minutes=15))
APP_AUTH_FAILURES_PER_USER = rate_limit.Limit("appauth:user", 20, timedelta(minutes=15))


def _md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def create(db: Session, user: User, label: str, scope: str) -> tuple[AppPassword, str]:
    if scope not in SCOPES:
        raise ValueError("Unknown scope")
    active = db.query(AppPassword).filter(AppPassword.user_id == user.id, AppPassword.revoked_at.is_(None)).count()
    if active >= MAX_PER_USER:
        raise ValueError("Too many app passwords; revoke one first")
    plain = secrets.token_urlsafe(18)
    row = AppPassword(user_id=user.id, label=label.strip()[:120], scope=scope, secret_hash=hash_password(_md5_hex(plain)))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plain


def list_for_user(db: Session, user_id: int) -> list[AppPassword]:
    return (
        db.query(AppPassword)
        .filter(AppPassword.user_id == user_id)
        .order_by(AppPassword.created_at.desc(), AppPassword.id.desc())
        .all()
    )


def revoke(db: Session, user_id: int, app_password_id: int) -> bool:
    row = db.query(AppPassword).filter(AppPassword.id == app_password_id, AppPassword.user_id == user_id).first()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        db.commit()
    return True


def _authenticate(db: Session, request: Request, username: str, scope: str, key_md5: str) -> User:
    ip = client_ip(request)
    rate_limit.check(db, APP_AUTH_FAILURES_PER_IP, ip)
    rate_limit.check(db, APP_AUTH_FAILURES_PER_USER, username)

    user = get_user_by_username(db, username).first()
    matched: AppPassword | None = None
    if user is not None and not user.is_disabled and MD5_HEX.match(key_md5):
        candidates = (
            db.query(AppPassword)
            .filter(AppPassword.user_id == user.id, AppPassword.scope == scope, AppPassword.revoked_at.is_(None))
            .all()
        )
        matched = next((row for row in candidates if verify_password(key_md5, row.secret_hash)), None)

    if matched is None:
        rate_limit.record(db, APP_AUTH_FAILURES_PER_IP, ip)
        rate_limit.record(db, APP_AUTH_FAILURES_PER_USER, username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or app password")

    rate_limit.clear(db, APP_AUTH_FAILURES_PER_USER, username)
    matched.last_used_at = utcnow()
    db.commit()
    return user


def authenticate_basic(db: Session, request: Request, username: str, app_password: str) -> User:
    """OPDS: HTTP Basic credentials, with the app password as the password."""
    return _authenticate(db, request, username, "opds", _md5_hex(app_password))


def authenticate_kosync(db: Session, request: Request, username: str, key: str) -> User:
    """kosync: ``x-auth-key`` is md5(app password), as KOReader sends it."""
    return _authenticate(db, request, username, "kosync", (key or "").strip().lower())

