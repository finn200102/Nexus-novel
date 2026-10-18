"""Server-backed chapter audio jobs for providers reachable by Nexus."""

from __future__ import annotations

import os
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.models.audio_job import ChapterAudioJob, ChapterAudioPart
from app.models.chapter import AudioStatus, Chapter
from app.services.job_lease import claim, heartbeat
from sqlalchemy.exc import IntegrityError


ACTIVE_AUDIO_STATUSES = ("queued", "processing", "retry_wait")
PROVIDER_CAPABILITIES = [
    {"id": "kokoro_mps", "label": "Kokoro · fast local", "execution_mode": "browser", "safe_segment_size": 1100, "experimental": False, "response_formats": ["wav"]},
    {"id": "chatterbox_turbo_mlx", "label": "Chatterbox Turbo · expressive local", "execution_mode": "browser", "safe_segment_size": 900, "experimental": False, "response_formats": ["wav"]},
    {"id": "qwen3_mlx_4bit", "label": "Qwen3-TTS 1.7B · experimental", "execution_mode": "browser", "safe_segment_size": 350, "experimental": True, "response_formats": ["wav"]},
    {"id": "spark_tts_mlx", "label": "Spark-TTS 0.5B · experimental", "execution_mode": "browser", "safe_segment_size": 380, "experimental": True, "response_formats": ["wav"]},
    {"id": "qwen3_clone", "label": "My cloned narrator · local Qwen3", "execution_mode": "server", "safe_segment_size": 350, "experimental": True, "response_formats": ["wav"]},
    {"id": "custom", "label": "Custom OpenAI-compatible API", "execution_mode": "server", "safe_segment_size": 900, "experimental": False, "response_formats": ["wav", "mp3"]},
]


def capability_for(provider_id: str) -> dict:
    return next((item for item in PROVIDER_CAPABILITIES if item["id"] == provider_id), PROVIDER_CAPABILITIES[-1])


def speech_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/audio/speech") else f"{normalized}/audio/speech"


def split_text(text: str, maximum: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    sentences = __import__("re").findall(r"[^.!?]+[.!?]+|[^.!?]+$", normalized) or [normalized]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        # Long sentences must remain bounded even after a short chapter title.
        for index in range(0, len(sentence), maximum):
            piece = sentence[index:index + maximum]
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > maximum:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def queue_audio_job(db: Session, *, user_id: int, library_id: int, novel_id: int, chapter: Chapter, provider: dict, voice_profile_id: int | None = None, include_author_notes: bool = False, pronunciation: dict | None = None, identity_expectations: dict | None = None) -> ChapterAudioJob:
    from app.services.audio_identity_service import capture
    captured = capture(db, user_id, chapter, identity_expectations)
    if chapter.novel_id != novel_id or chapter.novel.library_id != library_id:
        from fastapi import HTTPException
        raise HTTPException(404, "Chapter not found")
    if voice_profile_id is not None:
        from app.services.voice_service import owned_ready
        owned_ready(db, voice_profile_id, user_id)
    active = db.query(ChapterAudioJob).filter(
        ChapterAudioJob.user_id == user_id,
        ChapterAudioJob.chapter_id == chapter.id,
        ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES),
    ).first()
    if active:
        from app.services.audio_identity_service import require_dispatch
        require_dispatch(db, active)
        return active
    capability = capability_for(provider.get("id", "custom"))
    from app.services.audio_alignment import plan_passages
    from app.services.chapter_version_service import document_for, retain_current
    document = document_for(chapter)
    from app.services.pronunciation_service import snapshot as pronunciation_snapshot
    pronunciation = pronunciation if pronunciation is not None else pronunciation_snapshot(db, user_id, novel_id)
    chunks = plan_passages(document, chapter.title, capability["safe_segment_size"], include_author_notes=include_author_notes, pronunciation_rules=pronunciation["effective_rules"])
    if not chunks:
        raise ValueError("This chapter has no text to turn into audio.")
    job = ChapterAudioJob(
        user_id=user_id, library_id=library_id, novel_id=novel_id, chapter_id=chapter.id,
        voice_profile_id=voice_profile_id, provider_id=provider.get("id", "custom"), provider_url=provider["base_url"],
        provider_model=provider["model"], provider_voice=provider["voice"],
        provider_language=provider.get("language_code"), total_parts=len(chunks),
        source_version=document["content_version"], chapter_key=captured["chapter_key"],
        manifest_epoch=captured["manifest_epoch"], manifest_revision=captured["manifest_revision"],
        chapter_title_snapshot=chapter.title, chapter_number_snapshot=chapter.chapter_number, identity_inferred=False,
        include_author_notes=include_author_notes,
        pronunciation_version=pronunciation["effective_version"], pronunciation_rules=pronunciation["effective_rules"],
        next_attempt_at=datetime.now(UTC).replace(tzinfo=None),
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        existing = db.query(ChapterAudioJob).filter(ChapterAudioJob.user_id == user_id,
            ChapterAudioJob.chapter_id == chapter.id, ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES)).first()
        if existing:
            from app.services.audio_identity_service import require_dispatch
            require_dispatch(db,existing)
            return existing
        raise
    retain_current(db, chapter, reason="narration")
    db.add_all(ChapterAudioPart(job_id=job.id, part_index=index, **chunk) for index, chunk in enumerate(chunks))
    chapter.audio_status = AudioStatus.PROCESSING
    db.commit()
    db.refresh(job)
    return job


