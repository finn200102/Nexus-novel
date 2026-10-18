"""Durable notification outbox with per-destination leases and bounded retries.

A transport may accept a message before a worker crashes. Recovery can resend
that same stable-tag payload; exactly-once external delivery is not promised.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4
import hashlib
from itertools import chain
from sqlalchemy import or_, and_
from app.models.notification_delivery import NotificationDelivery

from pywebpush import WebPushException, webpush

from app.services.outbound_url import check_public_url
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
    check_public_url(subscription.endpoint)
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
    check_public_url(url)
    client = apprise.Apprise()
    client.add(plugin)
    return bool(client.notify(title=title, body=body))


@dataclass
class Message:
    title: str
    body: str
    url: str
    tag: str
    event_ids: list[int] | None = None


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
        event_ids=[event.id for event in events],
    )


def _new_work_message(event: NovelUpdateEvent) -> Message:
    details = event.details or {}
    metadata_id = details.get("metadata_id")
    return Message(
        title=details.get("title") or "New work",
        body=event.message or "New work",
        url=f"/story/{metadata_id}" if metadata_id else "/updates",
        tag=f"new-work-{event.id}",
        event_ids=[event.id],
    )


def _digest_message(stories: list[tuple[str, int]], event_ids=None) -> Message:
    count = len(stories)
    lines = [f"{title}: {chapters} new" for title, chapters in stories[:10]]
    if count > 10:
        lines.append(f"and {count - 10} more")
    return Message(
        title=f"{count} {'story' if count == 1 else 'stories'} updated",
        body="\n".join(lines),
        url="/activity",
        tag="nexus-digest",
        event_ids=event_ids,
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
    messages: dict[int, list[Message]] = {}
    for event in events:
        if event.novel_id is None:
            # A new work by a followed author or in a followed series.
            if event.event_type in ("author_new_work", "series_new_work", "catalog_match"):
                messages.setdefault(event.user_id, []).append(_new_work_message(event))
            continue
        follow = follows.get((event.user_id, event.novel_id))
        novel = novels.get(event.novel_id)
        if novel is None:
            continue
        if follow is not None and follow.notification_policy in DIGEST_POLICIES:
            digest_by_user.setdefault(event.user_id, {}).setdefault(event.novel_id, []).append(event)
        else:
            by_story.setdefault((event.user_id, event.novel_id), []).append(event)

    for (user_id, novel_id), story_events in by_story.items():
        messages.setdefault(user_id, []).append(_story_message(novels[novel_id], story_events))
    for user_id, stories in digest_by_user.items():
        rows = []
        for novel_id, story_events in stories.items():
            rows.append((novels[novel_id].title, sum(event.chapter_count or 0 for event in story_events) or len(story_events)))
        messages.setdefault(user_id, []).append(_digest_message(rows,[event.id for story_events in stories.values() for event in story_events]))
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
            logger.warning("Push subscription %s failed", subscription.id)
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
        logger.warning("Apprise channel %s raised an error", channel.id)
        return "Delivery raised an error"
    return None if delivered else "Delivery failed"


LEASE_SECONDS=60
MAX_ATTEMPTS=5


def destination_fingerprint(kind,destination):
    values=[kind,destination.id,destination.user_id,str(destination.created_at),destination.delivery_key,destination.eligibility_event_id]
    if kind=='push':values.extend([destination.endpoint,destination.p256dh,destination.auth])
    else:values.extend([destination.kind,destination.url_encrypted])
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def destination_watermark(db,user_id):
    from sqlalchemy import func
    return db.query(func.max(NovelUpdateEvent.id)).filter_by(user_id=user_id).scalar() or 0


def cancel_destination_deliveries(db,user_id,kind,destination_id):
    """Call in the same transaction as a destination disable/edit/delete."""
    return db.query(NotificationDelivery).filter_by(user_id=user_id,destination_kind=kind,destination_id=destination_id).filter(
        NotificationDelivery.status.in_(['queued','retry_wait','processing'])).update(
        {'status':'cancelled','finished_at':_now(),'lease_owner':None,'lease_expires_at':None,'next_attempt_at':None,
         'last_error_code':'destination_changed'},synchronize_session=False)


def snapshot_due_notifications(db,limit=BATCH_SIZE):
    """Commit immutable bounded payloads and closure of source events together.

    Legacy notified_at rows stay closed: their prior transport outcome cannot
    be reconstructed honestly. No new destinations are attached on retries.
    """
    limit=max(1,min(int(limit),BATCH_SIZE))
    candidates=db.query(NovelUpdateEvent.id,NovelUpdateEvent.user_id).filter(NovelUpdateEvent.notification_visible.is_(True),NovelUpdateEvent.notified_at.is_(None)).order_by(
        NovelUpdateEvent.created_at,NovelUpdateEvent.id).limit(limit).all()
    # Same lock order as account deletion and destination changes. Lock users
    # before event rows/FK inserts, never hold the reverse cascade order.
    if candidates:
        db.query(User.id).filter(User.id.in_({row.user_id for row in candidates})).order_by(User.id).with_for_update().all()
    events=db.query(NovelUpdateEvent).filter(NovelUpdateEvent.id.in_([row.id for row in candidates]),NovelUpdateEvent.notified_at.is_(None),
        NovelUpdateEvent.notification_visible.is_(True)).order_by(NovelUpdateEvent.created_at,NovelUpdateEvent.id).with_for_update(skip_locked=True).all()
    now=_now();claimed=[]
    for event in events:
        if db.query(NovelUpdateEvent).filter_by(id=event.id,notified_at=None).update({'notified_at':now},synchronize_session=False):claimed.append(event)
    messages=build_messages(db,claimed)
    prepared_count=0
    for user_id in sorted(messages):
        account=db.query(User).filter_by(id=user_id,is_disabled=False).first()
        if account is None:continue
        account_events=[event for event in claimed if event.user_id==user_id]
        targets=chain((('push',row) for row in db.query(PushSubscription).filter_by(user_id=user_id).order_by(PushSubscription.id).yield_per(50)),
            (('channel',row) for row in db.query(NotificationChannel).filter_by(user_id=user_id,enabled=True).order_by(NotificationChannel.id).yield_per(50)))
        for kind,target in targets:
            # A newly installed destination does not receive the old backlog.
            eligible=[event for event in account_events if event.created_at is not None and target.created_at is not None and event.created_at>=target.created_at and event.id>(target.eligibility_event_id or 0)]
            for message in build_messages(db,eligible).get(user_id,[]):
                db.add(NotificationDelivery(user_id=user_id,account_key=account.storage_id,delivery_key=str(uuid4()),
                    destination_kind=kind,destination_id=target.id,destination_fingerprint=destination_fingerprint(kind,target),
                    payload={'title':message.title[:200],'body':message.body[:4000],'url':message.url[:500],'tag':message.tag[:200]},
                    event_ids=message.event_ids or [event.id for event in eligible],status='queued',attempt_count=0,next_attempt_at=now))
                prepared_count+=1
                if prepared_count%50==0:db.flush()
    db.commit()
    return len(claimed),sum(len(rows) for rows in messages.values())


def claim_delivery(db):
    """One atomic lease; a committed claim survives process death."""
    now=_now()
    due=or_(and_(NotificationDelivery.status.in_(['queued','retry_wait']),or_(NotificationDelivery.next_attempt_at.is_(None),NotificationDelivery.next_attempt_at<=now)),
        and_(NotificationDelivery.status=='processing',NotificationDelivery.lease_expires_at<=now))
    # A crashed final attempt is conservatively paused, never discarded as sent.
    db.query(NotificationDelivery).filter(due,NotificationDelivery.attempt_count>=MAX_ATTEMPTS).update(
        {'status':'paused','last_error_code':'retry_exhausted','lease_owner':None,'lease_expires_at':None,'next_attempt_at':None},synchronize_session=False)
    candidate=db.query(NotificationDelivery.id).filter(due,NotificationDelivery.attempt_count<MAX_ATTEMPTS).order_by(
        NotificationDelivery.created_at,NotificationDelivery.id).with_for_update(skip_locked=True).first()
    if candidate is None:db.commit();return None
    token=str(uuid4())
    changed=db.query(NotificationDelivery).filter(NotificationDelivery.id==candidate.id,due,NotificationDelivery.attempt_count<MAX_ATTEMPTS).update(
        {'status':'processing','lease_owner':token,'lease_expires_at':now+timedelta(seconds=LEASE_SECONDS),
         'attempt_count':NotificationDelivery.attempt_count+1,'next_attempt_at':None},synchronize_session=False)
    db.commit()
    return (candidate.id,token) if changed else None


def catalog_event_is_deliverable(db,account,event):
    # Fail closed during source development/partial installation. The watch
    # engine owns visibility, immutable search binding, and blocklist policy.
    try:
        from app.services.catalog_watch_service import event_is_deliverable
    except ImportError:
        return False
    return event_is_deliverable(db,account,event)


def process_delivery(db,delivery_id,token,report=None):
    """Recheck account/destination under short bounded-dispatch row locks.

    A deletion/revocation waits for an already-authorized transport operation;
    after its commit no subsequent attempt can start. No secrets enter payloads.
    """
    report=report or DeliveryReport()
    identity=db.query(NotificationDelivery.user_id).filter_by(id=delivery_id).scalar()
    if identity is None:db.rollback();return report
    account=db.query(User).filter_by(id=identity).with_for_update().populate_existing().first()
    row=db.query(NotificationDelivery).filter_by(id=delivery_id,status='processing',lease_owner=token).with_for_update().populate_existing().first()
    if row is None:db.rollback();return report
    target_type=PushSubscription if row.destination_kind=='push' else NotificationChannel
    target=db.query(target_type).filter_by(id=row.destination_id,user_id=row.user_id).with_for_update().populate_existing().first()
    allowed=account is not None and not account.is_disabled and account.storage_id==row.account_key and target is not None
    if allowed and row.destination_kind=='channel':allowed=target.enabled
    if allowed:allowed=destination_fingerprint(row.destination_kind,target)==row.destination_fingerprint
    if allowed:
        source_events=db.query(NovelUpdateEvent).filter(NovelUpdateEvent.user_id==row.user_id,NovelUpdateEvent.id.in_(row.event_ids)).populate_existing().all()
        allowed=len(source_events)==len(row.event_ids)
        for source in source_events:
            if source.event_type=='catalog_match':
                if not catalog_event_is_deliverable(db,account,source):allowed=False
    if not allowed:
        row.status='cancelled';row.last_error_code='destination_unavailable';row.finished_at=_now()
    elif row.lease_expires_at is None or row.lease_expires_at<=_now():
        row.status='paused' if row.attempt_count>=MAX_ATTEMPTS else 'retry_wait'
        row.last_error_code='lease_expired';row.next_attempt_at=_now() if row.status=='retry_wait' else None
    else:
        error=None;gone=False
        if row.destination_kind=='push':
            try:send_web_push(target,dict(row.payload))
            except WebPushException as exc:
                status=getattr(exc,'status_code',None) or (exc.response.status_code if exc.response is not None else None)
                gone=status in GONE_STATUSES;error='destination_gone' if gone else 'transport_failed'
            except Exception:error='transport_failed'
            if gone:
                db.delete(target);report.push_removed+=1
            elif error:
                target.failure_count=(target.failure_count or 0)+1;report.push_failed+=1
            else:
                target.last_success_at=_now();target.failure_count=0;report.push_sent+=1
        else:
            reason=_send_channel(target,row.payload['title'],row.payload['body'])
            target.last_error=reason
            error='transport_failed' if reason else None
            if error:report.channels_failed+=1
            else:report.channels_sent+=1
        row.last_error_code=error
        if error:
            row.status='paused' if gone or row.attempt_count>=MAX_ATTEMPTS else 'retry_wait'
            row.next_attempt_at=_now()+timedelta(seconds=min(3600,30*2**(row.attempt_count-1))) if row.status=='retry_wait' else None
        else:row.status='succeeded';row.finished_at=_now()
    row.lease_owner=None;row.lease_expires_at=None
    db.commit()
    return report


def deliver_due_notifications(db: Session, limit: int = BATCH_SIZE) -> DeliveryReport:
    report=DeliveryReport()
    report.events,report.messages=snapshot_due_notifications(db,limit)
    for _ in range(max(1,min(int(limit),BATCH_SIZE))):
        claimed=claim_delivery(db)
        if claimed is None:break
        process_delivery(db,*claimed,report)
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
