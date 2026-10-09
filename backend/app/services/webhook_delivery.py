"""Outgoing webhooks for released update events.

Runs in the novel worker after push and Apprise delivery. A released event
(``notified_at`` set by the push path) is posted once to each enabled webhook
that subscribes to its type and was created after the webhook. A receipt row
is written before the request is sent, so an event is never posted twice to
the same endpoint, even when the worker restarts. Failed posts are not
retried; after ``MAX_CONSECUTIVE_FAILURES`` in a row the webhook is disabled.

Each request is signed: ``X-Nexus-Signature: sha256=<hex HMAC-SHA256 of the
body>`` using the webhook's secret, when it has one.
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent
from app.models.webhook import Webhook, WebhookDelivery
from app.services.notification_crypto import decrypt_url
from app.services.outbound_url import BlockedDestination, check_public_url, public_http_transport

logger = logging.getLogger(__name__)

WEBHOOK_EVENT_TYPES = ("new_chapters", "source_failed", "resumed")
WEBHOOK_TIMEOUT_SECONDS = 10
MAX_CONSECUTIVE_FAILURES = 10
BATCH_PER_WEBHOOK = 20
USER_AGENT = "Nexus-Webhook/1"


def _iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def build_payload(event: NovelUpdateEvent, novel: Novel) -> dict:
    count = event.chapter_count or 0
    return {
        "event": event.event_type,
        "story": {
            "title": novel.title,
            "url": novel.url or novel.source_url,
            "site": novel.novel_site or novel.site,
        },
        "chapters": {
            "count": count,
            "first": event.first_chapter_number if count else None,
            "last": event.last_chapter_number if count else None,
        },
        "created_at": _iso(event.created_at),
    }


def sign(body: bytes, secret: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if secret:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={digest}"
    return headers


def post_webhook(hook: Webhook, payload: dict) -> tuple[int | None, str | None]:
    """POST the payload. Returns ``(status_code, error)``; error is None on 2xx."""
    url = decrypt_url(hook.url_encrypted)
    secret = decrypt_url(hook.secret_encrypted) if hook.secret_encrypted else None
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    try:
        check_public_url(url)
        with httpx.Client(transport=public_http_transport(), timeout=WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(url, content=body, headers=sign(body, secret))
    except BlockedDestination as exc:
        return None, str(exc)[:255]
    except httpx.HTTPError as exc:
        return None, type(exc).__name__[:255]
    if 200 <= response.status_code < 300:
        return response.status_code, None
    return response.status_code, f"HTTP {response.status_code}"


def _record(db: Session, hook: Webhook, status_code: int | None, error: str | None) -> None:
    hook.last_status_code = status_code
    hook.last_error = error
    hook.last_delivered_at = datetime.now(UTC).replace(tzinfo=None)
    if error is None:
        hook.consecutive_failures = 0
    else:
        hook.consecutive_failures = (hook.consecutive_failures or 0) + 1
        if hook.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            hook.enabled = False
            logger.warning("Webhook %s disabled after %s failures", hook.id, hook.consecutive_failures)


def send_test(db: Session, hook: Webhook) -> dict:
    """Post a sample payload now. Works even when the webhook is disabled."""
    payload = {
        "event": "test",
        "story": {"title": "Test story", "url": None, "site": None},
        "chapters": {"count": 0, "first": None, "last": None},
        "created_at": _iso(datetime.now(UTC).replace(tzinfo=None)),
    }
    status_code, error = post_webhook(hook, payload)
    _record(db, hook, status_code, error)
    db.commit()
    return {"ok": error is None, "status_code": status_code, "error": error}


def deliver_due_webhooks(db: Session) -> int:
    """Post released events to enabled webhooks. Returns the number of attempts."""
    attempts = 0
    for hook in db.query(Webhook).filter(Webhook.enabled.is_(True)).order_by(Webhook.id.asc()).all():
        pending = (
            db.query(NovelUpdateEvent, Novel)
            .join(Novel, Novel.id == NovelUpdateEvent.novel_id)
            .filter(
                NovelUpdateEvent.user_id == hook.user_id,
                NovelUpdateEvent.notified_at.isnot(None),
                NovelUpdateEvent.created_at >= hook.created_at,
                NovelUpdateEvent.event_type.in_(list(hook.event_types or [])),
                ~exists().where(
                    WebhookDelivery.webhook_id == hook.id,
                    WebhookDelivery.event_id == NovelUpdateEvent.id,
                ),
            )
            .order_by(NovelUpdateEvent.id.asc())
            .limit(BATCH_PER_WEBHOOK)
            .all()
        )
        for event, novel in pending:
            if not hook.enabled:
                break
            # Claim the (webhook, event) pair first; a concurrent worker loses here.
            try:
                receipt = WebhookDelivery(webhook_id=hook.id, event_id=event.id)
                db.add(receipt)
                db.commit()
            except IntegrityError:
                db.rollback()
                continue
            status_code, error = post_webhook(hook, build_payload(event, novel))
            attempts += 1
            receipt.status_code = status_code
            receipt.error = error
            _record(db, hook, status_code, error)
            db.commit()
    return attempts
