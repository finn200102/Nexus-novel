from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from config.database import SessionLocal as SessionFactory
from config.database import get_db
from app.models.user import User
from ..schemas.chapter import Chapter as ChapterSchema
from ..schemas.chapter import ChapterCreate, ChapterUpdate, ChapterContent, ChapterDownloadJob as ChapterDownloadJobSchema, ChapterDownloadQueueRequest, ReadingProgressResponse, ReadingProgressUpdate, ReadingAnnotationCreate, ReadingAnnotationResponse
from app.models.chapter import Chapter
from app.models.novel import Novel
import app.services.chapter_services as chapter_services
import app.services.library_services as library_services
import app.services.novel_services as novel_services
import app.services.epub_service as epub_service
from app.auth.dependencies import get_current_user
from app.models.chapter import ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.models.reading_progress import ReadingProgress
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.services.download_job_service import claim_job, complete_job, fail_or_retry_job

import os
from dotenv import load_dotenv
from app.logging_config import get_logger

from app.services import metadata_client
import asyncio
from datetime import UTC, datetime
from io import BytesIO
import re


# Load environment variables
load_dotenv()

router = APIRouter(
    prefix="/chapter",
    tags=["chapters"],
    responses={404: {"description": "Not found"}},
)
logger = get_logger(__name__)


_PERMANENT_CHAPTER_FAILURES = {"locked", "removed"}


def _chapter_failure_details(error: str | None) -> tuple[str, bool]:
    """Recover typed source status stored on a chapter by the worker."""
    value = str(error or "")
    category, separator, _ = value.partition(":")
    category = category.strip().lower() if separator else "download_failed"
    return category.upper(), category not in _PERMANENT_CHAPTER_FAILURES


def extract_story_id_from_url(url: str | None, site_name: str | None) -> int | None:
    """Return the source's stable story/thread ID from a canonical work URL.

    Catalog imports intentionally create a lightweight manifest first.  Those
    records do not always carry the scraper's ``story_id`` yet, so chapter
    downloads must be able to recover it from the source URL.  Keep this
    source-aware rather than applying the old WebNovel-only expression to
    every connector.
    """
    value = str(url or "")
    patterns = {
        "fanfiction": r"/s/(\d+)(?:/|$)",
        "royalroad": r"/fiction/(\d+)(?:/|$)",
        "spacebattles": r"/threads/(?:[^/]+\.)?(\d+)(?:/|$)",
        "sufficientvelocity": r"/threads/(?:[^/]+\.)?(\d+)(?:/|$)",
        "questionablequesting": r"/threads/(?:[^/]+\.)?(\d+)(?:/|$)",
        "scribblehub": r"/series/(\d+)(?:/|$)",
        "archive": r"/works/(\d+)(?:/|$)",
        "webnovel": r"/book/[^_/?]+_(\d+)(?:[/?]|$)",
    }
    pattern = patterns.get(site_name or "")
    if not pattern:
        return None
    match = re.search(pattern, value, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def run_queued_download(job_id: int, db_session_factory):
    db = db_session_factory()
    try:
        job = claim_job(db, job_id)
        if not job:
            return
        chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
        if not chapter:
            fail_or_retry_job(db, job, "Chapter disappeared", error_code="CHAPTER_NOT_FOUND")
            return
        # Jobs created by the durable queue do not pass through the interactive
        # chapter endpoint, so establish the same processing state here before
        # the downloader opens its worker session.
        if chapter.content_status == ContentStatus.MISSING:
            chapter.content_status = ContentStatus.PROCESSING
            chapter.download_started_at = datetime.now(UTC)
            chapter.download_error = None
            db.commit()
        download_chapter_background(
            job.chapter_id,
            job.novel_id,
            chapter.chapter_number,
            job.library_id,
            db_session_factory,
        )
        db.expire_all()
        job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job_id).first()
        if not job or job.status == "cancelled":
            return
        chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
        if chapter and chapter.content_status == ContentStatus.PRESENT:
            complete_job(db, job)
        else:
            error = (chapter.download_error if chapter else "Chapter disappeared") or "Download failed"
            error_code, retryable = _chapter_failure_details(error)
            fail_or_retry_job(db, job, error, error_code=error_code, retryable=retryable)
    except Exception as exc:
        db.rollback()
        job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job_id).first()
        if job:
            fail_or_retry_job(db, job, str(exc), error_code="DOWNLOAD_EXCEPTION")
    finally:
        db.close()


