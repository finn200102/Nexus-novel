from __future__ import annotations

from pathlib import Path

import httpx
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter, ContentStatus
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.schemas.audio import AudioManifestResponse, AudioJobCreate, AudioJobResponse, ProviderCapability, ProviderCheckRequest, ProviderPreviewRequest
from app.schemas.audio import StoryAudioCreate, StoryAudioResponse, StoryAudioBatchResponse,StoryAudioRecordingPage
from app.services.audio_job_service import ACTIVE_AUDIO_STATUSES, PROVIDER_CAPABILITIES, capability_for, delete_audio_job, queue_audio_job, speech_url
from config.database import get_db

router = APIRouter(prefix="/audio", tags=["audio"])


def _server_provider(db, user, snapshot, voice_profile_id):
    """Share single/batch policy; never infer a remote fallback for a clone."""
    if snapshot is not None and snapshot.execution_mode != "server":
        raise HTTPException(409, "Use browser generation in the story’s Audio tab for this provider.")
    if voice_profile_id is not None:
        from app.services.voice_service import owned_ready, bridge_config, MODEL
        try:
            profile = owned_ready(db, voice_profile_id, user.id)
            url, _ = bridge_config()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"id": "qwen3_clone", "base_url": url + "/v1", "model": MODEL,
                "voice": profile.name, "language_code": profile.language}
    if snapshot is None or snapshot.id == "qwen3_clone":
        raise HTTPException(422, "Choose one of your ready narrator voices")
    provider = snapshot.model_dump()
    provider["base_url"] = provider["base_url"].rstrip("/")
    return provider


def _owned_story(db: Session, novel_id: int, user: User) -> Novel:
    novel = db.query(Novel).join(Library, Novel.library_id == Library.id).filter(
        Novel.id == novel_id, Library.user_id == user.id).first()
    if not novel:
        raise HTTPException(404, "Story not found")
    return novel


@router.get("/stories/{novel_id}", response_model=StoryAudioResponse)
def story_audio(novel_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                from_chapter: int | None = Query(None, ge=-2147483648, le=2147483647),
                to_chapter: int | None = Query(None, ge=-2147483648, le=2147483647),
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    novel = _owned_story(db, novel_id, current_user)
    if from_chapter is not None and to_chapter is not None and from_chapter > to_chapter:
        raise HTTPException(422, 'Choose a chapter range in ascending order.')
    selected = [Chapter.novel_id == novel.id, Chapter.archived.is_(False)]
    if from_chapter is not None:
        selected.append(Chapter.chapter_number >= from_chapter)
    if to_chapter is not None:
        selected.append(Chapter.chapter_number <= to_chapter)
    query = db.query(Chapter).filter(*selected)
    from app.services.chapter_identity_service import manifest_state
    current_manifest = manifest_state(db, novel.id)
    total = query.count()
    downloaded = query.filter(Chapter.content_status == ContentStatus.PRESENT).count()
    latest = db.query(ChapterAudioJob.id.label("id"), func.row_number().over(
        partition_by=ChapterAudioJob.chapter_id,
        order_by=(case((ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES), 1), else_=0).desc(),
                  ChapterAudioJob.updated_at.desc().nullslast(), ChapterAudioJob.id.desc())).label("rank")).join(
        Chapter, Chapter.id == ChapterAudioJob.chapter_id).filter(
        *selected, ChapterAudioJob.user_id == current_user.id, ChapterAudioJob.novel_id == novel.id,
        ChapterAudioJob.library_id == novel.library_id, ChapterAudioJob.chapter_key == Chapter.chapter_key,
        ChapterAudioJob.manifest_epoch == current_manifest.manifest_epoch,ChapterAudioJob.identity_inferred.is_(False)).subquery()
    jobs = db.query(ChapterAudioJob).join(latest, latest.c.id == ChapterAudioJob.id).filter(latest.c.rank == 1).all()
    by_chapter = {job.chapter_id: job for job in jobs}
    summary = {"chapters": total, "downloaded": downloaded, "ready": 0, "queued": 0, "needs_retry": 0}
    for job in jobs:
        if job.status == "completed" and _response(job).audio_ready:
            summary["ready"] += 1
        elif job.status in ACTIVE_AUDIO_STATUSES:
            summary["queued"] += 1
        elif job.status in {"failed", "cancelled"}:
            summary["needs_retry"] += 1
    from app.services.chapter_version_service import document_for
    from app.services.chapter_identity_service import identity
    chapters = []
    for chapter in query.order_by(Chapter.chapter_number, Chapter.id).offset(offset).limit(limit).all():
        available = chapter.content_status == ContentStatus.PRESENT
        document = document_for(chapter) if available else None
        job = by_chapter.get(chapter.id)
        chapters.append({**identity(chapter), "id": chapter.id, "chapter_number": chapter.chapter_number, "title": chapter.title,
            "content_status": chapter.content_status.value, "downloaded": available,
            "source_version": document.get("content_version") if document else None,
            "latest_job": _response(job) if job else None})
    return {"novel_id": novel.id, "total": total, "offset": offset, "limit": limit, "summary": summary, "chapters": chapters}


