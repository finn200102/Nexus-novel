from __future__ import annotations

from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import require_admin
from app.models.user import User
from app.services import metadata_client

router = APIRouter(prefix="/admin/integrations", tags=["admin-integrations"])


class PluginPackage(BaseModel):
    data_base64: str = Field(max_length=11_000_000)
    enable: bool = True


class PluginAction(BaseModel):
    action: Literal["enable", "disable", "rollback", "test"]
    digest: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")


class PluginDiagnostic(BaseModel):
    url: str = Field(max_length=2000)
    operation: Literal["metadata", "manifest", "chapter"] = "metadata"


class RegistrySelection(BaseModel):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/plugins/registry")
async def plugin_registry(_: User = Depends(require_admin)):
    return await metadata_admin("GET", "/plugins/registry")


@router.post("/plugins/registry/{plugin_id}/{version}/preview")
async def registry_preview(plugin_id: str, version: str, payload: RegistrySelection, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/plugins/registry/{plugin_id}/{version}/preview", payload.model_dump())


@router.get("/plugins")
async def plugins(_: User = Depends(require_admin)):
    return await metadata_admin("GET", "/plugins")


@router.post("/plugins/{operation}")
async def plugin_package(operation: Literal["preview", "install"], payload: PluginPackage, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/plugins/{operation}", payload.model_dump())


@router.get("/plugins/{plugin_id}/versions")
async def plugin_versions(plugin_id: str, _: User = Depends(require_admin)):
    return await metadata_admin("GET", f"/plugins/{plugin_id}/versions")


@router.post("/plugins/{plugin_id}/actions")
async def plugin_action(plugin_id: str, payload: PluginAction, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/plugins/{plugin_id}/actions", payload.model_dump())


@router.post("/plugins/{plugin_id}/diagnostic")
async def plugin_diagnostic(plugin_id: str, payload: PluginDiagnostic, _: User = Depends(require_admin)):
    return await metadata_admin("POST", f"/plugins/{plugin_id}/diagnostic", payload.model_dump())


async def metadata_admin(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    try:
        return await metadata_client.admin_request(method, path, json=payload, params=params)
    except RuntimeError as exc:
        if isinstance(exc.__cause__, httpx.HTTPStatusError):
            response = exc.__cause__.response
            try:
                detail = response.json().get("detail", "Administrator operation failed")
            except (ValueError, AttributeError):
                detail = "Administrator operation failed"
            raise HTTPException(status_code=response.status_code, detail=detail) from exc
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


class GuideReviewDecision(BaseModel):
    review_state: str = Field(pattern="^(approved|machine_suggested|hidden)$")
    reason: str | None = Field(default=None, max_length=1000)


class GuideRestoreDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


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
    raise HTTPException(409, detail={'code':'reviewed_workflow_required',
        'message':'Legacy source-link reviews are read-only. Use reviewed edition grouping or the separate source migration preview.'})


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


@router.get("/story-guides/{novel_id}/review-queue")
async def story_guide_review_queue(novel_id: int, _: User = Depends(require_admin)):
    """Administrator-only editorial workbench feed; never used by reader pages."""
    return await metadata_admin("GET", f"/analysis/novels/{novel_id}/story-guide/review-queue")


@router.get("/story-guides/{novel_id}/review-history")
async def story_guide_review_history(novel_id: int, limit: int = 100, _: User = Depends(require_admin)):
    return await metadata_admin("GET", f"/analysis/novels/{novel_id}/story-guide/review-history", params={"limit": min(max(limit, 1), 500)})


@router.post("/story-guides/assertions/{assertion_id}/review")
async def review_story_guide_assertion(assertion_id: str, payload: GuideReviewDecision, _: User = Depends(require_admin)):
    return await metadata_admin(
        "POST",
        f"/analysis/story-guide/assertions/{assertion_id}/review",
        params=payload.model_dump(exclude_none=True),
    )


@router.post("/story-guides/assertions/{assertion_id}/restore")
async def restore_story_guide_assertion(assertion_id: str, payload: GuideRestoreDecision, _: User = Depends(require_admin)):
    return await metadata_admin(
        "POST",
        f"/analysis/story-guide/assertions/{assertion_id}/restore",
        params=payload.model_dump(exclude_none=True),
    )