def download_chapter_background(
    chapter_id: int,
    novel_id: int,
    chapter_number: int,
    library_id: int,
    db_session_factory,
):
    """Background task to download a single chapter."""
    import time

    db = db_session_factory()
    try:
        logger.info(
            "Starting background chapter download",
            chapter_id=chapter_id,
            novel_id=novel_id,
            chapter_number=chapter_number,
        )

        chapter = chapter_services.get_chapter_by_id(db, chapter_id)
        if not chapter:
            logger.error(
                "Chapter not found for background download", chapter_id=chapter_id
            )
            return

        # A cancellation/reset can happen while the background task waits for a
        # database connection. Do not resurrect a chapter the user cancelled.
        if chapter.content_status != ContentStatus.PROCESSING:
            logger.info(
                "Skipping chapter download because it is no longer processing",
                chapter_id=chapter_id,
                content_status=chapter.content_status.value,
            )
            return

        novel = novel_services.get_novel_by_id(db, novel_id)
        if not novel:
            logger.error("Novel not found for background download", novel_id=novel_id)
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.now(UTC),
                    "download_error": "Novel not found",
                },
            )
            return

        metadata_id = novel.metadata_id
        if not metadata_id:
            # Source access is deliberately centralized in Nexus Server. Old
            # local-only rows have no durable source identity to delegate.
            logger.error("Chapter has no metadata-server identity", novel_id=novel_id)
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.now(UTC),
                    "download_error": "Novel has no Nexus Server identity; refresh metadata first",
                },
            )
            return

        try:
            start_time = time.time()
            try:
                # Nexus Server owns source access. This keeps WebNovel and all
                # other source-policy decisions in one durable gateway.
                # This synchronous worker must not reuse the async metadata
                # client across a new event loop per chapter.  The sync helper
                # still calls only Nexus Server, which remains the sole owner
                # of external source access.
                fetched = metadata_client.fetch_public_chapter_text_sync(int(metadata_id), chapter_number) if metadata_id else None
                if not fetched:
                    raise RuntimeError("Chapter has no metadata-server identity")
            except asyncio.TimeoutError:
                logger.error(
                    "Chapter download timed out",
                    chapter_id=chapter_id,
                    timeout_seconds=os.getenv("NEXUS_CHAPTER_DOWNLOAD_TIMEOUT", "180"),
                )
                chapter_services.update_chapter(
                    db,
                    chapter_id,
                    {
                        "content_status": ContentStatus.FAILED,
                        "download_finished_at": datetime.now(UTC),
                        "download_error": f"Download timed out after {os.getenv('NEXUS_CHAPTER_DOWNLOAD_TIMEOUT', '180')} seconds",
                    },
                )
                return
            elapsed = time.time() - start_time
            logger.info(
                f"Chapter download took {elapsed:.2f} seconds", chapter_id=chapter_id
            )

            chapter_data = {
                "content": fetched.get("text"),
                "title": fetched.get("title") or chapter.title,
            }

            if chapter_data:
                chapter_data["content_status"] = ContentStatus.PRESENT
                chapter_data["download_finished_at"] = datetime.now(UTC)
                chapter_services.update_chapter(db, chapter_id, chapter_data)
                logger.info(
                    "Background chapter download completed",
                    chapter_id=chapter_id,
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                )
            else:
                chapter_services.update_chapter(
                    db,
                    chapter_id,
                    {
                        "content_status": ContentStatus.FAILED,
                        "download_finished_at": datetime.now(UTC),
                        "download_error": "No data returned from scraper",
                    },
                )
                logger.error(
                    "Background chapter download failed - no data returned",
                    chapter_id=chapter_id,
                )
        except metadata_client.ChapterSourceError as exc:
            error_msg = f"{exc.category}: {exc}"
            logger.warning(
                "Background chapter source outcome",
                chapter_id=chapter_id,
                category=exc.category,
                retryable=exc.retryable,
            )
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.now(UTC),
                    "download_error": error_msg,
                },
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Background chapter download failed",
                chapter_id=chapter_id,
                error=error_msg,
            )
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.now(UTC),
                    "download_error": error_msg,
                },
            )
    except Exception as e:
        error_msg = str(e)
        logger.error(
            "Background chapter download error",
            chapter_id=chapter_id,
            error=error_msg,
        )
        try:
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.utcnow(),
                    "download_error": error_msg,
                },
            )
        except Exception:
            pass
    finally:
        db.close()


