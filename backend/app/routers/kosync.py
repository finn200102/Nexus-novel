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
import json
import time

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

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
    builds = _builds(db,user.id,document)
    if not builds:
        raise HTTPException(404,'Unknown document. Download it from the OPDS catalog first.')
    build=builds[0] if len(builds)==1 else None
    novel_ids={item.novel_id for item in builds}
    if len(novel_ids)!=1:raise HTTPException(409,'This sampled document identifier matches several books. Download a current unambiguous copy.')
    from app.services.ereader_identity_service import owner
    _,novel=owner(db,user.id,next(iter(novel_ids)))
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

    from app.services.ereader_identity_service import inferred
    index=_chapter_index(build.spine if build else [],update)
    if build is None:record.progress_review_reason='book_document_ambiguous'
    elif index is None:record.progress_review_reason='book_identity_unknown'
    else:
        record.progress_review_reason=inferred(db,user.id,build,index,update.percentage,
            operation=json.dumps(['kosync',document,update.model_dump()],sort_keys=True))
    db.commit()
    return {"document":document,"timestamp":timestamp,"nexus_progress":'review_required' if record.progress_review_reason else 'inferred',
        "review_reason":record.progress_review_reason}


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
        "nexus_progress":"review_required" if record.progress_review_reason else "inferred",
        "review_reason":record.progress_review_reason,
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


def _chapter_index(spine: list[int], update: KosyncProgressUpdate) -> int | None:
    if not spine:
        return None
    match = FRAGMENT.search(update.progress or "")
    if match:
        index = int(match.group(1)) - 1
        if not 0<=index<len(spine):return None
    else:
        index = int(update.percentage * len(spine))
    index = min(max(index, 0), len(spine) - 1)
    return index



def _web_position(db: Session, user: User, document: str, record: KosyncProgress | None) -> dict | None:
    """The web reader's chapter, when it is further along than the device.

    Reading only moves forward in practice, so a later chapter in the web app
    wins; KOReader then offers to jump there. The position is the start of
    that chapter (DocFragment N+1 for spine index N).
    """
    builds=_builds(db,user.id,document)
    if len(builds)!=1:return None
    build=builds[0]
    spine=list(build.spine or [])
    if not spine or _owned_novel(db,user,build.novel_id) is None:return None
    web = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == user.id,
        ReadingProgress.novel_id == build.novel_id,
    ).first()
    from app.services.ereader_identity_service import progress_index
    point=progress_index(db,user.id,build,web)
    if point is None:return None
    web_index=point[0]
    if record is not None:
        device_index=_chapter_index(spine,record)
        if device_index is not None and device_index>=web_index:return None
    return {
        "document": document,
        "progress": f"/body/DocFragment[{web_index + 1}]/body",
        "percentage": round(web_index / len(spine), 4),
        "device": "Nexus web reader",
        "device_id": "nexus-web",
        "timestamp": int(time.time()),
    }



def _builds(db,user_id,document):
    return db.query(EpubBuild).join(Novel,Novel.id==EpubBuild.novel_id).join(Library,Library.id==Novel.library_id).filter(
        Library.user_id==user_id,or_(EpubBuild.partial_md5==document,EpubBuild.partial_md5_lua==document)).order_by(EpubBuild.id).limit(2).all()
