from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config.settings import settings
from app.auth.dependencies import require_admin
from app.models.user import User

router = APIRouter(prefix="/catalog-scrapes", tags=["catalog-scrapes"])


class CatalogRequest(BaseModel):
    site: str = "fanfiction"
    query: dict


class CreateCatalogRequest(CatalogRequest):
    name: str = Field(min_length=1, max_length=255)
    schedule_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    enabled: bool = True


class UpdateCatalogRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    query: dict | None = None
    schedule_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    enabled: bool | None = None


async def _request(method: str, path: str, *, json: dict | None = None, params: dict | None = None):
    # Catalog previews touch an external source and must never hold the UI/API
    # open for the generic 120-second client timeout. The metadata service has
    # its own source timeout; this shorter gateway timeout gives the browser a
    # deterministic, actionable response when a source is blocked or degraded.
    timeout = 15.0 if path == "/catalog-scrapes/preview" else 30.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{settings.METADATA_SERVER_URL}{path}", json=json, params=params)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Metadata server timed out while contacting the source. Check source health and retry later.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Metadata server is unavailable. Check the metadata service and retry.") from exc
    if response.status_code >= 400:
        detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


@router.get("/capabilities")
async def capabilities(_: User = Depends(require_admin)):
    return await _request("GET", "/catalog-scrapes/capabilities")


@router.post("/preview")
async def preview(request: CatalogRequest, _: User = Depends(require_admin)):
    return await _request("POST", "/catalog-scrapes/preview", json=request.model_dump())


@router.post("")
async def create(request: CreateCatalogRequest, current_user: User = Depends(require_admin)):
    payload = request.model_dump()
    payload["created_by"] = current_user.username
    return await _request("POST", "/catalog-scrapes", json=payload)


@router.get("")
async def list_jobs(_: User = Depends(require_admin)):
    return await _request("GET", "/catalog-scrapes")


@router.get("/{definition_id}")
async def get_definition(definition_id: int, _: User = Depends(require_admin)):
    return await _request("GET", f"/catalog-scrapes/{definition_id}")


@router.patch("/{definition_id}")
async def update_definition(definition_id: int, request: UpdateCatalogRequest, _: User = Depends(require_admin)):
    return await _request("PATCH", f"/catalog-scrapes/{definition_id}", json=request.model_dump(exclude_none=True))


@router.post("/{definition_id}/pause")
async def pause_definition(definition_id: int, _: User = Depends(require_admin)):
    return await _request("POST", f"/catalog-scrapes/{definition_id}/pause")


@router.post("/{definition_id}/resume")
async def resume_definition(definition_id: int, _: User = Depends(require_admin)):
    return await _request("POST", f"/catalog-scrapes/{definition_id}/resume")


@router.delete("/{definition_id}")
async def delete_definition(definition_id: int, _: User = Depends(require_admin)):
    return await _request("DELETE", f"/catalog-scrapes/{definition_id}")


@router.post("/{definition_id}/run")
async def run_definition(definition_id: int, _: User = Depends(require_admin)):
    return await _request("POST", f"/catalog-scrapes/{definition_id}/run")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, _: User = Depends(require_admin)):
    return await _request("GET", f"/catalog-scrapes/jobs/{job_id}")


@router.get("/jobs/{job_id}/candidates")
async def get_candidates(job_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), _: User = Depends(require_admin)):
    return await _request("GET", f"/catalog-scrapes/jobs/{job_id}/candidates", params={"limit": limit, "offset": offset})


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, _: User = Depends(require_admin)):
    return await _request("POST", f"/catalog-scrapes/jobs/{job_id}/retry")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, _: User = Depends(require_admin)):
    return await _request("POST", f"/catalog-scrapes/jobs/{job_id}/cancel")


@router.get("/taxonomies/{site}/{taxonomy_type}")
async def taxonomies(site: str, taxonomy_type: str, _: User = Depends(require_admin)):
    return await _request("GET", f"/catalog-scrapes/taxonomies/{site}/{taxonomy_type}")
