"""Only the configured, authenticated local host receives private reference audio."""
import base64
import binascii
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.orm.exc import ObjectDeletedError

from app.models.voice_profile import VoiceProfile
from app.services.job_lease import claim, heartbeat, recover_expired, utcnow

MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"
LANGUAGES = ("English", "German", "Chinese", "Japanese", "Korean", "French", "Russian", "Portuguese", "Spanish", "Italian")
MAX_UPLOAD = 12 * 1024 * 1024
SAFE_REFERENCE_ERRORS = {
    "Audio could not be decoded. Try a WAV, MP3, M4A, Ogg or FLAC recording.",
    "Invalid audio recording",
    "Use a recording between 3 and 30 seconds; 5–15 seconds of clear speech works best.",
    "The selected excerpt contains less than 3 seconds of audio. Choose an earlier start or a longer excerpt.",
    "The recording is silent. Upload clear speech.",
    "No clear speech was detected. Enter the recording’s exact transcript and retry.",
}


def bridge_config():
    url = os.getenv("NEXUS_LOCAL_VOICE_URL", "").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "host.docker.internal", "local-tts"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Local voice cloning is not configured on this Nexus server.")
    try:
        key = Path(os.environ["NEXUS_LOCAL_VOICE_KEY_FILE"]).read_text().strip()
        if len(key) < 32:
            raise ValueError()
    except (OSError, KeyError, ValueError):
        raise ValueError("The local voice service key is unavailable.") from None
    return url, {"Authorization": "Bearer " + key}


def request_payload(profile, *, prepare=False, **extra):
    selection = {}
    if prepare and profile.excerpt_duration_seconds is not None:
        selection = {"excerpt_start_seconds": profile.excerpt_start_seconds,
                     "excerpt_duration_seconds": profile.excerpt_duration_seconds}
    return {"audio_base64": base64.b64encode(profile.sample).decode(), "transcript": profile.transcript,
            "language": profile.language, **selection, **extra}


def owned_ready(db, profile_id, user_id):
    profile = db.query(VoiceProfile).filter_by(id=profile_id, user_id=user_id).first()
    if not profile or profile.status != "completed":
        raise ValueError("Choose one of your ready narrator voices.")
    return profile


def prepare_voice(profile_id, session_factory):
    with session_factory() as db:
        profile = claim(db, VoiceProfile, profile_id)
        if not profile:
            return
        owner = profile.lease_owner
        try:
            url, headers = bridge_config()
            with heartbeat(session_factory, VoiceProfile, profile.id, owner), httpx.Client(timeout=httpx.Timeout(960, connect=5), trust_env=False) as client:
                response = client.post(url + "/v1/voices/prepare", json=request_payload(profile, prepare=True), headers=headers)
                response.raise_for_status()
                data = response.json()
            db.expire_all()
            current = db.get(VoiceProfile, profile_id)
            if not current or current.status != "processing" or current.lease_owner != owner:
                return
            sample = base64.b64decode(data["audio_base64"], validate=True)
            preview = base64.b64decode(data["preview_base64"], validate=True)
            transcript = data["transcript"]
            if (not sample.startswith(b"RIFF") or len(sample) > 1_500_000 or not preview.startswith(b"RIFF")
                    or len(preview) > 40_000_000 or not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 4000 or data.get("model") != MODEL):
                raise ValueError("Invalid response from the local voice service")
            current.sample, current.preview, current.transcript = sample, preview, transcript
            current.status, current.finished_at = "completed", utcnow()
            current.lease_owner, current.lease_expires_at = None, None
            db.commit()
        except (Exception, ObjectDeletedError) as exc:
            db.rollback()
            db.expire_all()
            current = db.get(VoiceProfile, profile_id)
            if not current or current.status != "processing" or current.lease_owner != owner:
                return
            # Never retain raw provider errors/URLs, input audio or generated transcript in logs.
            invalid = isinstance(exc, (ValueError, binascii.Error)) or isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (413, 422)
            current.error = "Use 3–30 seconds of clear speech. Check the exact transcript and try again." if invalid else "The local voice service could not finish. Check it is running and retry. Initial model downloads may take several minutes."
            if invalid and isinstance(exc, httpx.HTTPStatusError):
                try:
                    detail = exc.response.json().get("detail")
                    if isinstance(detail, str) and detail in SAFE_REFERENCE_ERRORS:
                        current.error = detail
                except (ValueError, AttributeError):
                    pass
            current.error_code = "invalid_reference" if invalid else "local_voice_unavailable"
            current.status = "failed" if invalid or current.attempt_count >= current.max_attempts else "retry_wait"
            current.next_attempt_at = utcnow() + timedelta(seconds=30 * 2 ** (current.attempt_count - 1))
            current.lease_owner, current.lease_expires_at = None, None
            db.commit()


def process_due_voices(session_factory):
    with session_factory() as db:
        recover_expired(db, VoiceProfile)
        profile = db.query(VoiceProfile).filter(VoiceProfile.status.in_(("queued", "retry_wait")),
            or_(VoiceProfile.next_attempt_at.is_(None), VoiceProfile.next_attempt_at <= utcnow())).order_by(VoiceProfile.created_at).first()
        profile_id = profile.id if profile else None
    if profile_id is not None:
        prepare_voice(profile_id, session_factory)
