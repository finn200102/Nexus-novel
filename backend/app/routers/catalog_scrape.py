from __future__ import annotations

import re
from dataclasses import dataclass
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from config.database import get_db
from app.auth.dependencies import get_current_auth, Authenticated
from app.models.user import User
from app.models.account import UserSession
from app.services import metadata_client
from app.schemas.catalog_scrape import CatalogActiveJobsResponse, CatalogCapabilitiesResponse, CatalogCapabilityResponse, CatalogPreviewResponse, CatalogDefinitionResponse, CatalogCreateResponse, CatalogJobResponse, CatalogCandidateResponse, CatalogDeleteResponse, CatalogTaxonomyResponse, CatalogTemplateResponse, CatalogRequest, CreateCatalogRequest, UpdateCatalogRequest, CatalogControlRequest, CatalogRebindRequest, CatalogCandidateUpdate

router = APIRouter(prefix="/catalog-scrapes", tags=["catalog-scrapes"])
PRIVATE = {"Cache-Control": "private, no-store"}

@dataclass
class CatalogAdministrator:
    user_id: int
    storage_id: str
    session_id: int
    db: Session

def administrator(response: Response, db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    if not auth.user.is_admin:
        raise HTTPException(403, detail="Administrator access required", headers=PRIVATE)
    context = CatalogAdministrator(auth.user.id, auth.user.storage_id, auth.session.id, db)
    db.commit()
    response.headers.update(PRIVATE)
    return context

def reauthorize(context):
    db = context.db
    db.expire_all()
    user, session = db.get(User, context.user_id), db.get(UserSession, context.session_id)
    valid = bool(user and user.is_admin and not user.is_disabled and user.storage_id == context.storage_id
        and session and session.user_id == context.user_id and session.revoked_at is None)
    db.commit()
    if not valid:
        raise HTTPException(403, detail="Administrator access changed. Sign in again.", headers=PRIVATE)

async def _request(method: str, path: str, *, json: dict | None = None, params: dict | None = None):
    timeout = httpx.Timeout(15.0 if path == "/catalog-scrapes/preview" else 30.0, connect=3.0)
    try:
        response = await metadata_client._request(method, path, timeout=timeout, admin=True, json=json, params=params)
        return response.json() if response.content else None
    except (RuntimeError, ValueError) as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.TimeoutException):
            raise HTTPException(504, detail={"code":"catalog_timeout", "message":"The source did not respond in time. Review source health and retry later."}, headers=PRIVATE) from exc
        if isinstance(cause, httpx.HTTPStatusError):
            status = cause.response.status_code
            try:
                detail = cause.response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            code = detail.get("code") if isinstance(detail, dict) else None
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                code = "catalog_settings_rejected" if status == 422 else "catalog_state_changed" if status == 409 else "catalog_operation_failed"
            message = {404:"This catalog job or source is no longer available.",409:"The job, source package, or reviewed criteria changed. Refresh and preview again.",422:"These settings are not supported. Review the source capabilities and preview again.",429:"The source request budget is exhausted. Wait before retrying."}.get(status,"The catalog service could not complete this administrator operation.")
            message = {"run_active":"Cancel active catalog runs and pending imports before editing, rebinding, or deleting this definition.", "review_required":"Preview and save this job’s source criteria before running or resuming it.", "definition_paused":"Resume the reviewed definition before running it.", "rebind_required":"The installed package changed. Review its new version and explicitly rebind this job.", "definition_changed":"Another administrator changed this job. Refresh and review the current settings.", "review_changed":"The preview expired or its criteria changed. Preview the current settings again."}.get(code,message)
            raise HTTPException(status if 400 <= status < 600 else 502, detail={"code":code,"message":message}, headers=PRIVATE) from exc
        raise HTTPException(503, detail={"code":"catalog_unavailable","message":"The catalog service is unavailable. Your saved jobs are retained."}, headers=PRIVATE) from exc

async def forward(context, method, path, **kwargs):
    # Release the initial DB snapshot before I/O, then recheck authority even
    # when the upstream response is an error. Never expose a revoked admin view.
    await run_in_threadpool(reauthorize, context)
    try:
        result = await _request(method, path, **kwargs)
    except Exception:
        await run_in_threadpool(reauthorize, context)
        raise
    await run_in_threadpool(reauthorize, context)
    return result


