from app.routers.chapter_manifest import router as manifest_router
from typing import Literal
from app.schemas.chapter_reading import ChapterReadingSummaryResponse, ChapterReadingPageResponse
from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Query, Path, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, defer
from config.database import SessionLocal as SessionFactory
from config.database import get_db
from app.models.user import User
from ..schemas.chapter import Chapter as ChapterSchema
from ..schemas.chapter import ChapterCreate, ChapterUpdate, ChapterContent, ChapterDownloadJob as ChapterDownloadJobSchema, ChapterDownloadQueueRequest, ReadingProgressResponse, ReadingProgressUpdate, ReadingAnnotationCreate, ReadingAnnotationResponse
from ..schemas.chapter import (
    ChapterVersionsPage, RecentReadingProgressResponse, ReadingHistoryResponse, ChapterNavigationResponse,
    ChapterRecapResponse, NovelDownloadStatusResponse,
    ChapterDownloadCancelledResponse, ChapterDownloadsCancelledResponse,
)
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
from app.services.reading_progress_service import save_reading_progress
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

# Chapter numbers can be negative (prologues). Keep their path parameters
# unconstrained at routing time; FastAPI validates the annotated integer.
router = APIRouter(
    prefix="/chapter",
    tags=["chapters"],
    responses={404: {"description": "Not found"}},
)
logger = get_logger(__name__)


_PERMANENT_CHAPTER_FAILURES = {"locked", "removed", "chapter_manifest_changed", "chapter_review_required", "chapter_identity_required"}


def _owned_novel(db: Session, novel_id: int, user: User):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id not in [library.id for library in user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")
    return novel


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
    from app.services.job_lease import heartbeat

    owner = None
    attempt = None
    db = db_session_factory()
    try:
        job = claim_job(db, job_id)
        if not job:
            return
        owner = job.lease_owner
        if not job.chapter_identity:
            fail_or_retry_job(db,job,'Review and bind this chapter to its source before downloading.',error_code='CHAPTER_REVIEW_REQUIRED',retryable=False)
            return
        from app.services.chapter_download_identity_service import capture,matches
        chapter = db.query(Chapter).filter(Chapter.id == job.chapter_id).first()
        if not chapter:
            fail_or_retry_job(db, job, "Chapter disappeared", error_code="CHAPTER_NOT_FOUND")
            return
        current=capture(db,chapter,user_id=job.user_id,library_id=job.library_id)
        if not matches(current,job.chapter_identity) or not current.get('metadata_manifest_key') or not current.get('metadata_chapter_key') or not isinstance(current.get('metadata_source'),dict):
            fail_or_retry_job(db,job,'Review the changed chapter source before downloading.',error_code='CHAPTER_REVIEW_REQUIRED',retryable=False)
            return
        # Jobs created by the durable queue do not pass through the interactive
        # chapter endpoint, so establish the same processing state here before
        # the downloader opens its worker session.
        if chapter.content_status == ContentStatus.MISSING:
            chapter.content_status = ContentStatus.PROCESSING
            chapter.download_started_at = datetime.now(UTC)
            chapter.download_error = None
            db.commit()
        attempt=job.attempt_count
        arguments=(job.chapter_id,job.novel_id,chapter.chapter_number,job.library_id,db_session_factory)
        captured_identity=dict(job.chapter_identity)
        captured_user=job.user_id
        db.rollback()  # The coordinator also releases its read transaction.
        with heartbeat(db_session_factory, ChapterDownloadJob, job_id, owner):
            download_chapter_background(*arguments,expected_identity=captured_identity,
                expected_user_id=captured_user,job_id=job_id,lease_owner=owner,attempt=attempt)
        db.expire_all()
        job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job_id).first()
        if not job or job.status != "processing" or job.lease_owner != owner or job.attempt_count!=attempt:
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
        if job and job.status == "processing" and job.lease_owner == owner and (attempt is None or job.attempt_count==attempt):
            fail_or_retry_job(db, job, str(exc), error_code="DOWNLOAD_EXCEPTION")
    finally:
        db.close()


