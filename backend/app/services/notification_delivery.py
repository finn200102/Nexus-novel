"""Push and Apprise delivery for update notifications.

Runs in the novel worker. Each update event is claimed (``notified_at`` set
with a conditional update) before anything is sent, so an event is delivered
at most once even if the worker restarts or two workers overlap. A failed
send is recorded on the subscription or channel; it is not retried.

Story events are grouped per story. Events from digest policies are grouped
into one digest per account.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from config.settings import settings
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.notification import NotificationChannel, PushSubscription
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services.notification_crypto import decrypt_url

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
WEBPUSH_TIMEOUT_SECONDS = 10
APPRISE_TIMEOUT_SECONDS = 10
WEBPUSH_TTL_SECONDS = 6 * 60 * 60
# Push services answer these when a subscription is gone for good.
GONE_STATUSES = {404, 410}
DIGEST_POLICIES = {"daily_digest", "weekly_digest"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def send_web_push(subscription: PushSubscription, payload: dict) -> None:
    """Send one Web Push message. Raises WebPushException on failure."""
    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=json.dumps(payload),
        vapid_private_key=settings.VAPID_PRIVATE_KEY,
        vapid_claims={"sub": settings.VAPID_SUBJECT},
        timeout=WEBPUSH_TIMEOUT_SECONDS,
        ttl=WEBPUSH_TTL_SECONDS,
    )


def instantiate_apprise(url: str):
    """Build the notification plugin for a URL without fetching anything.

    ``Apprise.add`` would treat an http(s) URL as a remote config file and
    download it; instantiating the plugin directly never makes that request.
    """
    import apprise

    asset = apprise.AppriseAsset(service_timeout=APPRISE_TIMEOUT_SECONDS)
    return apprise.Apprise.instantiate(url, asset=asset, suppress_exceptions=True)


def send_apprise(url: str, title: str, body: str) -> bool:
    """Send through one Apprise URL. Returns False when delivery failed."""
    import apprise

    plugin = instantiate_apprise(url)
    if plugin is None:
        return False
    client = apprise.Apprise()
    client.add(plugin)
    return bool(client.notify(title=title, body=body))


@dataclass
class Message:
    title: str
    body: str
    url: str
    tag: str


@dataclass
class DeliveryReport:
    events: int = 0
    messages: int = 0
    push_sent: int = 0
    push_failed: int = 0
    push_removed: int = 0
    channels_sent: int = 0
    channels_failed: int = 0


def _chapters_text(total: int, first: int | None, last: int | None) -> str:
    noun = "chapter" if total == 1 else "chapters"
    if first is not None and last is not None:
        return f"{total} new {noun} ({first}–{last})"
    return f"{total} new {noun}"


def _story_message(novel: Novel, events: list[NovelUpdateEvent]) -> Message:
    total = sum(event.chapter_count or 0 for event in events)
    numbers = [n for event in events for n in (event.first_chapter_number, event.last_chapter_number) if n is not None]
    if total:
        body = _chapters_text(total, min(numbers) if numbers else None, max(numbers) if numbers else None)
    else:
        body = events[-1].message or "Update"
    return Message(
        title=novel.title,
        body=body,
        url=f"/library/{novel.library_id}/novels/{novel.id}",
        tag=f"novel-{novel.id}",
    )


def _digest_message(stories: list[tuple[str, int]]) -> Message:
    count = len(stories)
    lines = [f"{title}: {chapters} new" for title, chapters in stories[:10]]
    if count > 10:
        lines.append(f"and {count - 10} more")
    return Message(
        title=f"{count} {'story' if count == 1 else 'stories'} updated",
        body="\n".join(lines),
        url="/activity",
        tag="nexus-digest",
    )


def build_messages(db: Session, events: list[NovelUpdateEvent]) -> dict[int, list[Message]]:
    """Return the messages each user should receive for the claimed events."""
    if not events:
        return {}
    keys = {(event.user_id, event.novel_id) for event in events}
    follows = {
        (follow.user_id, follow.novel_id): follow
        for follow in db.query(UserNovelFollow).filter(
            UserNovelFollow.user_id.in_({key[0] for key in keys}),
            UserNovelFollow.novel_id.in_({key[1] for key in keys}),
        )
    }
    novels = {novel.id: novel for novel in db.query(Novel).filter(Novel.id.in_({key[1] for key in keys}))}

    by_story: dict[tuple[int, int], list[NovelUpdateEvent]] = {}
    digest_by_user: dict[int, dict[int, list[NovelUpdateEvent]]] = {}
    for event in events:
        follow = follows.get((event.user_id, event.novel_id))
        novel = novels.get(event.novel_id)
        if novel is None:
            continue
        if follow is not None and follow.notification_policy in DIGEST_POLICIES:
            digest_by_user.setdefault(event.user_id, {}).setdefault(event.novel_id, []).append(event)
        else:
            by_story.setdefault((event.user_id, event.novel_id), []).append(event)

    messages: dict[int, list[Message]] = {}
    for (user_id, novel_id), story_events in by_story.items():
        messages.setdefault(user_id, []).append(_story_message(novels[novel_id], story_events))
    for user_id, stories in digest_by_user.items():
        rows = []
        for novel_id, story_events in stories.items():
            rows.append((novels[novel_id].title, sum(event.chapter_count or 0 for event in story_events) or len(story_events)))
        messages.setdefault(user_id, []).append(_digest_message(rows))
    return messages


def _send_push(db: Session, subscriptions: list[PushSubscription], message: Message, report: DeliveryReport) -> None:
    payload = {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag}
    for subscription in list(subscriptions):
        try:
            send_web_push(subscription, payload)
        except WebPushException as exc:
            status = getattr(exc, "status_code", None) or (exc.response.status_code if exc.response is not None else None)
            if status in GONE_STATUSES:
                db.delete(subscription)
                report.push_removed += 1
                logger.info("Removed push subscription %s after HTTP %s", subscription.id, status)
            else:
                subscription.failure_count = (subscription.failure_count or 0) + 1
                report.push_failed += 1
                logger.warning("Push subscription %s failed with HTTP %s", subscription.id, status)
            continue
        except Exception:
            subscription.failure_count = (subscription.failure_count or 0) + 1
            report.push_failed += 1
            logger.exception("Push subscription %s failed", subscription.id)
            continue
        subscription.last_success_at = _now()
        subscription.failure_count = 0
        report.push_sent += 1


def _send_channel(channel: NotificationChannel, title: str, body: str) -> str | None:
    """Send through one channel. Returns None on success, else a short reason."""
    try:
        delivered = send_apprise(decrypt_url(channel.url_encrypted), title, body)
    except Exception:
        # Apprise errors can echo the URL; log only the channel id.
        logger.exception("Apprise channel %s raised an error", channel.id)
        return "Delivery raised an error"
    return None if delivered else "Delivery failed"


def deliver_due_notifications(db: Session, limit: int = BATCH_SIZE) -> DeliveryReport:
    """Claim and send visible update events that have not been delivered yet."""
    report = DeliveryReport()
    candidate_ids = [
        row.id
        for row in db.query(NovelUpdateEvent.id)
        .filter(NovelUpdateEvent.notification_visible.is_(True), NovelUpdateEvent.notified_at.is_(None))
        .order_by(NovelUpdateEvent.created_at.asc(), NovelUpdateEvent.id.asc())
        .limit(limit)
        .all()
    ]
    now = _now()
    claimed = []
    for event_id in candidate_ids:
        updated = (
            db.query(NovelUpdateEvent)
            .filter(NovelUpdateEvent.id == event_id, NovelUpdateEvent.notified_at.is_(None))
            .update({NovelUpdateEvent.notified_at: now}, synchronize_session=False)
        )
        if updated:
            claimed.append(event_id)
    db.commit()
    if not claimed:
        return report
    events = db.query(NovelUpdateEvent).filter(NovelUpdateEvent.id.in_(claimed)).all()
    report.events = len(events)

    messages = build_messages(db, events)
    for user_id, user_messages in messages.items():
        subscriptions = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        channels = (
            db.query(NotificationChannel)
            .filter(NotificationChannel.user_id == user_id, NotificationChannel.enabled.is_(True))
            .all()
        )
        for message in user_messages:
            report.messages += 1
            _send_push(db, subscriptions, message, report)
            for channel in channels:
                error = _send_channel(channel, message.title, message.body)
                channel.last_error = error
                if error:
                    report.channels_failed += 1
                else:
                    report.channels_sent += 1
        db.commit()
    return report


def send_test(db: Session, user: User) -> dict:
    """Send a test message to every enabled channel and push device of a user."""
    title = "Nexus Novel test"
    body = "If you can read this, notifications reach this device."
    payload = {"title": title, "body": body, "url": "/notifications", "tag": "nexus-test"}

    channel_results = []
    channels = (
        db.query(NotificationChannel)
        .filter(NotificationChannel.user_id == user.id, NotificationChannel.enabled.is_(True))
        .order_by(NotificationChannel.id.asc())
        .all()
    )
    for channel in channels:
        error = _send_channel(channel, title, body)
        channel.last_error = error
        channel_results.append({"id": channel.id, "label": channel.label, "url_hint": channel.url_hint, "ok": error is None, "error": error})

    report = DeliveryReport()
    subscriptions = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).all()
    for subscription in list(subscriptions):
        _send_push(db, [subscription], Message(title, body, payload["url"], payload["tag"]), report)
    db.commit()
    return {
        "channels": channel_results,
        "push": {"sent": report.push_sent, "failed": report.push_failed, "removed": report.push_removed},
    }
