from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from config.database import get_db
from config.settings import settings
from app.auth.dependencies import get_current_user
from app.models.notification import NotificationChannel, PushSubscription
from app.models.user import User
from app.schemas.notification import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    PushSubscribeRequest,
    PushSubscriptionResponse,
    PushUnsubscribeRequest,
)
from app.services.notification_crypto import encrypt_url, url_hint
from app.services.notification_delivery import instantiate_apprise, send_test, cancel_destination_deliveries, destination_watermark
from app.services.outbound_url import BlockedDestination, check_public_url

def _lock_users(db,identities):
    identities=sorted(set(identities))
    db.query(User.id).filter(User.id.in_(identities)).order_by(User.id).with_for_update().all()
    return identities


def _reset_delivery_eligibility(db,user_id,kind,target):
    if target.id is not None:cancel_destination_deliveries(db,user_id,kind,target.id)
    if not target.delivery_key:target.delivery_key=str(uuid4())
    target.eligibility_event_id=destination_watermark(db,user_id)



router = APIRouter(prefix="/notifications", tags=["notifications"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _channel_or_404(db: Session, channel_id: int, user: User) -> NotificationChannel:
    channel = db.query(NotificationChannel).filter(
        NotificationChannel.id == channel_id,
        NotificationChannel.user_id == user.id,
    ).populate_existing().first()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification channel not found")
    return channel


def _validated_apprise_url(url: str) -> str:
    url = url.strip()
    # Only notification plugins are accepted; a bare URL that Apprise would
    # treat as a remote config file is refused.
    if instantiate_apprise(url) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Not a supported Apprise URL")
    try:
        check_public_url(url)
    except BlockedDestination as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return url


def _channel_response(channel: NotificationChannel) -> ChannelResponse:
    return ChannelResponse(
        id=channel.id,
        kind=channel.kind,
        label=channel.label or channel.url_hint,
        url_hint=channel.url_hint,
        enabled=channel.enabled,
        last_error=channel.last_error,
        created_at=channel.created_at,
    )


def _subscription_response(subscription: PushSubscription) -> PushSubscriptionResponse:
    return PushSubscriptionResponse(
        id=subscription.id,
        user_agent=subscription.user_agent,
        created_at=subscription.created_at,
        last_success_at=subscription.last_success_at,
        failure_count=subscription.failure_count or 0,
    )


@router.get("/vapid-public-key")
def vapid_public_key():
    """The public half of the Web Push key; safe to expose, needed to subscribe."""
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.get("/push/subscriptions", response_model=list[PushSubscriptionResponse])
def list_push_subscriptions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(PushSubscription).filter(PushSubscription.user_id == current_user.id).order_by(PushSubscription.id.asc()).all()
    return [_subscription_response(row) for row in rows]


@router.post("/push/subscriptions", response_model=PushSubscriptionResponse)
def subscribe_push(
    body: PushSubscribeRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    user_agent: str | None = Header(default=None),
):
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Push endpoints must use HTTPS")
    try:
        check_public_url(body.endpoint)
    except BlockedDestination as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    previous = db.query(PushSubscription).filter(PushSubscription.endpoint == body.endpoint).first()
    identities=_lock_users(db,[current_user.id]+([previous.user_id] if previous is not None else []))
    subscription=db.query(PushSubscription).filter(PushSubscription.endpoint==body.endpoint).with_for_update().populate_existing().first()
    if subscription is not None and subscription.user_id not in identities:
        raise HTTPException(409,detail='This device changed accounts; try subscribing again')
    if subscription is None:
        subscription = PushSubscription(endpoint=body.endpoint,user_id=current_user.id)
        response.status_code = status.HTTP_201_CREATED
        changed=True
    else:
        changed=(subscription.user_id!=current_user.id or subscription.p256dh!=body.keys.p256dh or subscription.auth!=body.keys.auth)
    if changed:
        if subscription.id is not None:cancel_destination_deliveries(db,subscription.user_id,'push',subscription.id)
        _reset_delivery_eligibility(db,current_user.id,'push',subscription)
    subscription.user_id = current_user.id
    subscription.p256dh = body.keys.p256dh
    subscription.auth = body.keys.auth
    subscription.user_agent = (user_agent or "")[:255] or None
    subscription.failure_count = 0
    db.add(subscription)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,detail='This device changed while subscribing; try again') from None
    db.refresh(subscription)
    return _subscription_response(subscription)


@router.post("/push/unsubscribe")
def unsubscribe_push(body: PushUnsubscribeRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _lock_users(db,[current_user.id])
    rows=db.query(PushSubscription).filter_by(endpoint=body.endpoint,user_id=current_user.id).all()
    for row in rows:
        cancel_destination_deliveries(db,current_user.id,'push',row.id)
        db.delete(row)
    removed=len(rows)
    db.commit()
    return {"removed": removed}


@router.delete("/push/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_subscription(subscription_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _lock_users(db,[current_user.id])
    subscription=db.query(PushSubscription).filter_by(id=subscription_id,user_id=current_user.id).first()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    cancel_destination_deliveries(db,current_user.id,'push',subscription_id)
    db.delete(subscription)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/channels", response_model=list[ChannelResponse])
def list_channels(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(NotificationChannel).filter(NotificationChannel.user_id == current_user.id).order_by(NotificationChannel.id.asc()).all()
    return [_channel_response(row) for row in rows]


@router.post("/channels", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
def create_channel(body: ChannelCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    url = _validated_apprise_url(body.url)
    _lock_users(db,[current_user.id])
    channel = NotificationChannel(
        user_id=current_user.id,
        kind="apprise",
        url_encrypted=encrypt_url(url),
        url_hint=url_hint(url),
        label=body.label.strip(),
        enabled=body.enabled,
    )
    _reset_delivery_eligibility(db,current_user.id,'channel',channel)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
def update_channel(channel_id: int, body: ChannelUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _lock_users(db,[current_user.id])
    channel = _channel_or_404(db, channel_id, current_user)
    changes = body.model_dump(exclude_unset=True)
    if changes.get('url') is not None or (changes.get('enabled') is not None and changes['enabled']!=channel.enabled):
        _reset_delivery_eligibility(db,current_user.id,'channel',channel)
    if changes.get("url") is not None:
        url = _validated_apprise_url(changes["url"])
        channel.url_encrypted = encrypt_url(url)
        channel.url_hint = url_hint(url)
        channel.last_error = None
    if changes.get("label") is not None:
        channel.label = changes["label"].strip()
    if changes.get("enabled") is not None:
        channel.enabled = changes["enabled"]
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(channel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _lock_users(db,[current_user.id])
    channel = _channel_or_404(db, channel_id, current_user)
    cancel_destination_deliveries(db,current_user.id,'channel',channel.id)
    db.delete(channel)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test")
def test_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Send a test to every enabled channel and device; returns each result."""
    _lock_users(db,[current_user.id])
    return send_test(db, current_user)
