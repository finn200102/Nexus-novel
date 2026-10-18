"""Exact chunk start locators and measured PCM timing, never word estimates."""
import math
import wave
from pathlib import Path

from app.models.audio_job import ChapterAudioPart
from app.services.chapter_version_service import document_for


def utf16_length(value):
    return len(value.encode("utf-16-le")) // 2


def plan_passages(document, title, maximum, *, include_author_notes=False, pronunciation_rules=None):
    result = []
    from app.services.pronunciation_service import pronounced_chunks, ensure_speech_budget, AudioPlanningLimitError, MAX_AUDIO_PARTS, MAX_AUDIO_SPOKEN_UTF16
    ensure_speech_budget(document, title, pronunciation_rules or [], include_author_notes)
    spoken_size = 0
    def add(part):
        nonlocal spoken_size
        spoken_size += utf16_length(part["text"])
        if len(result) >= MAX_AUDIO_PARTS or spoken_size > MAX_AUDIO_SPOKEN_UTF16:
            raise AudioPlanningLimitError()
        result.append(part)
    planner = (lambda text, bound: pronounced_chunks(text, bound, pronunciation_rules)) if pronunciation_rules else chunks
    # The spoken title is intentionally unanchored to the story's prose.
    for chunk in planner(title or "", maximum):
        add({"text": chunk[0], "block_id": None, "text_offset": None, "text_length": None})
    for block in document.get("blocks", []):
        if block.get("role") == "author_note" and not include_author_notes:
            continue
        text = block.get("text", "")
        for spoken, start, end in planner(text, maximum):
            add({"text": spoken, "block_id": block["id"], "text_offset": utf16_length(text[:start]), "text_length": utf16_length(text[start:end])})
    return result


def chunks(text, maximum):
    """Keep original character offsets while normalizing only the spoken copy."""
    start = 0
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            break
        end = min(len(text), start + maximum)
        if end < len(text):
            cut = max(text.rfind(" ", start + maximum // 2, end), text.rfind("\n", start + maximum // 2, end))
            if cut > start:
                end = cut
        raw = text[start:end]
        end -= len(raw) - len(raw.rstrip())
        if end <= start:
            break
        yield " ".join(text[start:end].split()), start, end
        start = end


def wav_duration(path):
    with wave.open(str(path), "rb") as reader:
        rate, count = reader.getframerate(), reader.getnframes()
        channels, width = reader.getnchannels(), reader.getsampwidth()
        if not 8000 <= rate <= 96000 or channels not in (1, 2) or width not in (1, 2, 3, 4) or not 0 < count <= rate * 600:
            raise ValueError("Provider returned an unsupported audio segment")
        if reader.getcomptype() != "NONE":
            raise ValueError("Provider returned compressed WAV audio")
        remaining = count
        while remaining:
            frames = min(65536, remaining)
            if len(reader.readframes(frames)) != frames * channels * width:
                raise ValueError("Provider returned truncated WAV audio")
            remaining -= frames
        return count / rate


def manifest(db, job):
    parts = db.query(ChapterAudioPart).filter_by(job_id=job.id).order_by(ChapterAudioPart.part_index).all()
    available = bool(job.status == "completed" and job.source_version and job.audio_path and Path(job.audio_path).is_file()
        and bool(parts) and len(parts) == job.total_parts
        and [p.part_index for p in parts] == list(range(job.total_parts))
        and all(p.status == "completed" and p.duration_seconds is not None
            and math.isfinite(p.duration_seconds) and p.duration_seconds > 0 for p in parts))
    segments, elapsed = [], 0.0
    if available:
        for part in parts:
            end = elapsed + part.duration_seconds
            segments.append({"part_index": part.part_index, "block_id": part.block_id, "text_offset": part.text_offset,
                "text_length": part.text_length, "start_seconds": elapsed, "end_seconds": end})
            elapsed = end
    from app.services.audio_identity_service import fields, chapter_for_job
    chapter = chapter_for_job(db, job)
    provenance = fields(db, job, chapter)
    current_version = document_for(chapter).get("content_version") if chapter is not None else None
    return {**provenance, "job_id": job.id, "source_version": job.source_version, "rendition": "original",
        "include_author_notes": job.include_author_notes, "pronunciation_version": job.pronunciation_version, "precision": "segment" if available else "unavailable",
        "current_source": bool(provenance["source_identity_current"] and not provenance["chapter_archived"] and job.source_version and job.source_version == current_version),
        "duration_seconds": elapsed if available else None, "segments": segments}