@router.post("/stories/{novel_id}/jobs", response_model=StoryAudioBatchResponse, status_code=202, response_model_exclude_unset=True)
def create_story_audio(novel_id: int, request: StoryAudioCreate, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    novel = _owned_story(db, novel_id, current_user)
    from app.services.chapter_version_service import document_for
    provider = _server_provider(db, current_user, request.provider, request.voice_profile_id)
    from app.services.pronunciation_service import snapshot as pronunciation_snapshot
    pronunciation = pronunciation_snapshot(db, current_user.id, novel.id)
    identities = {item.chapter_number: item.model_dump(exclude={"chapter_number"}) for item in (request.chapter_identities or [])}
    outcomes = []
    for number in request.chapter_numbers:
        chapter = db.query(Chapter).filter_by(novel_id=novel.id, chapter_number=number).first()
        if not chapter or chapter.content_status != ContentStatus.PRESENT or not document_for(chapter).get("plain_text", "").strip():
            outcomes.append({"chapter_number": number, "outcome": "unavailable", "job": None})
            continue
        from app.services.audio_identity_service import capture
        captured=capture(db, current_user.id, chapter, identities.get(number))
        jobs = db.query(ChapterAudioJob).filter_by(user_id=current_user.id, chapter_id=chapter.id, chapter_key=chapter.chapter_key,
            manifest_epoch=captured['manifest_epoch'],identity_inferred=False)
        active = jobs.filter(ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES)).order_by(ChapterAudioJob.id.desc()).first()
        if active:
            outcomes.append({"chapter_number": number, "outcome": "already_queued", "job": _response(active)})
            continue
        version = document_for(chapter)["content_version"]
        matching = jobs.filter_by(source_version=version, voice_profile_id=request.voice_profile_id,
            include_author_notes=request.include_author_notes, provider_id=provider["id"], pronunciation_version=pronunciation["effective_version"])
        if request.voice_profile_id is None:
            matching = matching.filter(func.rtrim(ChapterAudioJob.provider_url, "/") == provider["base_url"],
                ChapterAudioJob.provider_model == provider["model"], ChapterAudioJob.provider_voice == provider["voice"],
                ChapterAudioJob.provider_language == provider.get("language_code"))
        matching = matching.order_by(ChapterAudioJob.updated_at.desc().nullslast(), ChapterAudioJob.id.desc()).all()
        completed = next((job for job in matching if job.status == "completed" and _response(job).audio_ready), None)
        needs_retry = next((job for job in matching if job.status in {"failed", "cancelled"}), None)
        if completed or needs_retry:
            job = completed or needs_retry
            outcomes.append({"chapter_number": number, "outcome": "already_ready" if completed else "needs_retry", "job": _response(job)})
            continue
        try:
            job = queue_audio_job(db, user_id=current_user.id, library_id=novel.library_id, novel_id=novel.id,
                chapter=chapter, provider=provider, voice_profile_id=request.voice_profile_id, include_author_notes=request.include_author_notes, pronunciation=pronunciation, identity_expectations=identities.get(number))
        except ValueError as exc:
            from app.services.pronunciation_service import AudioPlanningLimitError
            db.rollback()
            outcomes.append({"chapter_number": number, "outcome": "unavailable", "job": None,
                **({"error_code": "audio_planning_limit", "message": str(exc)} if isinstance(exc, AudioPlanningLimitError) else {})})
            continue
        outcomes.append({"chapter_number": number, "outcome": "queued", "job": _response(job)})
    return {"novel_id": novel.id, "outcomes": outcomes}