def download_chapter_background(
    chapter_id: int,
    novel_id: int,
    chapter_number: int,
    library_id: int,
    db_session_factory,
    *,expected_identity=None,expected_user_id=None,job_id=None,lease_owner=None,attempt=None,
):
    """Download only a bound source lifecycle and fence every local write."""
    import time

    db = db_session_factory()
    publication=None
    captured_version=None
    from app.services.chapter_download_identity_service import capture,matches,publish,fenced_chapter
    from app.services.chapter_identity_service import source_version
    def guarded_update(_db,_chapter_id,value):
        if publication is None:return False
        return publish(db,value=value,expected_source_version=captured_version,**publication)
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
            guarded_update(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.now(UTC),
                    "download_error": "Novel not found",
                },
            )
            return

        from app.models.library import Library
        actual_owner=db.query(Library.user_id).filter(Library.id==library_id,Library.id==novel.library_id).scalar()
        if actual_owner is None or expected_user_id is not None and expected_user_id!=actual_owner:return
        current=capture(db,chapter,user_id=actual_owner,library_id=library_id)
        if expected_identity is None:return
        if not matches(current,expected_identity) or not current.get('metadata_manifest_key') or not current.get('metadata_chapter_key') or not isinstance(current.get('metadata_source'),dict):
            return
        publication=dict(user_id=actual_owner,library_id=library_id,novel_id=novel_id,chapter_id=chapter_id,
            expected=expected_identity,job_id=job_id,lease_owner=lease_owner,attempt=attempt)
        if fenced_chapter(db,**publication) is None:return
        captured_version=source_version(chapter)
        fallback_title=chapter.title
        metadata_id = novel.metadata_id
        db.rollback()  # No database transaction survives delegated source I/O.
        if not metadata_id:
            # Source access is deliberately centralized in Nexus Server. Old
            # local-only rows have no durable source identity to delegate.
            logger.error("Chapter has no metadata-server identity", novel_id=novel_id)
            guarded_update(
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
                fetched = metadata_client.fetch_public_chapter_text_sync(int(metadata_id), chapter_number,expected_manifest_key=expected_identity['metadata_manifest_key'],expected_chapter_key=expected_identity['metadata_chapter_key'],expected_source=expected_identity['metadata_source']) if metadata_id else None
                if not fetched:
                    raise RuntimeError("Chapter has no metadata-server identity")
            except asyncio.TimeoutError:
                logger.error(
                    "Chapter download timed out",
                    chapter_id=chapter_id,
                    timeout_seconds=os.getenv("NEXUS_CHAPTER_DOWNLOAD_TIMEOUT", "180"),
                )
                guarded_update(
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
                "title": fetched.get("title") or fallback_title,
            }
            from app.services.chapter_document import from_html, from_text
            chapter_data["document"] = from_html(fetched["html"]) if fetched.get("html") else from_text(fetched.get("text") or "")
            if isinstance(fetched.get("image_assets"), dict):
                # Asset derivatives remain in this reader-owned chapter, never
                # written back to the shared source catalog.
                chapter_data["document"]["image_assets"] = fetched["image_assets"]
            chapter_data["content"] = chapter_data["document"]["plain_text"]

            if chapter_data:
                chapter_data["content_status"] = ContentStatus.PRESENT
                chapter_data["download_finished_at"] = datetime.now(UTC)
                guarded_update(db, chapter_id, chapter_data)
                logger.info(
                    "Background chapter download completed",
                    chapter_id=chapter_id,
                    novel_id=novel_id,
                    chapter_number=chapter_number,
                )
            else:
                guarded_update(
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
            guarded_update(
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
            guarded_update(
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
            guarded_update(
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
    from app.services.chapter_manifest_service import _lock,_active
    from app.services.chapter_identity_service import manifest_state,state_fields,conflict
    _lock(db,current_user.id,chapter.novel_id)
    state=manifest_state(db,chapter.novel_id,lock=True)
    header=state_fields(state)
    supplied=(chapter.expected_manifest_epoch,chapter.expected_manifest_revision)
    if state.identity_required or any(value is not None for value in supplied):
        if any(value is None for value in supplied):
            conflict('chapter_identity_required','Capture the current chapter-list identity before adding a chapter.',header)
        if supplied!=(header['manifest_epoch'],header['manifest_revision']):
            conflict('chapter_manifest_changed','The chapter list changed before this addition. Review the current list first.',header)
    if _active(db,current_user.id,chapter.novel_id):
        raise HTTPException(409,detail={'code':'active_work','message':'Wait for active downloads and generated work before adding a chapter.'})
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
    "/download/{library_id}/{novel_id:int}/{chapter_number}",
    response_model=ChapterSchema,
)
def download_chapter(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    background_tasks: BackgroundTasks,
    expected_chapter_key: str | None = Query(None,max_length=36),
    expected_manifest_epoch: str | None = Query(None,max_length=36),
    expected_manifest_revision: str | None = Query(None,max_length=19),
    expected_content_version: str | None = Query(None,pattern=r"^[a-f0-9]{64}$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from config.database import SessionLocal as SessionFactory

    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    from app.services.chapter_identity_service import check_write
    check_write(db,current_user.id,chapter,expected_chapter_key=expected_chapter_key,
        expected_manifest_epoch=expected_manifest_epoch,expected_manifest_revision=expected_manifest_revision,
        expected_content_version=expected_content_version,require_content_version=False)
    if chapter.content_status == ContentStatus.PRESENT:
        return chapter
    from app.services.chapter_download_identity_service import capture
    download_identity=capture(db,chapter,user_id=current_user.id,library_id=library_id)
    if not download_identity.get('metadata_manifest_key') or not download_identity.get('metadata_chapter_key') or not isinstance(download_identity.get('metadata_source'),dict):
        raise HTTPException(409,detail={'code':'chapter_review_required','message':'Review and bind this chapter to its source before downloading. Your saved originals are preserved.','review_path':f'/chapter/novel/{novel_id}/manifest-state'})
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
        expected_identity=download_identity,
        expected_user_id=current_user.id,
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
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == current_user.id,
        ReadingProgress.novel_id == novel_id,
    ).first()
    if progress is None:
        from app.services.reading_run_service import current_run, restore_progress
        progress = restore_progress(current_run(db, current_user.id, novel_id))
    return progress


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
    from urllib.parse import quote
    title = (novel.title or "nexus-novel").replace("\r", "").replace("\n", "")[:200]
    filename = re.sub(r"[^A-Za-z0-9._-]", "-", title).strip("-.") or "nexus-novel"
    disposition = f"attachment; filename=\"{filename}.epub\"; filename*=UTF-8''{quote(title + '.epub', safe='')}"
    return StreamingResponse(package, media_type="application/epub+zip", headers={"Content-Disposition": disposition})


@router.get("/progress/recent", response_model=list[RecentReadingProgressResponse], response_model_exclude_unset=True)
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
    chapter_query=db.query(Chapter).filter(Chapter.novel_id==novel_id)
    if update.expected_chapter_key is not None:
        chapter_query=chapter_query.execution_options(include_archived_chapters=True).filter(Chapter.chapter_key==update.expected_chapter_key)
    else:
        chapter_query=chapter_query.filter(Chapter.chapter_number==update.chapter_number)
    chapter=chapter_query.first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return save_reading_progress(db, user_id=current_user.id, chapter=chapter, position=update.position, percent=update.percent,
                                expected_revision=update.expected_revision, operation_id=update.operation_id,
                                device_id=update.device_id, block_id=update.block_id, content_version=update.content_version,
                                text_offset=update.text_offset, intent=update.intent, text_quote=update.text_quote,
                                quote_prefix=update.quote_prefix, quote_suffix=update.quote_suffix, locator_variant=update.locator_variant,
                                reading_run_key=update.reading_run_key,expected_chapter_key=update.expected_chapter_key,
                                expected_manifest_epoch=update.expected_manifest_epoch,expected_manifest_revision=update.expected_manifest_revision,
                                expected_content_version=update.expected_content_version,submitted_chapter_number=update.chapter_number)


@router.get("/history/{novel_id:int}", response_model=ReadingHistoryResponse, response_model_exclude_unset=True)
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
        "events": [{"chapter_key":row.chapter_key,"identity_inferred":row.identity_inferred,"chapter_number": row.chapter_number, "date": row.reading_date.date().isoformat(), "percent": row.max_percent} for row in rows],
    }


@router.get("/recap/{novel_id:int}", response_model=ChapterRecapResponse, response_model_exclude_unset=True)
def spoiler_safe_recap(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A deterministic recap bounded to the current reading run."""
    _owned_novel(db, novel_id, current_user)
    from app.services.private_reading_evidence import verified_chapters
    scope,verified=verified_chapters(db,current_user.id,novel_id,descending=True,max_verified=12)
    chapters=list(verified);chapters.reverse()
    versions={chapter.id:chapter.document['content_version'] for chapter in chapters}
    chapter_keys={chapter.id:chapter.chapter_key for chapter in chapters}
    annotations=db.query(ReadingAnnotation).filter(ReadingAnnotation.user_id==current_user.id,
        ReadingAnnotation.novel_id==novel_id,ReadingAnnotation.chapter_id.in_(list(versions) or [-1])).order_by(ReadingAnnotation.created_at.desc()).limit(100).all()
    numbers={chapter.id:chapter.chapter_number for chapter in chapters}
    safe_annotations=[row for row in annotations if row.chapter_key==chapter_keys[row.chapter_id] and row.locator_content_version==versions[row.chapter_id] and row.locator_variant is None][:12]
    return {'spoiler_boundary_chapter':scope.through_chapter,
        'summary':('There are no verified completed chapters in this reading yet.' if scope.through_chapter is None else f'This recap includes only current-version chapters confirmed read in this reading, through chapter {scope.through_chapter}.'),
        'chapters':[{'number':chapter.chapter_number,'title':chapter.title} for chapter in chapters],
        'annotations':[{'chapter_number':numbers[row.chapter_id],'quote':row.quote,'note':row.note,'type':row.annotation_type} for row in safe_annotations]}


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
    from app.services.chapter_identity_service import manifest_state,state_fields
    header=state_fields(manifest_state(db,novel_id))
    keys={annotation.chapter_key for annotation in annotations if annotation.chapter_key is not None}
    chapters={}
    # Chunk SQLite bind parameters while retaining archived originals. Never
    # trust a recycled numeric FK to identify the annotation's chapter.
    for start in range(0,len(keys),500):
        subset=list(keys)[start:start+500]
        chapters.update({row.chapter_key:row for row in db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.archived).execution_options(include_archived_chapters=True).filter(Chapter.novel_id==novel_id,Chapter.chapter_key.in_(subset))})
    return [{**annotation.__dict__,**header,"chapter_key":annotation.chapter_key,
        "chapter_number":chapters[annotation.chapter_key].chapter_number if annotation.chapter_key in chapters else annotation.chapter_number,
        "original_chapter_number":annotation.chapter_number,
        "archived":bool(chapters[annotation.chapter_key].archived) if annotation.chapter_key in chapters else False,
        "identity_unresolved":annotation.chapter_key not in chapters} for annotation in annotations]


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
    from app.services.chapter_identity_service import check_write
    check_write(db,current_user.id,chapter,expected_chapter_key=annotation.expected_chapter_key,
        expected_manifest_epoch=annotation.expected_manifest_epoch,expected_manifest_revision=annotation.expected_manifest_revision,
        expected_content_version=annotation.expected_content_version,require_content_version=True)
    item = ReadingAnnotation(
        user_id=current_user.id,
        novel_id=novel_id,
        chapter_id=chapter.id,
        annotation_type=annotation.annotation_type,
        position=max(annotation.position, 0),
        percent=min(max(annotation.percent, 0), 100),
        quote=annotation.quote,
        note=annotation.note,
        block_id=annotation.block_id,
        text_offset=annotation.text_offset,
        text_quote=annotation.text_quote,
        quote_prefix=annotation.quote_prefix,
        quote_suffix=annotation.quote_suffix,
        locator_content_version=annotation.locator_content_version,
        locator_variant=annotation.locator_variant,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    from app.services.chapter_identity_service import identity
    return {**item.__dict__, **identity(chapter), "chapter_number": chapter.chapter_number}


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


@router.get('/reading-summary/{novel_id:int}', response_model=ChapterReadingSummaryResponse)
def chapter_reading_summary(novel_id:int,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers['Cache-Control']='private, no-store'
    from app.services.chapter_reading_service import summary
    try:
        return summary(db,user.id,novel_id)
    finally:
        db.rollback()


@router.get('/reading-chapters/{novel_id:int}', response_model=ChapterReadingPageResponse)
def chapter_reading_page(novel_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),
    q:str=Query('',max_length=200),category_scope:Literal['all','followed']='all',db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers['Cache-Control']='private, no-store'
    from app.services.chapter_reading_service import page
    try:
        return page(db,user.id,novel_id,offset,limit,q,category_scope)
    finally:
        db.rollback()


@router.get("/{novel_id:int}", response_model=list[ChapterSchema])
def get_chapters(
    novel_id: int,
    title: str = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get chapters with pagination and optional filtering
    """
    # Only the owner's library copy: shared shelves never open another user's chapters.
    novel = db.query(Novel).filter_by(id=novel_id).first()
    if not novel or novel.library_id not in [lib.id for lib in current_user.libraries]:
        raise HTTPException(status_code=404, detail="Novel not found")

    # Start with base query
    query = chapter_services.get_chapters_by_novel_id(db, novel_id=novel_id)

    # Apply filters if provided
    if title:
        query = query.filter(Chapter.title == title)

    # Apply pagination and return results
    chapters = query.options(defer(Chapter.content), defer(Chapter.document)).order_by(
        Chapter.chapter_number, Chapter.id).offset(skip).limit(limit).all()
    return chapters


@router.get("/navigation/{novel_id:int}/{chapter_number}", response_model=ChapterNavigationResponse)
def chapter_navigation(novel_id: int, chapter_number: int, response: Response,
    expected_chapter_key: str | None = Query(None,max_length=36), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    _owned_novel(db, novel_id, user)
    query = db.query(Chapter).filter(Chapter.novel_id == novel_id)
    current = query.filter(Chapter.chapter_number == chapter_number).first()
    if current is None:
        raise HTTPException(404, 'Chapter not found')
    from app.services.chapter_identity_service import guard_read
    guard_read(db,current,expected_chapter_key)
    previous = query.filter(Chapter.chapter_number < chapter_number).order_by(Chapter.chapter_number.desc(), Chapter.id.desc()).first()
    following = query.filter(Chapter.chapter_number > chapter_number).order_by(Chapter.chapter_number, Chapter.id).first()
    from app.services.chapter_identity_service import identity
    def entry(row):
        return dict(**identity(row), id=row.id, chapter_number=row.chapter_number, title=row.title) if row else None
    return dict(**identity(current), novel_id=novel_id, chapter_id=current.id, chapter_number=current.chapter_number,
        previous=entry(previous), next=entry(following))


@router.get("/{novel_id:int}/{chapter_number}", response_model=ChapterSchema)
def get_chapter_by_number(
    novel_id: int,
    chapter_number: int,
    expected_chapter_key: str | None = Query(None,max_length=36),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a single chapter by Number
    """

    chapter = check_chapter(db, novel_id, chapter_number, current_user, expected_chapter_key)
    return chapter


def check_chapter(
    db: Session, novel_id: int, chapter_number: int, user: User, expected_chapter_key=None
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

    from app.services.chapter_identity_service import guard_read
    return guard_read(db,chapter,expected_chapter_key)


@router.get("/versions/{novel_id:int}/{chapter_number}", response_model=ChapterVersionsPage)
def chapter_versions(novel_id: int, chapter_number: int,
                     expected_chapter_key: str | None = Query(None,max_length=36),
                     cursor: int | None = Query(None, ge=1), limit: int = Query(25, ge=1, le=50),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import json
    from app.models.chapter_version import ChapterVersion
    from app.services.chapter_version_service import document_for, version_summary
    chapter = check_chapter(db, novel_id, chapter_number, user, expected_chapter_key)
    document = document_for(chapter)
    query = db.query(ChapterVersion).filter(ChapterVersion.chapter_id == chapter.id, ChapterVersion.chapter_key == chapter.chapter_key,
                                          ChapterVersion.content_version != document["content_version"])
    if cursor is not None:
        query = query.filter(ChapterVersion.id < cursor)
    rows = query.order_by(ChapterVersion.id.desc()).limit(limit + 1).all()
    versions = [version_summary(row) for row in rows[:limit]]
    if cursor is None and document.get("blocks"):
        versions.insert(0, {"content_version": document["content_version"], "title": chapter.title,
            "saved_at": chapter.updated_at, "current": True, "reason": "current",
            "byte_count": len(json.dumps(document, ensure_ascii=False).encode("utf-8"))})
    from app.services.chapter_identity_service import identity
    return {**identity(chapter), "current_version": document["content_version"], "versions": versions,
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


@router.get("/versions/{novel_id:int}/{chapter_number}/{content_version}", response_model=ChapterContent, response_model_exclude_unset=True)
def chapter_version_content(novel_id: int, chapter_number: int,
                            content_version: str = Path(pattern=r"^[a-f0-9]{64}$"),
                            expected_chapter_key: str | None = Query(None,max_length=36), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models.chapter_version import ChapterVersion
    from app.services.chapter_version_service import document_for
    chapter = check_chapter(db, novel_id, chapter_number, user, expected_chapter_key)
    current = document_for(chapter)
    if current["content_version"] == content_version and current.get("blocks"):
        value, document = chapter, current
    else:
        value = db.query(ChapterVersion).filter_by(chapter_id=chapter.id, chapter_key=chapter.chapter_key, content_version=content_version).first()
        if value is None:
            raise HTTPException(404, detail="This saved chapter version is unavailable")
        document = value.document
    from app.services.chapter_identity_service import identity
    return ChapterContent(**identity(chapter), id=chapter.id, novel_id=novel_id, chapter_number=chapter_number,
        title=value.title or f"Chapter {chapter_number}", content=document["plain_text"],
        source_url=value.source_url, document=document, source_version=document["content_version"],
        current_content_version=current["content_version"])


@router.get(
    "/content/library/{library_id:int}/{novel_id:int}/{chapter_number}",
    response_model=ChapterContent,
    response_model_exclude_unset=True,
)
def get_chapter_content(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    expected_chapter_key: str | None = Query(None,max_length=36),
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
    from app.services.chapter_identity_service import guard_read
    guard_read(db,chapter,expected_chapter_key)
    if not chapter.content and not (chapter.document or {}).get("blocks"):
        raise HTTPException(status_code=409, detail="Chapter content is not downloaded")

    from app.services.chapter_document import from_text
    from app.services.chapter_identity_service import identity
    return ChapterContent(
        **identity(chapter),
        id=chapter.id,
        novel_id=chapter.novel_id,
        chapter_number=chapter.chapter_number,
        title=chapter.title or f"Chapter {chapter.chapter_number}",
        content=chapter.content or "",
        source_url=chapter.source_url,
        document=chapter.document or from_text(chapter.content),
        source_version=(chapter.document or from_text(chapter.content))["content_version"],
        current_content_version=(chapter.document or from_text(chapter.content))["content_version"],
    )


@router.delete("/{chapter_id:int}", response_model=ChapterSchema)
def delete_chapter_by_id(
    chapter_id: int,
    expected_chapter_key: str | None = Query(None,max_length=36),
    expected_manifest_epoch: str | None = Query(None,max_length=36),
    expected_manifest_revision: str | None = Query(None,max_length=19),
    expected_content_version: str | None = Query(None,pattern=r"^[a-f0-9]{64}$"),
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
    raise HTTPException(409,detail={
        'code':'reviewed_workflow_required',
        'message':'Review this chapter in Chapter changes. Archival preserves its original and requires an explicit destination for affected saved positions.',
        'review_path':f'/chapter/novel/{chapter.novel_id}/manifest-state',
    })



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
    if not ch or ch.novel_id != chapter.novel_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    check_chapter(db, ch.novel_id, ch.chapter_number, current_user)
    from app.services.chapter_identity_service import check_write
    check_write(db,current_user.id,ch,expected_chapter_key=chapter.expected_chapter_key,
        expected_manifest_epoch=chapter.expected_manifest_epoch,expected_manifest_revision=chapter.expected_manifest_revision,
        expected_content_version=chapter.expected_content_version)

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


@router.get("/novel/{novel_id}/download-status", response_model=NovelDownloadStatusResponse, response_model_exclude_unset=True)
def get_novel_download_status(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get download status for all chapters of a novel.
    Returns counts and lists of chapters by status.
    """
    _owned_novel(db, novel_id, current_user)
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


@router.delete("/{chapter_id:int}/download", response_model=ChapterDownloadCancelledResponse, response_model_exclude_unset=True)
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


@router.post("/novel/{novel_id}/cancel-all-downloads", response_model=ChapterDownloadsCancelledResponse, response_model_exclude_unset=True)
def cancel_all_downloads(
    novel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cancel all in-progress chapter downloads for a novel.
    Resets PROCESSING chapters to MISSING.
    """
    _owned_novel(db, novel_id, current_user)
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

# Identity observations use dedicated names so numeric chapter routes remain compatible.
router.include_router(manifest_router)