def supported_src(url):
    supported = [
        "www.royalroad.com",
        "forums.spacebattles.com",
        "www.fanfiction.net",
        "archiveofourown.org",
        "www.webnovel.com",
        "forums.sufficientvelocity.com",
        "forum.questionablequesting.com",
        "www.scribblehub.com",
    ]

    def check_url_supported(url):
        for s in supported:
            if s in url:
                return True
        return False

    return check_url_supported(url)


def get_site_name_from_url(url):
    if "royalroad" in url:
        return "royalroad"
    if "fanfiction" in url:
        return "fanfiction"
    if "spacebattles" in url:
        return "spacebattles"
    if "archiveofourown" in url:
        return "archive"
    if "webnovel" in url:
        return "webnovel"
    if "sufficientvelocity" in url:
        return "sufficientvelocity"
    if "questionablequesting" in url:
        return "questionablequesting"
    if "scribblehub" in url:
        return "scribblehub"
    return None


@router.post("/", response_model=ChapterSchema, status_code=status.HTTP_201_CREATED)
def add_chapter(
    chapter: ChapterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = chapter_services.get_chapter_by_chapter_number(
        db, chapter.chapter_number, chapter.novel_id
    )

    if query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Chapter already exists"
        )
    # Create chapter data dictionary
    chapter_data = {
        "novel_id": chapter.novel_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "content_status": chapter.content_status.value,
    }
    new_chapter = chapter_services.create_chapter(db, chapter_data)

    return new_chapter


@router.get(
    "/download/{library_id}/{novel_id:int}/{chapter_number:int}",
    response_model=ChapterSchema,
)
def download_chapter(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from config.database import SessionLocal as SessionFactory

    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    if chapter.content_status == ContentStatus.PRESENT:
        return chapter
    if chapter.content_status == ContentStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chapter download is already in progress",
        )

    chapter_services.update_chapter(
        db,
        chapter.id,
        {
            "content_status": ContentStatus.PROCESSING,
            "download_started_at": datetime.now(UTC),
            "download_finished_at": None,
            "download_error": None,
            "retry_count": (chapter.retry_count or 0) + 1,
        },
    )
    db.refresh(chapter)

    background_tasks.add_task(
        download_chapter_background,
        chapter.id,
        novel_id,
        chapter_number,
        library_id,
        SessionFactory,
    )

    return chapter


