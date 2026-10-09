"""Native Kobo sync: device tokens, library sync, KEPUB files and progress.

The Kobo store protocol (as implemented by Calibre-Web and Komga, see
docs/kobo-sync.md) is spoken under ``/kobo/<token>/``. Each device syncs one
shelf. What a device was last told lives in ``kobo_synced_books``, so a sync
sends only books that are new, changed or gone, and reading states that moved.
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import rate_limit
from app.auth.sessions import client_ip, utcnow
from app.models.chapter import Chapter
from app.models.ereader import EpubBuild, KoboDevice, KoboSyncedBook
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.models.shelf import Shelf, ShelfNovel
from app.models.user import User
from app.services import epub_service
from app.services.reading_progress_service import save_reading_progress
from config.settings import settings

logger = logging.getLogger(__name__)

INVALID_TOKENS_PER_IP = rate_limit.Limit("kobo:ip", 30, timedelta(minutes=15))
DEFAULT_SHELF_NAME = "Kobo"
# Books and reading states per sync response; the device asks again while
# the response carries ``x-kobo-sync: continue`` (Calibre-Web uses 100 too).
SYNC_ITEM_LIMIT = 100
SYNC_TOKEN_HEADER = "x-kobo-synctoken"
ENTITLEMENT_NAMESPACE = uuid.UUID("5b0f4f5e-6c43-4a8e-9d55-1f2a7c3e9b10")
CHAPTER_FILE = re.compile(r"chapter-(\d+)\.xhtml")
TAGS = re.compile(r"<[^>]+>")


# ---- tokens -----------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_shelf(db: Session, user: User) -> Shelf:
    shelf = db.query(Shelf).filter(Shelf.user_id == user.id, Shelf.name == DEFAULT_SHELF_NAME).first()
    if shelf is None:
        shelf = Shelf(user_id=user.id, name=DEFAULT_SHELF_NAME, position=0)
        db.add(shelf)
        db.flush()
    return shelf


def owned_shelf(db: Session, user: User, shelf_id: int) -> Shelf:
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id, Shelf.user_id == user.id).first()
    if shelf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shelf not found")
    return shelf


def create_device(db: Session, user: User, label: str, shelf_id: int | None) -> tuple[KoboDevice, str]:
    """Create a device; the token is returned once and only its hash is kept."""
    shelf = owned_shelf(db, user, shelf_id) if shelf_id is not None else default_shelf(db, user)
    token = secrets.token_urlsafe(32)
    device = KoboDevice(user_id=user.id, label=label.strip()[:120], token_hash=_hash(token), shelf_id=shelf.id)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, token


def list_devices(db: Session, user_id: int) -> list[KoboDevice]:
    return (
        db.query(KoboDevice)
        .filter(KoboDevice.user_id == user_id, KoboDevice.revoked_at.is_(None))
        .order_by(KoboDevice.created_at.desc(), KoboDevice.id.desc())
        .all()
    )


def get_device(db: Session, user_id: int, device_id: int) -> KoboDevice:
    device = (
        db.query(KoboDevice)
        .filter(KoboDevice.id == device_id, KoboDevice.user_id == user_id, KoboDevice.revoked_at.is_(None))
        .first()
    )
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kobo device not found")
    return device


def revoke_device(db: Session, user_id: int, device_id: int) -> None:
    device = get_device(db, user_id, device_id)
    device.revoked_at = utcnow()
    db.commit()


def device_for_token(db: Session, request: Request, token: str) -> tuple[KoboDevice, User]:
    """Authenticate a Kobo request by its path token. Wrong tokens are rate limited per address."""
    ip = client_ip(request)
    rate_limit.check(db, INVALID_TOKENS_PER_IP, ip)
    device = (
        db.query(KoboDevice)
        .filter(KoboDevice.token_hash == _hash(token), KoboDevice.revoked_at.is_(None))
        .first()
        if token
        else None
    )
    user = db.query(User).filter(User.id == device.user_id).first() if device is not None else None
    if device is None or user is None or user.is_disabled:
        rate_limit.record(db, INVALID_TOKENS_PER_IP, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown Kobo token")
    now = utcnow()
    if device.last_used_at is None or now - device.last_used_at > timedelta(minutes=1):
        device.last_used_at = now
        db.commit()
    return device, user


# ---- URLs and formatting ----------------------------------------------------

def api_base(request: Request) -> str:
    """The external URL of the API (``.../api`` behind the bundled nginx)."""
    configured = settings.NEXUS_KOBO_BASE_URL.strip().rstrip("/")
    if configured:
        return configured
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    prefix = "/api" if request.headers.get("x-real-ip") else ""
    return f"{proto}://{host}{prefix}"


def kobo_base(request: Request, token: str) -> str:
    return f"{api_base(request)}/kobo/{token}"


def timestamp(value: datetime | None) -> str:
    return (value or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def entitlement_id(novel_id: int) -> str:
    return str(uuid.uuid5(ENTITLEMENT_NAMESPACE, f"novel:{novel_id}"))


def tag_id(shelf_id: int) -> str:
    return str(uuid.uuid5(ENTITLEMENT_NAMESPACE, f"shelf:{shelf_id}"))


def encode_sync_token(device: KoboDevice) -> str:
    payload = json.dumps({"nexus": 1, "device": device.id}, separators=(",", ":"))
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def is_own_sync_token(value: str | None, device: KoboDevice) -> bool:
    """False for no token (a new or reset device) or someone else's, which means a full resync."""
    if not value:
        return False
    try:
        payload = json.loads(base64.b64decode(value, validate=False))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("nexus") == 1 and payload.get("device") == device.id