def claim_audio_job(db: Session, job_id: int) -> ChapterAudioJob | None:
    return claim(db, ChapterAudioJob, job_id)


def _job_directory(job: ChapterAudioJob) -> Path:
    root = Path(os.getenv("DOWNLOAD_PATH", "/data/downloads")) / "audio" / str(job.user_id) / str(job.novel_id) / str(job.chapter_id) / str(job.id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def delete_audio_job(db: Session, job: ChapterAudioJob) -> None:
    """Remove a completed/cancelled audio job and only its owned audio files."""
    if job.status in ACTIVE_AUDIO_STATUSES:
        raise ValueError("Pause the audio generation before deleting it")

    from app.services.podcast_audio_service import delete_podcast_audio_for_source
    delete_podcast_audio_for_source(db, job)
    chapter_id = job.chapter_id
    paths = [Path(path) for path in [job.audio_path, *[
        part.audio_path for part in db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id == job.id).all()
    ]] if path]
    db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id == job.id).delete(synchronize_session=False)
    db.delete(job)
    db.flush()

    # Remove only file paths attached to this job. This keeps a regenerated
    # chapter's newer audio intact even if an older job is later deleted.
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            path.parent.rmdir()
        except OSError:
            pass

    remaining = db.query(ChapterAudioJob).filter(
        ChapterAudioJob.chapter_id == chapter_id,
        ChapterAudioJob.status == "completed",
        ChapterAudioJob.audio_path.isnot(None),
    ).first()
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if chapter and not remaining:
        chapter.audio_status = AudioStatus.MISSING
    db.commit()


def _write_wav_parts(parts: list[Path], final_path: Path) -> int:
    if not parts:
        raise ValueError("No audio segments were created")
    parameters = None
    with wave.open(str(final_path), "wb") as writer:
        for path in parts:
            with wave.open(str(path), "rb") as reader:
                current = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
                if parameters is None:
                    parameters = current
                    writer.setnchannels(current[0]); writer.setsampwidth(current[1]); writer.setframerate(current[2]); writer.setcomptype(current[3], "not compressed")
                elif current != parameters:
                    raise ValueError("Provider returned incompatible WAV segment formats")
                remaining = reader.getnframes()
                while remaining:
                    count = min(65536, remaining)
                    data = reader.readframes(count)
                    if len(data) != count * current[0] * current[1]:
                        raise ValueError("Provider returned truncated WAV audio")
                    writer.writeframesraw(data)
                    remaining -= count
    return final_path.stat().st_size



