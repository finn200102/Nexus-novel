"""Account-private narrator management, never shared through story references."""
import base64
import binascii
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.audio_job import ChapterAudioJob
from app.models.user import User
from app.models.voice_profile import VoiceProfile
from app.models.reader_preference import ReaderPreference
from app.services.voice_service import MODEL, QWEN_NATIVE_MODEL, QWEN_MODELS, FISH_MODELS, LANGUAGES, MAX_UPLOAD, bridge_config
from config.database import get_db

router = APIRouter(prefix="/audio/voices", tags=["narrator voices"])


class VoiceUpload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    audio_base64: str = Field(min_length=4, max_length=MAX_UPLOAD * 4 // 3 + 4)
    transcript: str = Field(default="", max_length=4000)
    language: str = "English"
    engine: str = Field(default="qwen", pattern="^(qwen|fish)$")
    excerpt_start_seconds: float | None = Field(default=None, ge=0, le=3600, allow_inf_nan=False)
    excerpt_duration_seconds: float | None = Field(default=None, ge=3, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def paired_excerpt(self):
        if (self.excerpt_start_seconds is None) != (self.excerpt_duration_seconds is None):
            raise ValueError("Choose both the excerpt start and its duration")
        return self


class VoiceView(BaseModel):
    id: int
    name: str
    language: str
    status: str
    transcript: str
    error: str | None
    preview_ready: bool
    model: str = MODEL
    created_at: datetime | None


class DefaultVoiceWrite(BaseModel):
    voice_profile_id: int | None = Field(default=None, gt=0)
    expected_revision: int = Field(ge=0)


def default_view(row):
    return {"voice_profile_id": (row.values or {}).get("voice_profile_id") if row else None,
            "revision": row.revision if row else 0}


@router.get("/default")
def default_voice(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope="audio").first()
    return default_view(row)


@router.put("/default")
def choose_default(request: DefaultVoiceWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(User).filter_by(id=user.id).with_for_update().first()
    if request.voice_profile_id is not None:
        profile = owned(db, user, request.voice_profile_id)
        if profile.status != "completed":
            raise HTTPException(409, "Wait for this narrator to finish preparing")
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope="audio").first()
    current = default_view(row)
    if current["voice_profile_id"] == request.voice_profile_id:
        return current
    if current["revision"] != request.expected_revision:
        raise HTTPException(409, detail={"message": "The default narrator changed on another device.", "current": current})
    if row is None:
        row = ReaderPreference(user_id=user.id, scope="audio", revision=0, values={})
        db.add(row)
    row.values = {"voice_profile_id": request.voice_profile_id}
    row.revision += 1
    db.commit()
    return default_view(row)


def view(profile):
    return VoiceView(model=profile.model, id=profile.id, name=profile.name, language=profile.language, status=profile.status,
                     transcript=profile.transcript, error=profile.error, preview_ready=bool(profile.preview), created_at=profile.created_at)


def owned(db, user, profile_id):
    profile = db.query(VoiceProfile).filter_by(id=profile_id, user_id=user.id).first()
    if not profile:
        raise HTTPException(404, "Narrator voice not found")
    return profile


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    try:
        bridge_config(); configured = True
    except ValueError:
        configured = False
    try:
        bridge_config(fish=True); fish_configured = True
    except ValueError:
        fish_configured = False
    return {"configured": configured or fish_configured, "model": QWEN_NATIVE_MODEL if os.getenv("NEXUS_MANAGED_SPEECH") == "1" else MODEL, "languages": LANGUAGES, "max_upload_bytes": MAX_UPLOAD,
            "transcript_required": os.getenv("NEXUS_MANAGED_SPEECH") == "1",
            "engines": [{"id": "qwen", "label": "Qwen3 TTS", "configured": configured},
                        {"id": "fish", "label": "Fish Audio", "configured": fish_configured}]}


@router.get("", response_model=list[VoiceView])
def list_voices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Listing must not materialize every private reference/preview into RAM.
    rows = db.query(VoiceProfile.id, VoiceProfile.model, VoiceProfile.name, VoiceProfile.language, VoiceProfile.status,
        VoiceProfile.transcript, VoiceProfile.error, VoiceProfile.created_at,
        VoiceProfile.preview.isnot(None).label("preview_ready")).filter(VoiceProfile.user_id == user.id).order_by(VoiceProfile.created_at.desc()).all()
    return [VoiceView(**dict(row._mapping)) for row in rows]


@router.post("", response_model=VoiceView, status_code=202)
def upload(request: VoiceUpload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        bridge_config(fish=True) if request.engine == "fish" else bridge_config()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    if request.language not in LANGUAGES or not request.name.strip():
        raise HTTPException(422, "Choose a narrator name and a supported language")
    if db.query(VoiceProfile).filter_by(user_id=user.id).count() >= 20:
        raise HTTPException(409, "Remove an unused narrator before adding another (20 per account)")
    try:
        body = base64.b64decode(request.audio_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "Invalid audio encoding") from None
    if not body or len(body) > MAX_UPLOAD:
        raise HTTPException(413, "Upload an audio recording smaller than 12 MB")
    model = os.getenv("NEXUS_FISH_MODEL", "fishaudio/s2-pro") if request.engine == "fish" else QWEN_NATIVE_MODEL if os.getenv("NEXUS_MANAGED_SPEECH") == "1" else MODEL
    if model not in QWEN_MODELS and model not in FISH_MODELS:
        raise HTTPException(503, "Unsupported local Fish model")
    profile = VoiceProfile(user_id=user.id, name=request.name.strip(), language=request.language, sample=body,
                           transcript=request.transcript.strip(), model=model, status="queued",
                           excerpt_start_seconds=request.excerpt_start_seconds,
                           excerpt_duration_seconds=request.excerpt_duration_seconds)
    db.add(profile); db.commit(); db.refresh(profile)
    return view(profile)


@router.get("/{profile_id}/preview")
def preview(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = owned(db, user, profile_id)
    if not profile.preview:
        raise HTTPException(404, "Voice preview is not ready")
    return Response(profile.preview, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/{profile_id}/retry", response_model=VoiceView)
def retry(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = owned(db, user, profile_id)
    if profile.status not in {"failed", "retry_wait"}:
        raise HTTPException(409, "This voice is not waiting for a retry")
    profile.status, profile.error, profile.error_code = "queued", None, None
    profile.attempt_count, profile.next_attempt_at = 0, None
    db.commit(); db.refresh(profile)
    return view(profile)


@router.delete("/{profile_id}", status_code=204)
def delete(profile_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(User).filter_by(id=user.id).with_for_update().first()
    profile = owned(db, user, profile_id)
    preference = db.query(ReaderPreference).filter_by(user_id=user.id, scope="audio").first()
    if preference and (preference.values or {}).get("voice_profile_id") == profile.id:
        preference.values = {"voice_profile_id": None}
        preference.revision += 1
    db.query(ChapterAudioJob).filter(ChapterAudioJob.user_id == user.id, ChapterAudioJob.voice_profile_id == profile.id,
        ChapterAudioJob.status.in_(("queued", "processing", "retry_wait"))).update({"status": "cancelled", "lease_owner": None, "lease_expires_at": None}, synchronize_session=False)
    # Clear associations explicitly too: SQLite installations may not enable FK actions.
    db.query(ChapterAudioJob).filter(ChapterAudioJob.voice_profile_id == profile.id).update({"voice_profile_id": None}, synchronize_session=False)
    db.delete(profile); db.commit()
