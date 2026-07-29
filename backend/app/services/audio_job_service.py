"""Server-backed chapter audio jobs for providers reachable by Nexus."""

from __future__ import annotations

import io
import os
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.models.audio_job import ChapterAudioJob, ChapterAudioPart
from app.models.chapter import AudioStatus, Chapter


ACTIVE_AUDIO_STATUSES = ("queued", "processing", "retry_wait")
PROVIDER_CAPABILITIES = [
    {"id": "kokoro_mps", "label": "Kokoro · fast local", "execution_mode": "browser", "safe_segment_size": 1100, "experimental": False},
    {"id": "chatterbox_turbo_mlx", "label": "Chatterbox Turbo · expressive local", "execution_mode": "browser", "safe_segment_size": 900, "experimental": False},
    {"id": "qwen3_mlx_4bit", "label": "Qwen3-TTS 1.7B · experimental", "execution_mode": "browser", "safe_segment_size": 350, "experimental": True},
    {"id": "spark_tts_mlx", "label": "Spark-TTS 0.5B · experimental", "execution_mode": "browser", "safe_segment_size": 380, "experimental": True},
    {"id": "custom", "label": "Custom OpenAI-compatible API", "execution_mode": "server", "safe_segment_size": 900, "experimental": False},
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
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > maximum:
            chunks.append(current)
            current = sentence
        elif len(sentence) > maximum:
            chunks.extend(sentence[index:index + maximum] for index in range(0, len(sentence), maximum))
            current = ""
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def queue_audio_job(db: Session, *, user_id: int, library_id: int, novel_id: int, chapter: Chapter, provider: dict) -> ChapterAudioJob:
    active = db.query(ChapterAudioJob).filter(
        ChapterAudioJob.user_id == user_id,
        ChapterAudioJob.chapter_id == chapter.id,
        ChapterAudioJob.status.in_(ACTIVE_AUDIO_STATUSES),
    ).first()
    if active:
        return active
    capability = capability_for(provider.get("id", "custom"))
    chunks = split_text(f"{chapter.title}. {chapter.content or ''}", capability["safe_segment_size"])
    if not chunks:
        raise ValueError("This chapter has no text to turn into audio.")
    job = ChapterAudioJob(
        user_id=user_id, library_id=library_id, novel_id=novel_id, chapter_id=chapter.id,
        provider_id=provider.get("id", "custom"), provider_url=provider["base_url"],
        provider_model=provider["model"], provider_voice=provider["voice"],
        provider_language=provider.get("language_code"), total_parts=len(chunks),
        next_attempt_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(job)
    db.flush()
    db.add_all(ChapterAudioPart(job_id=job.id, part_index=index, text=text) for index, text in enumerate(chunks))
    chapter.audio_status = AudioStatus.PROCESSING
    db.commit()
    db.refresh(job)
    return job


def claim_audio_job(db: Session, job_id: int) -> ChapterAudioJob | None:
    now = datetime.now(UTC).replace(tzinfo=None)
    job = db.query(ChapterAudioJob).filter(ChapterAudioJob.id == job_id).first()
    if not job or job.status not in {"queued", "retry_wait"} or (job.next_attempt_at and job.next_attempt_at > now):
        return None
    job.status = "processing"
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.error = None
    job.error_code = None
    db.commit()
    db.refresh(job)
    return job


def _job_directory(job: ChapterAudioJob) -> Path:
    root = Path(os.getenv("DOWNLOAD_PATH", "/data/downloads")) / "audio" / str(job.user_id) / str(job.novel_id) / str(job.chapter_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_wav_parts(parts: list[Path], final_path: Path) -> int:
    parameters = None
    frames: list[bytes] = []
    for path in parts:
        with wave.open(str(path), "rb") as reader:
            current = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
            if parameters is None:
                parameters = current
            elif current != parameters:
                raise ValueError("Provider returned incompatible WAV segment formats")
            frames.append(reader.readframes(reader.getnframes()))
    if not parameters:
        raise ValueError("No audio segments were created")
    with wave.open(str(final_path), "wb") as writer:
        writer.setnchannels(parameters[0])
        writer.setsampwidth(parameters[1])
        writer.setframerate(parameters[2])
        writer.setcomptype(parameters[3], "not compressed")
        for frame in frames:
            writer.writeframes(frame)
    return final_path.stat().st_size


def process_audio_job(job_id: int, session_factory) -> None:
    db: Session = session_factory()
    try:
        job = claim_audio_job(db, job_id)
        if not job:
            return
        parts = db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id == job.id).order_by(ChapterAudioPart.part_index).all()
        directory = _job_directory(job)
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=8.0)) as client:
                for part in parts:
                    if part.status == "completed":
                        continue
                    latest = db.query(ChapterAudioJob).filter(ChapterAudioJob.id == job.id).first()
                    if not latest or latest.status == "cancelled":
                        return
                    response = client.post(speech_url(job.provider_url), json={
                        "model": job.provider_model, "voice": job.provider_voice, "input": part.text,
                        "response_format": "wav", **({"lang_code": job.provider_language} if job.provider_language else {}),
                    })
                    response.raise_for_status()
                    if not response.content.startswith(b"RIFF"):
                        raise ValueError("Provider did not return a WAV audio segment")
                    path = directory / f"part-{part.part_index:04d}.wav"
                    path.write_bytes(response.content)
                    part.audio_path = str(path)
                    part.status = "completed"
                    job.completed_parts = part.part_index + 1
                    db.commit()
            final_path = directory / "chapter.wav"
            job.audio_bytes = _write_wav_parts([Path(part.audio_path) for part in parts if part.audio_path], final_path)
            job.audio_path = str(final_path)
            job.status = "completed"
            job.finished_at = datetime.now(UTC).replace(tzinfo=None)
            job.error = None
            job.error_code = None
            chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
            if chapter:
                chapter.audio_status = AudioStatus.PRESENT
            db.commit()
        except Exception as exc:
            job.error = str(exc)[:2000]
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
