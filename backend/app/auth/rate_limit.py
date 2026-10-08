"""Database-backed attempt limits for sign-in, sign-up and password checks.

Attempts live in ``auth_attempts`` so limits survive restarts. Each check
counts the attempts for one key (for example ``login:user:alice``) inside a
sliding window.
"""

from dataclasses import dataclass
from datetime import timedelta
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.sessions import utcnow
from app.models.account import AuthAttempt

RETENTION = timedelta(days=1)


@dataclass(frozen=True)
class Limit:
    name: str
    max_attempts: int
    window: timedelta

    def key(self, value: str) -> str:
        return f"{self.name}:{value.strip().lower()[:200]}"


# Failed sign-ins per address and per account name. The per-account limit
# stops guessing one password from many addresses; the address limit is
# generous because a household may share one public address.
LOGIN_FAILURES_PER_IP = Limit("login:ip", 30, timedelta(minutes=15))
LOGIN_FAILURES_PER_USER = Limit("login:user", 10, timedelta(minutes=15))
# Every sign-up request, successful or not.
SIGNUPS_PER_IP = Limit("signup:ip", 10, timedelta(hours=1))
# Wrong current password when changing it.
PASSWORD_FAILURES_PER_USER = Limit("password:user", 10, timedelta(minutes=15))


def check(db: Session, limit: Limit, value: str) -> None:
    """Raise 429 when ``value`` has used up ``limit``."""
    now = utcnow()
    key = limit.key(value)
    count, oldest = (
        db.query(func.count(AuthAttempt.id), func.min(AuthAttempt.created_at))
        .filter(AuthAttempt.key == key, AuthAttempt.created_at > now - limit.window)
        .one()
    )
    if count >= limit.max_attempts:
        retry_after = max(1, ceil((oldest + limit.window - now).total_seconds())) if oldest else 60
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a few minutes and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def record(db: Session, limit: Limit, value: str) -> None:
    """Count one attempt and commit it, even if the request then fails."""
    now = utcnow()
    key = limit.key(value)
    db.query(AuthAttempt).filter(AuthAttempt.key == key, AuthAttempt.created_at < now - RETENTION).delete(
        synchronize_session=False
    )
    db.add(AuthAttempt(key=key, created_at=now, updated_at=now))
    db.commit()


def clear(db: Session, limit: Limit, value: str) -> None:
    db.query(AuthAttempt).filter(AuthAttempt.key == limit.key(value)).delete(synchronize_session=False)
