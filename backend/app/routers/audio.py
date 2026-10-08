from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.schemas.audio import AudioJobCreate, AudioJobResponse, ProviderCapability, ProviderCheckRequest, ProviderPreviewRequest
from app.services.audio_job_service import ACTIVE_AUDIO_STATUSES, PROVIDER_CAPABILITIES, capability_for, delete_audio_job, queue_audio_job, speech_url
from config.database import get_db

router = APIRouter(prefix="/audio", tags=["audio"])


def _owned_job(db: Session, job_id: int, user: User) -> ChapterAudioJob:
    job = db.query(ChapterAudioJob).filter(ChapterAudioJob.id == job_id, ChapterAudioJob.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Audio job not found")
    return job


def _response(job: ChapterAudioJob) -> AudioJobResponse:
    return AudioJobResponse.model_validate({
        **{key: getattr(job, key) for key in AudioJobResponse.model_fields if hasattr(job, key)},
        "audio_ready": bool(job.audio_path and Path(job.audio_path).is_file()),
    })


@router.get("/providers", response_model=list[ProviderCapability])
def providers():
    return PROVIDER_CAPABILITIES


def _check_provider(request: ProviderCheckRequest, provider_id: str | None = None):
    capability = capability_for(provider_id or request.provider_id)
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            response = client.get(request.base_url.rstrip("/").removesuffix("/v1") + "/v1/models")
            response.raise_for_status()
        return {
            "status": "ready", "provider_id": capability["id"], "model": request.model,
            "voice": request.voice, "response_formats": capability.get("response_formats", ["wav"]),
            "safe_segment_size": capability["safe_segment_size"], "execution_mode": capability["execution_mode"],
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Audio provider is unavailable: {exc}") from exc


def _preview_provider(request: ProviderPreviewRequest, provider_id: str | None = None):
    capability = capability_for(provider_id or request.provider_id)
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = client.post(speech_url(request.base_url), json={"model": request.model, "voice": request.voice, "input": request.text, "response_format": "wav", **({"lang_code": request.language_code} if request.language_code else {})})
            response.raise_for_status()
        if not response.content.startswith(b"RIFF"):
            raise HTTPException(status_code=422, detail="Audio provider returned data that is not a WAV preview")
        return {"status": "ready", "provider_id": capability["id"], "bytes": len(response.content), "response_format": "wav"}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Audio preview failed: {exc}") from exc


@router.post("/providers/check")
def check_provider(request: ProviderCheckRequest, current_user: User = Depends(get_current_user)):
    return _check_provider(request)


@router.post("/providers/{provider_id}/check")
def check_named_provider(provider_id: str, request: ProviderCheckRequest, current_user: User = Depends(get_current_user)):
    return _check_provider(request, provider_id)


@router.post("/providers/preview")
def preview_provider(request: ProviderPreviewRequest, current_user: User = Depends(get_current_user)):
    return _preview_provider(request)


@router.post("/providers/{provider_id}/preview")
def preview_named_provider(provider_id: str, request: ProviderPreviewRequest, current_user: User = Depends(get_current_user)):
    return _preview_provider(request, provider_id)


@router.post("/jobs", response_model=AudioJobResponse, status_code=202)
def create_job(request: AudioJobCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if request.provider.execution_mode != "server":
        raise HTTPException(status_code=409, detail="This provider is browser-local; start it from the reader instead.")
    library = db.query(Library).filter(Library.id == request.library_id, Library.user_id == current_user.id).first()
    novel = db.query(Novel).filter(Novel.id == request.novel_id, Novel.library_id == request.library_id).first()
    chapter = db.query(Chapter).filter(Chapter.novel_id == request.novel_id, Chapter.chapter_number == request.chapter_number).first()
    if not library or not novel or not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        job = queue_audio_job(db, user_id=current_user.id, library_id=library.id, novel_id=novel.id, chapter=chapter, provider=request.provider.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(job)


@router.get("/jobs", response_model=list[AudioJobResponse])
def list_jobs(chapter_id: int | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(ChapterAudioJob).filter(ChapterAudioJob.user_id == current_user.id)
    if chapter_id is not None:
        query = query.filter(ChapterAudioJob.chapter_id == chapter_id)
    return [_response(job) for job in query.order_by(ChapterAudioJob.updated_at.desc()).limit(50).all()]


@router.get("/jobs/{job_id}", response_model=AudioJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _response(_owned_job(db, job_id, current_user))


@router.post("/jobs/{job_id}/retry", response_model=AudioJobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    if job.status not in {"failed", "cancelled", "retry_wait"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled audio jobs can be retried")
    job.status, job.error, job.error_code, job.finished_at = "queued", None, None, None
    db.commit(); db.refresh(job)
    return _response(job)


@router.post("/jobs/{job_id}/cancel", response_model=AudioJobResponse)
def cancel_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    if job.status not in ACTIVE_AUDIO_STATUSES:
        raise HTTPException(status_code=409, detail="Audio job is not active")
    from datetime import datetime
    job.status, job.cancelled_at = "cancelled", datetime.utcnow()
    db.commit(); db.refresh(job)
    return _response(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    try:
        delete_audio_job(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/audio")
def job_audio(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_job(db, job_id, current_user)
    if not job.audio_path or not Path(job.audio_path).is_file():
        raise HTTPException(status_code=404, detail="Final chapter audio is not ready")
    return FileResponse(job.audio_path, media_type="audio/wav", filename=f"chapter-{job.chapter_id}.wav")
