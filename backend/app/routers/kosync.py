"""KOReader progress sync (kosync protocol) mapped onto Nexus reading progress.

Clients authenticate with ``x-auth-user`` and ``x-auth-key``, where the key is
the MD5 of an app password with the ``kosync`` scope. Documents are identified
by KOReader's partial MD5 of the EPUB; every EPUB we serve records its own
partial MD5, so any copy downloaded from OPDS can be matched to its novel.

Progress strings are KOReader xpointers. ``DocFragment[N]`` names the Nth spine
document, which is the Nth chapter we put in the book. Without an xpointer, the
overall percentage picks the chapter.
"""

import re
import time

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.ereader import EpubBuild, KosyncProgress
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.schemas.ereader import KosyncProgressUpdate
from app.services import app_password_service
from config.database import get_db

router = APIRouter(
    prefix="/kosync",
    tags=["kosync"],
    responses={404: {"description": "Not found"}},
)

FRAGMENT = re.compile(r"DocFragment\[(\d+)\]")


def get_kosync_user(request: Request, db: Session = Depends(get_db)) -> User:
    return app_password_service.authenticate_kosync(
        db,
        request,
        request.headers.get("x-auth-user", ""),
        request.headers.get("x-auth-key", ""),
    )


@router.post("/users/create")
def create_user():
    # Accounts are made in the web app; kosync registration is never allowed.
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"message": "Registration is not available on this server"},
    )


@router.get("/users/auth")
def authorize(user: User = Depends(get_kosync_user)):
    return {"authorized": "OK"}


@router.put("/syncs/progress")
def put_progress(
    update: KosyncProgressUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_kosync_user),
):
    document = update.document.strip().lower()
    build = (
        db.query(EpubBuild)
        .filter(or_(EpubBuild.partial_md5 == document, EpubBuild.partial_md5_lua == document))
        .order_by(EpubBuild.id.desc())
        .first()
    )
    novel = _owned_novel(db, user, build.novel_id) if build is not None else None
    if build is None or novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown document. Download it from the OPDS catalog first.")

    chapter_number = _chapter_number(build.spine or [], update)
    chapter = db.query(Chapter).filter(Chapter.novel_id == novel.id, Chapter.chapter_number == chapter_number).first()
    timestamp = int(time.time())

    record = (
        db.query(KosyncProgress)
        .filter(KosyncProgress.user_id == user.id, KosyncProgress.document == document)
        .first()
    )
    if record is None:
        record = KosyncProgress(user_id=user.id, document=document, novel_id=novel.id)
        db.add(record)
    record.novel_id = novel.id
    record.progress = update.progress[:512]
    record.percentage = update.percentage
    record.device = update.device[:100]
    record.device_id = update.device_id[:100]

    if chapter is not None:
        _store_reading_progress(db, user, novel.id, chapter, update.percentage)
    db.commit()
    return {"document": document, "timestamp": timestamp}


@router.get("/syncs/progress/{document}")
def get_progress(document: str, db: Session = Depends(get_db), user: User = Depends(get_kosync_user)):
    document = document.strip().lower()
    record = (
        db.query(KosyncProgress)
        .filter(KosyncProgress.user_id == user.id, KosyncProgress.document == document)
        .first()
    )
    web = _web_position(db, user, document, record)
    if web is not None:
        return web
    if record is None:
        return {}
    return {
        "document": record.document,
        "progress": record.progress,
        "percentage": record.percentage,
        "device": record.device,
        "device_id": record.device_id,
        "timestamp": int(record.updated_at.replace(tzinfo=UTC).timestamp()) if record.updated_at else 0,
    }


# ---- helpers ------------------------------------------------------------

def _owned_novel(db: Session, user: User, novel_id: int) -> Novel | None:
    return (
        db.query(Novel)
        .join(Library, Library.id == Novel.library_id)
        .filter(Novel.id == novel_id, Library.user_id == user.id)
        .first()
    )


def _chapter_number(spine: list[int], update: KosyncProgressUpdate) -> int | None:
    if not spine:
        return None
    match = FRAGMENT.search(update.progress or "")
    if match:
        index = int(match.group(1)) - 1
    else:
        index = int(update.percentage * len(spine))
    index = min(max(index, 0), len(spine) - 1)
    return spine[index]


def _store_reading_progress(db: Session, user: User, novel_id: int, chapter: Chapter, fraction: float) -> None:
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == user.id,
        ReadingProgress.novel_id == novel_id,
    ).first()
    if progress is None:
        progress = ReadingProgress(user_id=user.id, novel_id=novel_id)
        db.add(progress)
    progress.chapter_id = chapter.id
    progress.chapter_number = chapter.chapter_number
    progress.position = 0
    progress.percent = min(max(fraction * 100, 0), 100)


def _web_position(db: Session, user: User, document: str, record: KosyncProgress | None) -> dict | None:
    """The web reader's chapter, when it is further along than the device.

    Reading only moves forward in practice, so a later chapter in the web app
    wins; KOReader then offers to jump there. The position is the start of
    that chapter (DocFragment N+1 for spine index N).
    """
    build = (
        db.query(EpubBuild)
        .filter(or_(EpubBuild.partial_md5 == document, EpubBuild.partial_md5_lua == document))
        .order_by(EpubBuild.id.desc())
        .first()
    )
    spine = list(build.spine or []) if build is not None else []
    if not spine or _owned_novel(db, user, build.novel_id) is None:
        return None
    web = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == user.id,
        ReadingProgress.novel_id == build.novel_id,
    ).first()
    if web is None or web.chapter_number not in spine:
        return None
    web_index = spine.index(web.chapter_number)
    if record is not None:
        device_chapter = _chapter_number(spine, record)
        if device_chapter in spine and spine.index(device_chapter) >= web_index:
            return None
    return {
        "document": document,
        "progress": f"/body/DocFragment[{web_index + 1}]/body",
        "percentage": round(web_index / len(spine), 4),
        "device": "Nexus web reader",
        "device_id": "nexus-web",
        "timestamp": int(time.time()),
    }
