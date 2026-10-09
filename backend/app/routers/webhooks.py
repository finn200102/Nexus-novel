# routers/webhooks.py
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.webhook import Webhook
from app.schemas.webhook import WebhookCreateRequest, WebhookItem, WebhookTestResult, WebhookUpdateRequest
from app.services.notification_crypto import encrypt_url, url_hint
from app.services.outbound_url import BlockedDestination, check_public_url
from app.services.webhook_delivery import WEBHOOK_EVENT_TYPES, send_test
from config.database import get_db

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    responses={404: {"description": "Not found"}},
)

MAX_WEBHOOKS_PER_USER = 20


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _validated_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _unprocessable("Webhook URL must be an http or https URL")
    try:
        check_public_url(url)
    except BlockedDestination as exc:
        raise _unprocessable(str(exc)) from exc
    return url


def _validated_events(event_types: list[str]) -> list[str]:
    unknown = sorted(set(event_types) - set(WEBHOOK_EVENT_TYPES))
    if unknown:
        raise _unprocessable(f"Unknown event type: {unknown[0]}")
    return sorted(set(event_types))


def _webhook_or_404(db: Session, webhook_id: int, user: User) -> Webhook:
    hook = db.query(Webhook).filter(Webhook.id == webhook_id, Webhook.user_id == user.id).first()
    if hook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return hook


def _item(hook: Webhook) -> dict:
    return {
        "id": hook.id,
        "url_hint": hook.url_hint,
        "has_secret": bool(hook.secret_encrypted),
        "event_types": list(hook.event_types or []),
        "enabled": hook.enabled,
        "last_status_code": hook.last_status_code,
        "last_error": hook.last_error,
        "last_delivered_at": hook.last_delivered_at,
        "consecutive_failures": hook.consecutive_failures or 0,
        "created_at": hook.created_at,
    }


@router.get("", response_model=list[WebhookItem])
def list_webhooks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(Webhook).filter(Webhook.user_id == current_user.id).order_by(Webhook.id.asc()).all()
    return [_item(row) for row in rows]


@router.post("", response_model=WebhookItem, status_code=status.HTTP_201_CREATED)
def create_webhook(
    payload: WebhookCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = db.query(Webhook).filter(Webhook.user_id == current_user.id).count()
    if count >= MAX_WEBHOOKS_PER_USER:
        raise _unprocessable(f"At most {MAX_WEBHOOKS_PER_USER} webhooks per account")
    url = _validated_url(payload.url)
    secret = (payload.secret or "").strip()
    hook = Webhook(
        user_id=current_user.id,
        url_encrypted=encrypt_url(url),
        url_hint=url_hint(url),
        secret_encrypted=encrypt_url(secret) if secret else None,
        event_types=_validated_events(payload.event_types),
        enabled=payload.enabled,
        consecutive_failures=0,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    return _item(hook)


@router.patch("/{webhook_id}", response_model=WebhookItem)
def update_webhook(
    webhook_id: int,
    payload: WebhookUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hook = _webhook_or_404(db, webhook_id, current_user)
    if payload.url is not None:
        url = _validated_url(payload.url)
        hook.url_encrypted = encrypt_url(url)
        hook.url_hint = url_hint(url)
    if payload.clear_secret:
        hook.secret_encrypted = None
    elif payload.secret is not None:
        secret = payload.secret.strip()
        hook.secret_encrypted = encrypt_url(secret) if secret else None
    if payload.event_types is not None:
        hook.event_types = _validated_events(payload.event_types)
    if payload.enabled is not None:
        hook.enabled = payload.enabled
        if payload.enabled:
            # Re-enabling starts a fresh failure count.
            hook.consecutive_failures = 0
    db.commit()
    db.refresh(hook)
    return _item(hook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(webhook_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    hook = _webhook_or_404(db, webhook_id, current_user)
    db.delete(hook)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test", response_model=WebhookTestResult)
def test_webhook(webhook_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    hook = _webhook_or_404(db, webhook_id, current_user)
    return send_test(db, hook)
