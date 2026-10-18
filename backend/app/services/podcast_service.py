"""Private RSS enclosures reference prepared MP3 derivatives; never generate speech."""
from datetime import UTC, timedelta
from email.utils import format_datetime
import hashlib
from pathlib import Path
import re
import secrets
from xml.etree import ElementTree as ET

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.auth import rate_limit
from app.auth.sessions import client_ip, utcnow
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.podcast import PodcastFeedToken
from app.models.user import User
from config.settings import settings

INVALID = rate_limit.Limit("podcast:ip", 30, timedelta(minutes=15))
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def owned_story(db: Session, user_id: int, novel_id: int) -> Novel:
    story = db.query(Novel).join(Library, Library.id == Novel.library_id).filter(
        Novel.id == novel_id, Library.user_id == user_id).first()
    if not story:
        raise HTTPException(404, "Story not found")
    return story


def token_row(db: Session, user_id: int, novel_id: int):
    return db.query(PodcastFeedToken).filter_by(user_id=user_id, novel_id=novel_id).first()


def rotate(db: Session, user_id: int, novel_id: int) -> str:
    owned_story(db, user_id, novel_id)
    token = secrets.token_urlsafe(32)
    row = token_row(db, user_id, novel_id)
    if row is None:
        db.add(PodcastFeedToken(user_id=user_id, novel_id=novel_id, token_hash=digest(token)))
    else:
        row.token_hash = digest(token)
        row.last_used_at = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = token_row(db, user_id, novel_id)
        if row is None:
            raise
        row.token_hash, row.last_used_at = digest(token), None
        db.commit()
    return token


def authenticate(db: Session, request: Request, token: str) -> PodcastFeedToken:
    ip = client_ip(request)
    rate_limit.check(db, INVALID, ip)
    row = db.query(PodcastFeedToken).join(User, User.id == PodcastFeedToken.user_id).join(
        Novel, Novel.id == PodcastFeedToken.novel_id).join(Library, Library.id == Novel.library_id).filter(
        PodcastFeedToken.token_hash == digest(token), User.is_disabled.is_(False),
        Library.user_id == PodcastFeedToken.user_id).first() if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None
    if row is None:
        rate_limit.record(db, INVALID, ip)
        raise HTTPException(404, "Podcast not found", headers=PRIVATE_HEADERS)
    row.last_used_at = utcnow()
    db.commit()
    return row


def audio_path(job: ChapterAudioJob) -> Path | None:
    if job.status != "completed" or not job.audio_path:
        return None
    storage = Path(settings.DOWNLOAD_PATH).absolute()
    path = Path(job.audio_path).absolute()
    try:
        # A system alias above the configured volume (macOS /var, for example)
        # is harmless. Links inside private storage are never accepted.
        try:
            relative = path.relative_to(storage)
        except ValueError:
            relative = path.relative_to(storage.resolve())
        if relative.parts[:2] != ("audio", str(job.user_id)):
            return None
        current = storage
        for part in ("", *relative.parts):
            current = current / part
            if current.is_symlink():
                return None
        resolved = current.resolve()
        root = storage.resolve() / "audio" / str(job.user_id)
        return resolved if resolved.is_relative_to(root) and resolved.is_file() else None
    except (OSError, ValueError):
        return None


def public_api_base(request: Request) -> str:
    if settings.NEXUS_PUBLIC_API_URL:
        return settings.NEXUS_PUBLIC_API_URL.rstrip("/")
    # Bundled nginx overwrites this header; direct API installations need no prefix.
    prefix = "/api" if request.headers.get("x-forwarded-prefix") == "/api" else ""
    host = request.headers.get("x-forwarded-host") if prefix else None
    if host and re.fullmatch(r"[A-Za-z0-9.\[\]:-]+", host):
        scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else "http"
        return f"{scheme}://{host}{prefix}"
    return str(request.base_url).rstrip("/") + prefix


def _text(parent, name, value, **attrs):
    node = ET.SubElement(parent, name, attrs)
    node.text = "".join(ch for ch in str(value or "") if ch in "\t\n\r" or 32 <= ord(ch) <= 0xD7FF or 0xE000 <= ord(ch) <= 0xFFFD or 0x10000 <= ord(ch) <= 0x10FFFF)
    return node


def build_feed(db: Session, row: PodcastFeedToken, token: str, api_base: str) -> bytes:
    from app.services.podcast_audio_service import latest_sources, ready_file
    story = owned_story(db, row.user_id, row.novel_id)
    itunes = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ET.register_namespace("itunes", itunes)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    _text(channel, "title", story.title)
    _text(channel, "link", api_base.removesuffix("/api") + "/")
    _text(channel, "description", "Private Nexus narration. Completed recordings are prepared as MP3 episodes; originals remain private.")
    _text(channel, f"{{{itunes}}}author", "Nexus private library")
    _text(channel, f"{{{itunes}}}type", "serial")
    recordings = latest_sources(db, row.user_id, row.novel_id).order_by(Chapter.chapter_number, Chapter.id).yield_per(100)
    owner = db.get(User, row.user_id)
    for job, chapter, derivative in recordings:
        path = ready_file(derivative)
        if path is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        item = ET.SubElement(channel, "item")
        _text(item, "title", derivative.source_snapshot.get("title") or f"Chapter {derivative.chapter_number}")
        _text(item, "guid", f"urn:nexus:recording:{owner.storage_id}:{job.id}", isPermaLink="false")
        _text(item, "description", f"Chapter {derivative.chapter_number}")
        if derivative.chapter_number > 0:
            _text(item, f"{{{itunes}}}episode", str(derivative.chapter_number))
        _text(item, f"{{{itunes}}}duration", str(round(derivative.duration_seconds or 0)))
        stamp = job.finished_at or job.created_at
        if stamp:
            _text(item, "pubDate", format_datetime(stamp.replace(tzinfo=UTC), usegmt=True))
        ET.SubElement(item, "enclosure", {"url": f"{api_base}/podcasts/{token}/audio/{job.id}.mp3",
                                         "length": str(size), "type": "audio/mpeg"})
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)
