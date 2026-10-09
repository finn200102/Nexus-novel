"""Personal Atom feed of a user's latest update events.

The feed URL carries a random secret token instead of a session, so feed
readers can poll it. Only ``sha256(token)`` is stored; rotating replaces the
row, which makes the old URL stop working at once. Invalid tokens are rate
limited per client address, like app passwords.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import rate_limit
from app.auth.sessions import client_ip, utcnow
from app.models.novel import Novel
from app.models.personal_feed import UserFeedToken
from app.models.update_event import NovelUpdateEvent
from app.models.user import User

FEED_ITEM_LIMIT = 50
INVALID_TOKENS_PER_IP = rate_limit.Limit("feed:ip", 30, timedelta(minutes=15))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_token_row(db: Session, user_id: int) -> UserFeedToken | None:
    return db.query(UserFeedToken).filter(UserFeedToken.user_id == user_id).first()


def rotate(db: Session, user: User) -> str:
    """Create or replace the user's feed token. Returns the token once."""
    token = secrets.token_urlsafe(32)
    row = get_token_row(db, user.id)
    if row is None:
        row = UserFeedToken(user_id=user.id, token_hash=_hash(token))
        db.add(row)
    else:
        row.token_hash = _hash(token)
        row.last_used_at = None
    db.commit()
    return token


def revoke(db: Session, user_id: int) -> bool:
    row = get_token_row(db, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def user_for_token(db: Session, request: Request, token: str) -> User:
    ip = client_ip(request)
    rate_limit.check(db, INVALID_TOKENS_PER_IP, ip)
    row = db.query(UserFeedToken).filter(UserFeedToken.token_hash == _hash(token)).first() if token else None
    user = db.query(User).filter(User.id == row.user_id).first() if row else None
    if user is None or user.is_disabled:
        rate_limit.record(db, INVALID_TOKENS_PER_IP, ip)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found")
    row.last_used_at = utcnow()
    db.commit()
    return user


def _stamp(value: datetime | None) -> str:
    value = value or utcnow()
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_title(story: str, event: NovelUpdateEvent) -> str:
    count = event.chapter_count or 0
    if count:
        noun = "chapter" if count == 1 else "chapters"
        return f"{story} — {count} new {noun}"
    return f"{story} — {event.message or 'Update'}"


def build_atom(db: Session, user: User, base_url: str, feed_url: str) -> str:
    """Render the user's latest update events as an Atom 1.0 document."""
    base = base_url.rstrip("/")
    rows = (
        db.query(NovelUpdateEvent, Novel)
        .join(Novel, Novel.id == NovelUpdateEvent.novel_id)
        .filter(NovelUpdateEvent.user_id == user.id)
        .order_by(NovelUpdateEvent.created_at.desc(), NovelUpdateEvent.id.desc())
        .limit(FEED_ITEM_LIMIT)
        .all()
    )
    updated = _stamp(rows[0][0].created_at) if rows else _stamp(None)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <id>urn:nexus:user:{user.id}:updates</id>",
        "  <title>Nexus updates</title>",
        f'  <link rel="self" href="{escape(feed_url)}"/>',
        f'  <link rel="alternate" href="{escape(base + "/")}"/>',
        f"  <updated>{updated}</updated>",
    ]
    for event, novel in rows:
        if novel.metadata_id is not None:
            link = f"{base}/story/{novel.metadata_id}"
        else:
            link = f"{base}/library/{novel.library_id}/novels/{novel.id}"
        story = novel.title or "Untitled"
        lines += [
            "  <entry>",
            f"    <id>urn:nexus:update:{event.id}</id>",
            f"    <title>{escape(_entry_title(story, event))}</title>",
            f'    <link rel="alternate" href="{escape(link)}"/>',
            f"    <updated>{_stamp(event.created_at)}</updated>",
            f"    <summary>{escape(event.message or '')}</summary>",
            "  </entry>",
        ]
    lines.append("</feed>")
    return "\n".join(lines) + "\n"