def _owned_job(db: Session, job_id: int, user: User) -> ChapterAudioJob:
    job = db.query(ChapterAudioJob).filter(ChapterAudioJob.id == job_id, ChapterAudioJob.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Audio job not found")
    return job


def _response(job: ChapterAudioJob) -> AudioJobResponse:
    from app.services.audio_identity_service import fields
    from sqlalchemy.orm import object_session
    db = object_session(job)
    return AudioJobResponse.model_validate({
        **{key: getattr(job, key) for key in AudioJobResponse.model_fields if hasattr(job, key)},
        **(fields(db, job) if db else {}),
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
    library = db.query(Library).filter(Library.id == request.library_id, Library.user_id == current_user.id).first()
    novel = db.query(Novel).filter(Novel.id == request.novel_id, Novel.library_id == request.library_id).first()
    chapter = db.query(Chapter).filter(Chapter.novel_id == request.novel_id, Chapter.chapter_number == request.chapter_number).first()
    if not library or not novel or not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    provider = _server_provider(db, current_user, request.provider, request.voice_profile_id)
    try:
        job = queue_audio_job(db, user_id=current_user.id, library_id=library.id, novel_id=novel.id, chapter=chapter, provider=provider, voice_profile_id=request.voice_profile_id, include_author_notes=request.include_author_notes, identity_expectations=request.model_dump(include={"expected_chapter_key", "expected_manifest_epoch", "expected_manifest_revision", "expected_content_version"}))
    except ValueError as exc:
        from app.services.pronunciation_service import AudioPlanningLimitError
        detail = {"code": "audio_planning_limit", "message": str(exc)} if isinstance(exc, AudioPlanningLimitError) else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    return _response(job)


@router.get("/jobs", response_model=list[AudioJobResponse])
def list_jobs(chapter_id: int | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(ChapterAudioJob).filter(ChapterAudioJob.user_id == current_user.id)
    if chapter_id is not None:
        query = query.filter(ChapterAudioJob.chapter_id == chapter_id)
    return [_response(job) for job in query.order_by(ChapterAudioJob.updated_at.desc()).limit(50).all()]


@router.get('/stories/{novel_id}/recordings',response_model=StoryAudioRecordingPage)
def saved_recordings(novel_id:int,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),
                     db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _owned_story(db,novel_id,current_user)
    query=db.query(ChapterAudioJob).filter_by(user_id=current_user.id,novel_id=novel_id)
    return dict(total=query.count(),offset=offset,limit=limit,
        items=[_response(job) for job in query.order_by(ChapterAudioJob.created_at.desc(),ChapterAudioJob.id.desc()).offset(offset).limit(limit)])


@router.get("/jobs/{job_id}", response_model=AudioJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _response(_owned_job(db, job_id, current_user))


@router.post("/jobs/{job_id}/retry", response_model=AudioJobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(User.id).filter_by(id=current_user.id).with_for_update().first()
    job = db.query(ChapterAudioJob).filter_by(id=job_id, user_id=current_user.id).populate_existing().with_for_update().first()
    if job is None:
        raise HTTPException(404, "Audio job not found")
    from app.services.audio_identity_service import require_dispatch
    require_dispatch(db, job)
    if job.status not in {"failed", "cancelled", "retry_wait"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled audio jobs can be retried")
    if job.provider_id == "qwen3_clone":
        from app.services.voice_service import owned_ready
        try:
            owned_ready(db, job.voice_profile_id, current_user.id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    another = db.query(ChapterAudioJob.id).filter(ChapterAudioJob.user_id == current_user.id,
        ChapterAudioJob.chapter_id == job.chapter_id, ChapterAudioJob.id != job.id,
        ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES)).first()
    if another:
        raise HTTPException(409, "Another narration for this chapter is already queued")
    job.status, job.error, job.error_code, job.finished_at = "queued", None, None, None
    job.next_attempt_at, job.cancelled_at = None, None
    job.lease_owner, job.lease_expires_at = None, None
    job.attempt_count = 0
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Another narration for this chapter is already queued") from None
    db.refresh(job)
    return _response(job)


@router.post("/jobs/{job_id}/cancel", response_model=AudioJobResponse)
def cancel_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(User.id).filter_by(id=current_user.id).with_for_update().first()
    job = db.query(ChapterAudioJob).filter_by(id=job_id, user_id=current_user.id).populate_existing().with_for_update().first()
    if job is None:
        raise HTTPException(404, "Audio job not found")
    if job.status not in ACTIVE_AUDIO_STATUSES:
        raise HTTPException(status_code=409, detail="Audio job is not active")
    from datetime import datetime
    job.status, job.cancelled_at = "cancelled", datetime.utcnow()
    job.lease_owner = job.lease_expires_at = None
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
    return FileResponse(job.audio_path, media_type="audio/wav", filename=f"chapter-{job.chapter_id}.wav", headers={"Cache-Control": "private, no-store"})


@router.get("/jobs/{job_id}/manifest", response_model=AudioManifestResponse)
def audio_manifest(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.audio_alignment import manifest
    return manifest(db, _owned_job(db, job_id, current_user))