@router.get("/capabilities", response_model=CatalogCapabilitiesResponse, response_model_exclude_unset=True)
async def capabilities(admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", "/catalog-scrapes/capabilities")


@router.get("/capabilities/{site}", response_model=CatalogCapabilityResponse, response_model_exclude_unset=True)
async def source_capabilities(site: str, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", f"/catalog-scrapes/capabilities/{site}")


@router.post("/preview", response_model=CatalogPreviewResponse, response_model_exclude_unset=True)
async def preview(request: CatalogRequest, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", "/catalog-scrapes/preview", json=request.model_dump())


@router.post("", response_model=CatalogCreateResponse, response_model_exclude_unset=True)
async def create(request: CreateCatalogRequest, admin: CatalogAdministrator = Depends(administrator)):
    payload = request.model_dump(exclude_unset=True)
    payload["created_by"] = admin.storage_id
    return await forward(admin, "POST", "/catalog-scrapes", json=payload)


@router.get("", response_model=list[CatalogDefinitionResponse], response_model_exclude_unset=True)
async def list_jobs(admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", "/catalog-scrapes")


@router.get("/templates", response_model=list[CatalogTemplateResponse], response_model_exclude_unset=True)
async def templates(site: str | None = Query(None, max_length=80), admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", "/catalog-scrapes/templates", params={"site":site})


@router.get("/{definition_id}", response_model=CatalogDefinitionResponse, response_model_exclude_unset=True)
async def get_definition(definition_id: int, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", f"/catalog-scrapes/{definition_id}")


@router.patch("/{definition_id}", response_model=CatalogDefinitionResponse, response_model_exclude_unset=True)
async def update_definition(definition_id: int, request: UpdateCatalogRequest, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "PATCH", f"/catalog-scrapes/{definition_id}", json=request.model_dump(exclude_unset=True))


@router.post("/{definition_id}/pause", response_model=CatalogDefinitionResponse, response_model_exclude_unset=True)
async def pause_definition(definition_id: int, request: CatalogControlRequest | None = None, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/{definition_id}/pause", **({"json":request.model_dump(exclude_unset=True)} if request else {}))


@router.post("/{definition_id}/resume", response_model=CatalogDefinitionResponse, response_model_exclude_unset=True)
async def resume_definition(definition_id: int, request: CatalogControlRequest | None = None, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/{definition_id}/resume", **({"json":request.model_dump(exclude_unset=True)} if request else {}))


@router.delete("/{definition_id}", response_model=CatalogDeleteResponse, response_model_exclude_unset=True)
async def delete_definition(definition_id: int, request: CatalogControlRequest | None = None, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "DELETE", f"/catalog-scrapes/{definition_id}", **({"json":request.model_dump(exclude_unset=True)} if request else {}))


@router.post("/{definition_id}/run", response_model=CatalogJobResponse, response_model_exclude_unset=True)
async def run_definition(definition_id: int, request: CatalogControlRequest | None = None, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/{definition_id}/run", **({"json":request.model_dump(exclude_unset=True)} if request else {}))


@router.get("/jobs/{job_id}", response_model=CatalogJobResponse, response_model_exclude_unset=True)
async def get_job(job_id: str, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", f"/catalog-scrapes/jobs/{job_id}")


@router.get("/jobs/{job_id}/candidates", response_model=list[CatalogCandidateResponse], response_model_exclude_unset=True)
async def get_candidates(job_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", f"/catalog-scrapes/jobs/{job_id}/candidates", params={"limit": limit, "offset": offset})


@router.post("/jobs/{job_id}/retry", response_model=CatalogJobResponse, response_model_exclude_unset=True)
async def retry_job(job_id: str, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/jobs/{job_id}/retry")


@router.post("/jobs/{job_id}/cancel", response_model=CatalogJobResponse, response_model_exclude_unset=True)
async def cancel_job(job_id: str, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/jobs/{job_id}/cancel")


@router.get("/taxonomies/{site}/{taxonomy_type}", response_model=list[CatalogTaxonomyResponse], response_model_exclude_unset=True)
async def taxonomies(
    site: str,
    taxonomy_type: str,
    query: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: CatalogAdministrator = Depends(administrator),
):
    return await forward(admin,
        "GET",
        f"/catalog-scrapes/taxonomies/{site}/{taxonomy_type}",
        params={"query": query, "limit": limit, "offset": offset},
    )


@router.post("/{definition_id}/rebind", response_model=CatalogDefinitionResponse, response_model_exclude_unset=True)
async def rebind(definition_id: int, request: CatalogRebindRequest, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "POST", f"/catalog-scrapes/{definition_id}/rebind", json=request.model_dump())

@router.patch("/jobs/{job_id}/candidates/{candidate_id}", response_model=CatalogCandidateResponse, response_model_exclude_unset=True)
async def update_candidate(job_id: str, candidate_id: int, request: CatalogCandidateUpdate, admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "PATCH", f"/catalog-scrapes/jobs/{job_id}/candidates/{candidate_id}", json=request.model_dump())

@router.get("/{definition_id}/active-jobs", response_model=CatalogActiveJobsResponse, response_model_exclude_unset=True)
async def active_jobs(definition_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), admin: CatalogAdministrator = Depends(administrator)):
    return await forward(admin, "GET", f"/catalog-scrapes/{definition_id}/active-jobs", params={"offset":offset,"limit":limit})