# ---- KEPUB ------------------------------------------------------------------

def kepubify_binary() -> str | None:
    configured = settings.NEXUS_KEPUBIFY_PATH.strip()
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    return shutil.which("kepubify")


def kepub_path(built: epub_service.BuiltEpub) -> Path:
    return built.path.with_name(built.path.name.removesuffix(".epub") + ".kepub.epub")


def ensure_kepub(built: epub_service.BuiltEpub) -> Path | None:
    """KEPUB next to the cached EPUB, converted once with kepubify; None when unavailable.

    The file shares the EPUB's ``<novel>-<fingerprint>`` name, so the EPUB
    cache cleanup removes it once the novel's chapters change.
    """
    target = kepub_path(built)
    if target.is_file():
        return target
    binary = kepubify_binary()
    if binary is None:
        return None
    with tempfile.TemporaryDirectory(dir=built.path.parent) as scratch:
        output = Path(scratch) / "book.kepub.epub"
        try:
            subprocess.run(
                [binary, "-o", str(output), str(built.path)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("kepubify failed for %s: %s", built.path.name, exc)
            return None
        if not output.is_file():
            return None
        os.replace(output, target)
    return target


@dataclass(frozen=True)
class BookFile:
    built: epub_service.BuiltEpub
    path: Path
    kobo_format: str  # "KEPUB" or "EPUB3"


def book_file(db: Session, novel: Novel) -> BookFile:
    built = epub_service.ensure_build(db, novel)
    kepub = ensure_kepub(built)
    if kepub is not None:
        return BookFile(built=built, path=kepub, kobo_format="KEPUB")
    return BookFile(built=built, path=built.path, kobo_format="EPUB3")


# ---- library ------------------------------------------------------------------

def shelf_novels(db: Session, device: KoboDevice) -> list[Novel]:
    """The device's shelf, limited to stories in the owner's own libraries."""
    if device.shelf_id is None:
        return []
    return (
        db.query(Novel)
        .join(ShelfNovel, ShelfNovel.novel_id == Novel.id)
        .join(Library, Library.id == Novel.library_id)
        .filter(ShelfNovel.shelf_id == device.shelf_id, Library.user_id == device.user_id)
        .order_by(ShelfNovel.position.asc(), Novel.id.asc())
        .all()
    )


def synced_book(db: Session, device: KoboDevice, book_id: str) -> tuple[KoboSyncedBook, Novel] | None:
    row = (
        db.query(KoboSyncedBook)
        .filter(KoboSyncedBook.device_id == device.id, KoboSyncedBook.entitlement_id == book_id)
        .first()
    )
    if row is None:
        return None
    novel = (
        db.query(Novel)
        .join(Library, Library.id == Novel.library_id)
        .filter(Novel.id == row.novel_id, Library.user_id == device.user_id)
        .first()
    )
    return (row, novel) if novel is not None else None


def forget_book(db: Session, device: KoboDevice, row: KoboSyncedBook) -> None:
    """The device deleted the book: drop it from the device's shelf and stop sending it."""
    if device.shelf_id is not None:
        db.query(ShelfNovel).filter(ShelfNovel.shelf_id == device.shelf_id, ShelfNovel.novel_id == row.novel_id).delete(
            synchronize_session=False
        )
    row.removed = True
    db.commit()


def _plain(text: str | None) -> str:
    return unescape(TAGS.sub(" ", text or "")).strip()


def book_entitlement(row: KoboSyncedBook, novel: Novel, *, removed: bool) -> dict:
    eid = row.entitlement_id
    return {
        "Accessibility": "Full",
        "ActivePeriod": {"From": timestamp(None)},
        "Created": timestamp(row.created_at or novel.created_at),
        "CrossRevisionId": eid,
        "Id": eid,
        "IsRemoved": removed,
        "IsHiddenFromArchive": False,
        "IsLocked": False,
        "LastModified": timestamp(novel.updated_at or novel.created_at),
        "OriginCategory": "Imported",
        "RevisionId": eid,
        "Status": "Active",
    }


def book_metadata(base: str, row: KoboSyncedBook, novel: Novel, file: BookFile) -> dict:
    eid = row.entitlement_id
    version = file.built.build.fingerprint[:12]
    fmt = "kepub" if file.kobo_format == "KEPUB" else "epub"
    author = (novel.author or "").strip()
    metadata = {
        "Categories": ["00000000-0000-0000-0000-000000000001"],
        "CoverImageId": eid,
        "CrossRevisionId": eid,
        "CurrentDisplayPrice": {"CurrencyCode": "USD", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": _plain(novel.description),
        "DownloadUrls": [
            {
                "Format": file.kobo_format,
                "Size": file.path.stat().st_size,
                "Url": f"{base}/download/{eid}/{fmt}?v={version}",
                "Platform": "Generic",
            }
        ],
        "EntitlementId": eid,
        "ExternalIds": [],
        "Genre": "00000000-0000-0000-0000-000000000001",
        "IsEligibleForKoboLove": False,
        "IsInternetArchive": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": "en",
        "PhoneticPronunciations": {},
        "PublicationDate": timestamp(novel.publish_date or novel.created_at),
        "Publisher": {"Imprint": "", "Name": novel.novel_site or novel.site or "Nexus"},
        "RevisionId": eid,
        "Title": novel.title or "Untitled",
        "WorkId": eid,
    }
    if author:
        metadata["ContributorRoles"] = [{"Name": author}]
        metadata["Contributors"] = [author]
    else:
        metadata["Contributors"] = None
    return metadata


# ---- reading state ------------------------------------------------------------

def _spine(db: Session, row: KoboSyncedBook) -> list[int]:
    """Chapter numbers of the book the device holds (latest build as a fallback)."""
    query = db.query(EpubBuild).filter(EpubBuild.novel_id == row.novel_id)
    build = query.filter(EpubBuild.fingerprint == row.fingerprint).first() if row.fingerprint else None
    if build is None:
        build = query.order_by(EpubBuild.id.desc()).first()
    return list(build.spine or []) if build is not None else []


def _device_position(row: KoboSyncedBook, spine: list[int]) -> tuple[int, float] | None:
    """(spine index, fraction of that chapter) of the device's stored bookmark."""
    if not spine or row.bookmark_at is None:
        return None
    if row.status == "Finished":
        return len(spine) - 1, 1.0
    return bookmark_position(spine, row.bookmark_source, row.progress_percent, row.content_percent)


def bookmark_position(
    spine: list[int], source: str | None, progress_percent: float | None, content_percent: float | None
) -> tuple[int, float] | None:
    """Map a Kobo bookmark onto the book's chapters.

    ``Location.Source`` names the content file (``OEBPS/chapter-N.xhtml``, kept
    by kepubify) and ``ContentSourceProgressPercent`` the position inside it.
    Without a source, the overall ``ProgressPercent`` picks the chapter.
    """
    if not spine:
        return None
    match = CHAPTER_FILE.search(source or "")
    if match:
        index = min(max(int(match.group(1)) - 1, 0), len(spine) - 1)
        return index, min(max((content_percent or 0) / 100, 0), 1)
    if progress_percent is None:
        return None
    exact = min(max(progress_percent / 100, 0), 1) * len(spine)
    index = min(int(exact), len(spine) - 1)
    return index, min(max(exact - index, 0), 1)


def _nexus_position(progress: ReadingProgress | None, spine: list[int]) -> tuple[int, float] | None:
    if progress is None or progress.chapter_number not in spine:
        return None
    return spine.index(progress.chapter_number), min(max((progress.percent or 0) / 100, 0), 1)


def _progress(db: Session, user_id: int, novel_id: int) -> ReadingProgress | None:
    return (
        db.query(ReadingProgress)
        .filter(ReadingProgress.user_id == user_id, ReadingProgress.novel_id == novel_id)
        .first()
    )


def reading_state(db: Session, device: KoboDevice, row: KoboSyncedBook) -> dict:
    """The furthest of the device's bookmark and the Nexus position, as a Kobo ReadingState."""
    spine = _spine(db, row)
    progress = _progress(db, device.user_id, row.novel_id)
    device_pos = _device_position(row, spine)
    nexus_pos = _nexus_position(progress, spine)

    if nexus_pos is not None and (device_pos is None or nexus_pos > device_pos):
        index, fraction = nexus_pos
        modified = progress.updated_at or utcnow()
        overall = round((index + fraction) / len(spine) * 100, 2)
        finished = index == len(spine) - 1 and fraction >= 0.99
        bookmark = {
            "LastModified": timestamp(modified),
            "ProgressPercent": overall,
            "ContentSourceProgressPercent": round(fraction * 100, 2),
            "Location": {"Value": "kobo.1.1", "Type": "KoboSpan", "Source": f"OEBPS/chapter-{index + 1}.xhtml"},
        }
        state_status = "Finished" if finished else "Reading"
    elif row.bookmark_at is not None:
        modified = row.bookmark_at
        bookmark = {"LastModified": timestamp(modified)}
        if row.progress_percent is not None:
            bookmark["ProgressPercent"] = row.progress_percent
        if row.content_percent is not None:
            bookmark["ContentSourceProgressPercent"] = row.content_percent
        if row.bookmark_value or row.bookmark_source:
            bookmark["Location"] = {
                "Value": row.bookmark_value or "",
                "Type": row.bookmark_type or "KoboSpan",
                "Source": row.bookmark_source or "",
            }
        state_status = row.status or "Reading"
    else:
        modified = row.created_at or utcnow()
        bookmark = {"LastModified": timestamp(modified)}
        state_status = "ReadyToRead"

    stamp = timestamp(modified)
    status_info = {"LastModified": stamp, "Status": state_status, "TimesStartedReading": 0 if state_status == "ReadyToRead" else 1}
    if state_status != "ReadyToRead":
        status_info["LastTimeStartedReading"] = stamp
    return {
        "EntitlementId": row.entitlement_id,
        "Created": timestamp(row.created_at),
        "LastModified": stamp,
        "PriorityTimestamp": stamp,
        "StatusInfo": status_info,
        "Statistics": {"LastModified": stamp},
        "CurrentBookmark": bookmark,
    }


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def apply_reading_state(db: Session, device: KoboDevice, row: KoboSyncedBook, state: dict) -> dict:
    """Store a bookmark PUT by the device; Nexus progress moves only when the device is further."""
    bookmark = state.get("CurrentBookmark") or {}
    status_info = state.get("StatusInfo") or {}
    if not isinstance(bookmark, dict) or not isinstance(status_info, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed reading state")
    location = bookmark.get("Location") or {}
    if not isinstance(location, dict):
        location = {}

    now = utcnow()
    result = {"EntitlementId": row.entitlement_id, "LastModified": timestamp(now), "PriorityTimestamp": timestamp(now)}
    if bookmark:
        row.progress_percent = _number(bookmark.get("ProgressPercent"))
        row.content_percent = _number(bookmark.get("ContentSourceProgressPercent"))
        row.bookmark_source = str(location.get("Source") or "")[:255] or None
        row.bookmark_value = str(location.get("Value") or "")[:255] or None
        row.bookmark_type = str(location.get("Type") or "")[:40] or None
        row.bookmark_at = now
        result["CurrentBookmarkResult"] = {"Result": "Success"}
    if status_info.get("Status") in ("ReadyToRead", "Reading", "Finished"):
        row.status = status_info["Status"]
        row.bookmark_at = row.bookmark_at or now
        result["StatusInfoResult"] = {"Result": "Success"}
    if state.get("Statistics") is not None:
        result["StatisticsResult"] = {"Result": "Success"}

    spine = _spine(db, row)
    device_pos = _device_position(row, spine)
    progress = _progress(db, device.user_id, row.novel_id)
    nexus_pos = _nexus_position(progress, spine)
    if device_pos is not None and (nexus_pos is None or device_pos > nexus_pos):
        index, fraction = device_pos
        chapter = (
            db.query(Chapter)
            .filter(Chapter.novel_id == row.novel_id, Chapter.chapter_number == spine[index])
            .first()
        )
        if chapter is not None:
            progress = save_reading_progress(db, user_id=device.user_id, chapter=chapter, position=0, percent=fraction * 100)
    if nexus_pos is None or (device_pos is not None and device_pos >= nexus_pos):
        # The device knows the furthest position, so it is not sent back. When
        # Nexus is further, the next sync still offers the Nexus position.
        row.state_sent_at = max(filter(None, [now, progress.updated_at if progress else None]))
    db.commit()
    return result


# ---- sync ---------------------------------------------------------------------

@dataclass
class SyncResult:
    items: list[dict]
    more: bool


def sync(db: Session, device: KoboDevice, base: str, incoming_token: str | None) -> SyncResult:
    """Build one page of the library sync response and record what was sent."""
    rows = {row.novel_id: row for row in db.query(KoboSyncedBook).filter(KoboSyncedBook.device_id == device.id)}
    if not is_own_sync_token(incoming_token, device):
        # A new or reset device: send every book and reading state again.
        for row in rows.values():
            row.fingerprint = ""
            row.state_sent_at = None

    items: list[dict] = []
    budget = SYNC_ITEM_LIMIT
    more = False
    membership_changed = False
    novels = shelf_novels(db, device)
    wanted = {novel.id for novel in novels}

    for novel in novels:
        row = rows.get(novel.id)
        chapter_rows = epub_service._downloaded_chapter_rows(db, novel.id)
        if not chapter_rows:
            continue
        fp = epub_service.fingerprint(novel, chapter_rows)
        if row is not None and not row.removed and row.fingerprint == fp:
            continue
        if budget <= 0:
            more = True
            break
        is_new = row is None or row.removed or not row.fingerprint
        if row is None:
            row = KoboSyncedBook(device_id=device.id, novel_id=novel.id, entitlement_id=entitlement_id(novel.id))
            db.add(row)
            db.flush()
            rows[novel.id] = row
        try:
            file = book_file(db, novel)
        except epub_service.NoDownloadedChapters:
            continue
        row.fingerprint = file.built.build.fingerprint
        row.removed = False
        entry = {
            "BookEntitlement": book_entitlement(row, novel, removed=False),
            "BookMetadata": book_metadata(base, row, novel, file),
        }
        progress = _progress(db, device.user_id, novel.id)
        if progress is not None or row.bookmark_at is not None:
            entry["ReadingState"] = reading_state(db, device, row)
            row.state_sent_at = utcnow()
        items.append({"NewEntitlement" if is_new else "ChangedEntitlement": entry})
        membership_changed = membership_changed or is_new
        budget -= 1

    if not more:
        for row in rows.values():
            if row.removed or row.novel_id in wanted:
                continue
            if budget <= 0:
                more = True
                break
            novel = db.query(Novel).filter(Novel.id == row.novel_id).first()
            row.removed = True
            membership_changed = True
            if novel is None:
                continue
            items.append({"ChangedEntitlement": {"BookEntitlement": book_entitlement(row, novel, removed=True)}})
            budget -= 1

    for row in rows.values():
        if row.removed or not row.fingerprint:
            continue
        progress = _progress(db, device.user_id, row.novel_id)
        if progress is None or progress.updated_at is None:
            continue
        if row.state_sent_at is not None and progress.updated_at <= row.state_sent_at:
            continue
        if budget <= 0:
            more = True
            break
        items.append({"ChangedReadingState": {"ReadingState": reading_state(db, device, row)}})
        row.state_sent_at = max(utcnow(), progress.updated_at)
        budget -= 1

    full = not is_own_sync_token(incoming_token, device)
    if (membership_changed or full) and device.shelf_id is not None:
        shelf = db.query(Shelf).filter(Shelf.id == device.shelf_id).first()
        if shelf is not None:
            items.append(_shelf_tag(shelf, rows.values(), new=full))

    device.last_sync_at = utcnow()
    db.commit()
    return SyncResult(items=items, more=more)


def _shelf_tag(shelf: Shelf, rows, *, new: bool) -> dict:
    """The synced shelf as a Kobo collection holding the books on the device."""
    stamp = timestamp(shelf.updated_at or shelf.created_at)
    return {
        "NewTag" if new else "ChangedTag": {
            "Tag": {
                "Created": timestamp(shelf.created_at),
                "Id": tag_id(shelf.id),
                "Items": [
                    {"RevisionId": row.entitlement_id, "Type": "ProductRevisionTagItem"}
                    for row in rows
                    if not row.removed and row.fingerprint
                ],
                "LastModified": stamp,
                "Name": shelf.name,
                "Type": "UserTag",
            }
        }
    }