@router.post("/queue/{library_id:int}/{novel_id:int}", response_model=list[ChapterDownloadJobSchema])
def queue_chapter_downloads(
    library_id: int,
    novel_id: int,
    request: ChapterDownloadQueueRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if request.count < 1 or request.count > 100:
        raise HTTPException(status_code=400, detail="Download count must be between 1 and 100")
    library = library_services.get_library_by_id(db, library_id)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not library or library.user_id != current_user.id or not novel or novel.library_id != library_id:
        raise HTTPException(status_code=404, detail="Novel not found")

    existing_jobs = {
        job.chapter_id
        for job in db.query(ChapterDownloadJob)
        .filter(
            ChapterDownloadJob.user_id == current_user.id,
            ChapterDownloadJob.novel_id == novel_id,
            ChapterDownloadJob.status.in_(["queued", "processing", "retry_wait"]),
        )
        .all()
    }
    candidates = (
        db.query(Chapter)
        .filter(
            Chapter.novel_id == novel_id,
            Chapter.content_status == ContentStatus.MISSING,
            ~Chapter.id.in_(existing_jobs or {-1}),
        )
        .order_by(Chapter.chapter_number.asc())
        .limit(request.count)
        .all()
    )
    jobs = []
    for chapter in candidates:
        job = ChapterDownloadJob(
            user_id=current_user.id,
            library_id=library_id,
            novel_id=novel_id,
            chapter_id=chapter.id,
        )
        db.add(job)
        jobs.append(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
        background_tasks.add_task(run_queued_download, job.id, SessionFactory)
    return jobs


@router.get("/queue/{novel_id:int}", response_model=list[ChapterDownloadJobSchema])
def get_chapter_download_queue(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(ChapterDownloadJob)
        .filter(
            ChapterDownloadJob.novel_id == novel_id,
            ChapterDownloadJob.user_id == current_user.id,
        )
        .order_by(ChapterDownloadJob.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/progress/{novel_id:int}", response_model=ReadingProgressResponse | None)
def get_reading_progress(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    return db.query(ReadingProgress).filter(
        ReadingProgress.user_id == current_user.id,
        ReadingProgress.novel_id == novel_id,
    ).first()


@router.get("/novel/{novel_id:int}/export.epub")
def export_novel_epub(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    chapters = epub_service.downloaded_chapters(db, novel_id)
    if not chapters:
        raise HTTPException(status_code=409, detail="Download at least one chapter before exporting")

    package = BytesIO(epub_service.render_epub(novel, chapters))
    filename = f"{(novel.title or 'nexus-novel').replace(' ', '-').lower()}.epub"
    return StreamingResponse(package, media_type="application/epub+zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/progress/recent")
def list_recent_reading_progress(
    limit: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Last-read novels for the Home "Continue reading" row, newest first."""
    library_ids = [library.id for library in current_user.libraries]
    if not library_ids:
        return []
    rows = (
        db.query(ReadingProgress, Novel)
        .join(Novel, Novel.id == ReadingProgress.novel_id)
        .filter(ReadingProgress.user_id == current_user.id, Novel.library_id.in_(library_ids))
        .order_by(ReadingProgress.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "novel_id": novel.id,
            "novel_title": novel.title,
            "library_id": novel.library_id,
            "chapter_number": progress.chapter_number,
            "position": progress.position,
            "percent": progress.percent,
            "updated_at": progress.updated_at,
        }
        for progress, novel in rows
    ]


@router.put("/progress/{novel_id:int}", response_model=ReadingProgressResponse)
def update_reading_progress(
    novel_id: int,
    update: ReadingProgressUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    chapter = db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number == update.chapter_number,
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == current_user.id,
        ReadingProgress.novel_id == novel_id,
    ).first()
    if not progress:
        progress = ReadingProgress(user_id=current_user.id, novel_id=novel_id)
        db.add(progress)
    progress.chapter_id = chapter.id
    progress.chapter_number = update.chapter_number
    progress.position = max(update.position, 0)
    progress.percent = min(max(update.percent, 0), 100)
    # Persist a compact history point once per chapter/day. It powers streaks
    # and velocity without recording raw scrolling or text selection data.
    from datetime import date
    today = date.today()
    history = db.query(ReadingHistory).filter(
        ReadingHistory.user_id == current_user.id,
        ReadingHistory.novel_id == novel_id,
        ReadingHistory.chapter_number == update.chapter_number,
        func.date(ReadingHistory.reading_date) == today.isoformat(),
    ).first()
    if history:
        history.max_percent = max(history.max_percent or 0, round(progress.percent))
    else:
        db.add(ReadingHistory(
            user_id=current_user.id,
            novel_id=novel_id,
            chapter_number=update.chapter_number,
            reading_date=datetime.combine(today, datetime.min.time()),
            max_percent=round(progress.percent),
        ))
    db.commit()
    db.refresh(progress)
    return progress


@router.get("/history/{novel_id:int}")
def get_reading_history(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    rows = db.query(ReadingHistory).filter(
        ReadingHistory.user_id == current_user.id,
        ReadingHistory.novel_id == novel_id,
    ).order_by(ReadingHistory.reading_date.desc()).limit(365).all()
    dates = sorted({row.reading_date.date() for row in rows if row.reading_date})
    streak = 0
    from datetime import date, timedelta
    cursor = date.today()
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return {
        "chapters_touched": len({row.chapter_number for row in rows}),
        "active_days": len(dates),
        "current_streak_days": streak,
        "events": [{"chapter_number": row.chapter_number, "date": row.reading_date.date().isoformat(), "percent": row.max_percent} for row in rows],
    }


@router.get("/recap/{novel_id:int}")
def spoiler_safe_recap(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A deterministic recap that cannot read beyond the saved position."""
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == current_user.id,
        ReadingProgress.novel_id == novel_id,
    ).first()
    completed_through = int(progress.chapter_number or 0) if progress else 0
    chapters = db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number <= completed_through,
    ).order_by(Chapter.chapter_number.asc()).all()
    annotations = db.query(ReadingAnnotation).filter(
        ReadingAnnotation.user_id == current_user.id,
        ReadingAnnotation.novel_id == novel_id,
        ReadingAnnotation.chapter_id.in_([chapter.id for chapter in chapters] or [-1]),
    ).order_by(ReadingAnnotation.created_at.desc()).limit(12).all()
    return {
        "spoiler_boundary_chapter": completed_through,
        "summary": f"You have reached chapter {completed_through}. This recap only includes titles and your annotations from earlier chapters.",
        "chapters": [{"number": row.chapter_number, "title": row.title} for row in chapters[-12:]],
        "annotations": [{"chapter_number": row.chapter.chapter_number, "quote": row.quote, "note": row.note, "type": row.annotation_type} for row in annotations],
    }


@router.get("/annotations/{novel_id:int}", response_model=list[ReadingAnnotationResponse])
def get_reading_annotations(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    annotations = db.query(ReadingAnnotation).filter(
        ReadingAnnotation.user_id == current_user.id,
        ReadingAnnotation.novel_id == novel_id,
    ).order_by(ReadingAnnotation.created_at.desc()).all()
    return [
        {**annotation.__dict__, "chapter_number": annotation.chapter.chapter_number}
        for annotation in annotations
    ]


@router.post("/annotations/{novel_id:int}", response_model=ReadingAnnotationResponse, status_code=status.HTTP_201_CREATED)
def create_reading_annotation(
    novel_id: int,
    annotation: ReadingAnnotationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    if annotation.annotation_type not in {"bookmark", "note", "highlight"}:
        raise HTTPException(status_code=422, detail="Unsupported annotation type")
    chapter = db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number == annotation.chapter_number,
    ).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    item = ReadingAnnotation(
        user_id=current_user.id,
        novel_id=novel_id,
        chapter_id=chapter.id,
        annotation_type=annotation.annotation_type,
        position=max(annotation.position, 0),
        percent=min(max(annotation.percent, 0), 100),
        quote=annotation.quote,
        note=annotation.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {**item.__dict__, "chapter_number": chapter.chapter_number}


@router.delete("/annotations/{annotation_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reading_annotation(
    annotation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = db.query(ReadingAnnotation).filter(
        ReadingAnnotation.id == annotation_id,
        ReadingAnnotation.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(item)
    db.commit()


@router.get("/{novel_id:int}", response_model=list[ChapterSchema])
def get_chapters(
    novel_id: int,
    title: str = None,
    skip: int = 0,
    limit: int = 1000,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get chapters with pagination and optional filtering
    """

    # Start with base query
    query = chapter_services.get_chapters_by_novel_id(db, novel_id=novel_id)

    # Apply filters if provided
    if title:
        query = query.filter(Chapter.title == title)

    # Apply pagination and return results
    chapters = query.offset(skip).limit(limit).all()
    return chapters


@router.get("/{novel_id:int}/{chapter_number:int}", response_model=ChapterSchema)
def get_chapter_by_number(
    novel_id: int,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a single chapter by Number
    """

    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    return chapter


def check_chapter(
    db: Session, novel_id: int, chapter_number: int, user: User
) -> Chapter:
    chapter = (
        db.query(Chapter)
        .filter_by(novel_id=novel_id, chapter_number=chapter_number)
        .first()
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    novel = db.query(Novel).filter_by(id=novel_id).first()
    if not novel or novel.library_id not in [lib.id for lib in user.libraries]:
        raise HTTPException(
            status_code=403, detail="Access denied to this novel/chapter"
        )

    return chapter


@router.get(
    "/content/library/{library_id:int}/{novel_id:int}/{chapter_number:int}",
    response_model=ChapterContent,
)
def get_chapter_content(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a single chapter content by library ID, novel ID, and chapter number.
    """
    # Validate that the library exists and belongs to the user
    library = library_services.get_library_by_id(db, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {library_id} not found",
        )
    if library.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission for this library",
        )

    # Fetch the novel
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found in this library",
        )

    # Fetch the chapter
    chapter = chapter_services.get_chapter_by_chapter_number(
        db, chapter_number, novel_id
    )
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter_number} not found in novel {novel_id}",
        )
    if not chapter.content:
        raise HTTPException(status_code=409, detail="Chapter content is not downloaded")

    return ChapterContent(
        id=chapter.id,
        novel_id=chapter.novel_id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        content=chapter.content,
    )


@router.delete("/{chapter_id:int}", response_model=ChapterSchema)
def delete_chapter_by_id(
    chapter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a single chapter by ID
    """
    chapter = chapter_services.get_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="chapter not found"
        )
    check_chapter(db, chapter.novel_id, chapter.chapter_number, current_user)
    chapter_services.delete_chapter(db, chapter_id)
    return chapter


@router.put("/", response_model=ChapterSchema)
def update_chapter(
    chapter: ChapterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a single chapter by chapter_data
    """
    chapter_data = {"title": chapter.title, "content_status": chapter.content_status}
    ch = chapter_services.get_chapter_by_id(db, chapter.id)
    check_chapter(db, chapter.novel_id, ch.chapter_number, current_user)

    chapter_services.update_chapter(db, chapter.id, chapter_data)
    chapter = chapter_services.get_chapter_by_id(db, chapter.id)
    return chapter


@router.patch("/{chapter_id:int}/status", response_model=ChapterSchema)
def reset_chapter_status(
    chapter_id: int,
    content_status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reset a chapter's content_status (e.g., from FAILED to MISSING, or reset stuck PROCESSING)
    """
    chapter = chapter_services.get_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Chapter not found"
        )
    check_chapter(db, chapter.novel_id, chapter.chapter_number, current_user)

    chapter_services.update_chapter(db, chapter_id, {"content_status": content_status})
    chapter = chapter_services.get_chapter_by_id(db, chapter_id)
    return chapter


@router.get("/novel/{novel_id}/download-status")
def get_novel_download_status(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get download status for all chapters of a novel.
    Returns counts and lists of chapters by status.
    """
    chapters = chapter_services.get_chapters_by_novel_id(db, novel_id).all()
    if not chapters:
        return {
            "total": 0,
            "present": 0,
            "missing": 0,
            "processing": 0,
            "failed": 0,
            "chapters": [],
            "processing_chapters": [],
            "failed_chapters": [],
        }

    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found"
        )

    processing_chapters = []
    failed_chapters = []
    present_count = 0
    missing_count = 0

    for chapter in chapters:
        if chapter.content_status == ContentStatus.PRESENT:
            present_count += 1
        elif chapter.content_status == ContentStatus.MISSING:
            missing_count += 1
        elif chapter.content_status == ContentStatus.PROCESSING:
            processing_chapters.append(
                {
                    "id": chapter.id,
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "started_at": chapter.download_started_at.isoformat()
                    if chapter.download_started_at
                    else None,
                    "retry_count": chapter.retry_count or 0,
                }
            )
        elif chapter.content_status == ContentStatus.FAILED:
            failed_chapters.append(
                {
                    "id": chapter.id,
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "error": chapter.download_error,
                    "retry_count": chapter.retry_count or 0,
                    "finished_at": chapter.download_finished_at.isoformat()
                    if chapter.download_finished_at
                    else None,
                }
            )

    return {
        "total": len(chapters),
        "present": present_count,
        "missing": missing_count,
        "processing": len(processing_chapters),
        "failed": len(failed_chapters),
        "processing_chapters": processing_chapters,
        "failed_chapters": failed_chapters,
    }


@router.delete("/{chapter_id:int}/download")
def cancel_chapter_download(
    chapter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cancel a chapter download and reset it to MISSING status.
    """
    chapter = chapter_services.get_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Chapter not found"
        )
    check_chapter(db, chapter.novel_id, chapter.chapter_number, current_user)

    chapter_services.update_chapter(
        db,
        chapter_id,
        {
            "content_status": ContentStatus.MISSING,
            "download_started_at": None,
            "download_finished_at": None,
            "download_error": None,
        },
    )

    return {"message": "Download cancelled", "chapter_id": chapter_id}


@router.post("/novel/{novel_id}/cancel-all-downloads")
def cancel_all_downloads(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cancel all in-progress chapter downloads for a novel.
    Resets PROCESSING chapters to MISSING.
    """
    chapters = chapter_services.get_chapters_by_novel_id(db, novel_id)
    if not chapters:
        return {"message": "No chapters found", "cancelled": 0}

    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found"
        )

    cancelled_count = 0
    for chapter in chapters:
        if chapter.content_status == ContentStatus.PROCESSING:
            chapter_services.update_chapter(
                db,
                chapter.id,
                {
                    "content_status": ContentStatus.MISSING,
                    "download_started_at": None,
                    "download_finished_at": None,
                    "download_error": None,
                },
            )
            cancelled_count += 1

    return {"message": "Downloads cancelled", "cancelled": cancelled_count}