def _owns_audio_job(db: Session, job_id: int, owner: str, attempt=None) -> bool:
    from app.models.user import User
    from app.services.audio_identity_service import require_dispatch
    from fastapi import HTTPException
    with db.no_autoflush:
        user_id = db.query(ChapterAudioJob.user_id).filter_by(id=job_id).scalar()
        if user_id is None:
            return False
        db.query(User.id).filter_by(id=user_id).with_for_update().first()
        current = db.query(ChapterAudioJob).populate_existing().filter_by(id=job_id).with_for_update().first()
    if (current is None or current.status != "processing" or current.lease_owner != owner
            or current.lease_expires_at is None or current.lease_expires_at <= datetime.now(UTC).replace(tzinfo=None)
            or current.cancelled_at is not None or (attempt is not None and current.attempt_count != attempt)):
        db.rollback()
        return False
    try:
        require_dispatch(db, current)
    except HTTPException:
        current.status = "failed"
        current.error_code = "audio_identity_review_required"
        current.error = "The original chapter identity or text changed. Review the chapter before creating new narration. Existing recordings are preserved."
        current.finished_at = datetime.now(UTC).replace(tzinfo=None)
        current.lease_owner = current.lease_expires_at = None
        db.commit()
        return False
    return True


def process_audio_job(job_id: int, session_factory) -> None:
    db: Session = session_factory()
    try:
        job = claim_audio_job(db, job_id)
        if not job:
            return
        owner, attempt = job.lease_owner, job.attempt_count
        if not _owns_audio_job(db, job_id, owner, attempt):
            return
        db.commit()
        parts = db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id == job.id).order_by(ChapterAudioPart.part_index).all()
        directory = _job_directory(job)
        try:
            with heartbeat(session_factory, ChapterAudioJob, job.id, job.lease_owner), httpx.Client(timeout=httpx.Timeout(960.0 if job.provider_id == "qwen3_clone" else 120.0, connect=8.0)) as client:
                for part in parts:
                    if part.status == "completed":
                        continue
                    if not _owns_audio_job(db, job_id, owner, attempt):
                        return
                    db.commit()  # authorization is committed before provider I/O; publication rechecks it.
                    if job.provider_id == "qwen3_clone":
                        from app.services.voice_service import owned_ready, bridge_config, request_payload
                        profile = owned_ready(db, job.voice_profile_id, job.user_id)
                        url, headers = bridge_config()
                        response = client.post(url + "/v1/audio/speech", json=request_payload(profile, input=part.text), headers=headers)
                    else:
                        response = client.post(speech_url(job.provider_url), json={
                        "model": job.provider_model, "voice": job.provider_voice, "input": part.text,
                        "response_format": "wav", **({"lang_code": job.provider_language} if job.provider_language else {}),
                    })
                    response.raise_for_status()
                    if not _owns_audio_job(db, job_id, owner, attempt):
                        return
                    if not response.content.startswith(b"RIFF"):
                        raise ValueError("Provider did not return a WAV audio segment")
                    path = directory / f"part-{part.part_index:04d}.wav"
                    path.write_bytes(response.content)
                    from app.services.audio_alignment import wav_duration
                    duration = wav_duration(path)
                    part.duration_seconds = duration
                    part.audio_path = str(path)
                    part.status = "completed"
                    job.completed_parts = part.part_index + 1
                    db.commit()
            final_path = directory / "chapter.wav"
            if not _owns_audio_job(db, job_id, owner, attempt):
                return
            from app.services.audio_alignment import wav_duration
            for part in parts:
                if part.audio_path and part.duration_seconds is None:
                    part.duration_seconds = wav_duration(part.audio_path)
            job.audio_bytes = _write_wav_parts([Path(part.audio_path) for part in parts if part.audio_path], final_path)
            job.audio_path = str(final_path)
            job.status = "completed"
            job.lease_owner = None
            job.lease_expires_at = None
            job.finished_at = datetime.now(UTC).replace(tzinfo=None)
            job.error = None
            job.error_code = None
            chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
            if chapter:
                chapter.audio_status = AudioStatus.PRESENT
            db.commit()
        except Exception as exc:
            db.rollback()
            if not _owns_audio_job(db, job_id, owner, attempt):
                return
            job.lease_owner = None
            job.lease_expires_at = None
            job.error = "Local voice generation failed. Check the local speech service and retry." if job.provider_id == "qwen3_clone" else str(exc)[:2000]
            job.error_code = "audio_provider_failed"
            if job.attempt_count >= job.max_attempts:
                job.status = "failed"
                job.finished_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                job.status = "retry_wait"
                job.next_attempt_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30 * (2 ** (job.attempt_count - 1)))
            db.commit()
    finally:
        db.close()
