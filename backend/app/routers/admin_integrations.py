from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import require_admin
from app.models.user import User
from app.services import metadata_client

router = APIRouter(prefix="/admin/integrations", tags=["admin-integrations"])


async def metadata_admin(method: str, path: str, payload: dict | None = None):
    try:
        return await metadata_client.admin_request(method, path, json=payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Nexus Server administrator service is unavailable") from exc


class MergeDecision(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class WebhookWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_url: str = Field(min_length=8, max_length=1200)
    secret: str = Field(min_length=16, max_length=512)
    event_types: list[str] = Field(min_length=1)
    enabled: bool = True


class RotateWebhookSecret(BaseModel):
    secret: str = Field(min_length=16, max_length=512)


@router.get("/merge-reviews")
async def list_merge_reviews(_: User = Depends(require_admin)):
    return await metadata_admin("GET", "/merge-review/")


@router.get("/merge-reviews/{review_id}")
async def get_merge_review(review_id: int, _: User = Depends(require_admin)):
    return await metadata_admin("GET", f"/merge-review/{review_id}")


@router.post("/merge-reviews/{review_id}/{action}")
async def decide_merge_review(review_id: int, action: str, payload: MergeDecision, _: User = Depends(require_admin)):
    if action not in {"approve", "reject", "revert"}:
        raise HTTPException(status_code=404, detail="Unknown merge-review action")
    return await metadata_admin("POST", f"/merge-review/{review_id}/{action}", payload.model_dump())


@router.get("/webhooks")
async def list_webhooks(_: User = Depends(require_admin)):
    return await metadata_admin("GET", "/webhooks")


@router.post("/webhooks")
async def create_webhook(payload: WebhookWrite, _: User = Depends(require_admin)):
    return await metadata_admin("POST", "/webhooks", payload.model_dump())


@router.delete("/webhooks/{subscription_id}")
async def delete_webhook(subscription_id: str, _: User = Depends(require_admin)):
    return await metadata_admin("DELETE", f"/webhooks/{subscription_id}")


@router.post("/webhooks/{subscription_id}/rotate-secret")
async def rotate_webhook_secret(subscription_id: str, payload: RotateWebhookSecret, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/webhooks/{subscription_id}/rotate-secret", payload.model_dump())


@router.post("/webhooks/{subscription_id}/test")
async def test_webhook(subscription_id: str, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/webhooks/{subscription_id}/test")


@router.get("/webhooks/{subscription_id}/history")
async def webhook_history(subscription_id: str, _: User = Depends(require_admin)):
    return await metadata_admin("GET", f"/webhooks/{subscription_id}/history")
