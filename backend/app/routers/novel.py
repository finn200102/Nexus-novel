from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Header, Query
import httpx
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import Novel as NovelSchema
from ..schemas.novel import (
    NovelCreate,
    NovelFollowSettings,
    NovelFollowUpdate,
    NovelUpdate,
    NovelUpdateEvent as NovelUpdateEventSchema,
)
from app.models.chapter import ContentStatus
from app.models.user import User
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.follow import UserNovelFollow
from app.models.update_event import NovelUpdateEvent
from app.models.download_job import ChapterDownloadJob
from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
from app.services.auto_download_service import queue_auto_downloads
import app.services.novel_services as novel_services
import app.services.library_organization_service as organization
from app.services.chapter_services import (
    create_chapter,
    get_chapters_by_novel_id,
)
from app.services.library_services import get_library_by_id
from app.services.reading_order import attach_next_unread
from app.auth.dependencies import get_current_user
from app.services import metadata_client
from app.services.download_job_service import queue_missing_chapters
from app.logging_config import get_logger
from app.services.novel_title import clean_title
import asyncio
import hmac
import os
import shutil
from urllib.parse import urlparse
from datetime import UTC, datetime
from pydantic import BaseModel, Field

logger = get_logger(__name__)


router = APIRouter(
    prefix="/novel",
    tags=["novels"],
    responses={404: {"description": "Not found"}},
)


FOLLOW_STATES = {"plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"}


@router.get("/hiatus/{novel_id}")
async def get_novel_hiatus(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(status_code=404, detail="Novel not found")
    if not novel.metadata_id:
        return {"state": "unknown", "confidence": 0.0, "reason": "This novel has not finished metadata import."}
    try:
        return await metadata_client.get_hiatus_status(int(novel.metadata_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Hiatus status is temporarily unavailable") from exc


def get_existing_follow(db: Session, user_id: int, novel: Novel) -> UserNovelFollow | None:
    follow = (
        db.query(UserNovelFollow)
        .filter(UserNovelFollow.user_id == user_id, UserNovelFollow.novel_id == novel.id)
        .first()
    )
    return follow


def get_or_create_follow(db: Session, user_id: int, novel: Novel) -> UserNovelFollow:
    follow = get_existing_follow(db, user_id, novel)
    if follow:
        return follow

    legacy_state = novel.follow_state if novel.follow_state in FOLLOW_STATES else "plan_to_read"
    follow = UserNovelFollow(
        user_id=user_id,
        novel_id=novel.id,
            state=legacy_state,
            followed_at=novel.followed_at,
    )
    db.add(follow)
    db.flush()
    return follow


def sync_chapter_category(chapter: Chapter, category: str | None) -> None:
    """Re-sync an existing chapter's category from metadata; new chapters get it at creation."""
    value = category or "story"
    if chapter.category != value:
        chapter.category = value


def create_update_event(
    db: Session,
    novel: Novel,
    *,
    event_type: str,
    chapter_numbers: list[int],
    message: str,
) -> NovelUpdateEvent | None:
    if not novel.library or not novel.library.user_id or not chapter_numbers:
        return None
    follow = get_existing_follow(db, novel.library.user_id, novel)
    if not follow:
        return None
    download_plan = 0
    if follow.download_policy == "next_chapter":
        download_plan = min(1, len(chapter_numbers))
    elif follow.download_policy == "next_n":
        download_plan = min(follow.download_count, len(chapter_numbers))
    notification_visible = follow.notification_policy == "immediate"
    if follow.notification_policy == "after_n":
        previous = (
            db.query(NovelUpdateEvent)
            .filter(
                NovelUpdateEvent.user_id == follow.user_id,
                NovelUpdateEvent.novel_id == novel.id,
                NovelUpdateEvent.notification_visible.is_(False),
            )
            .all()
        )
        notification_visible = sum(event.chapter_count for event in previous) + len(chapter_numbers) >= max(follow.notification_count or 1, 1)
    elif follow.notification_policy in {"daily_digest", "weekly_digest"}:
        latest = (
            db.query(NovelUpdateEvent)
            .filter(
                NovelUpdateEvent.user_id == follow.user_id,
                NovelUpdateEvent.novel_id == novel.id,
                NovelUpdateEvent.notification_visible.is_(True),
            )
            .order_by(NovelUpdateEvent.created_at.desc())
            .first()
        )
        if latest and latest.created_at:
            latest_date = latest.created_at.date()
            current_date = datetime.now(UTC).date()
            notification_visible = current_date != latest_date if follow.notification_policy == "daily_digest" else current_date.isocalendar().week != latest_date.isocalendar().week
    event = NovelUpdateEvent(
            user_id=novel.library.user_id,
            novel_id=novel.id,
            event_type=event_type,
            chapter_count=len(chapter_numbers),
            first_chapter_number=min(chapter_numbers),
            last_chapter_number=max(chapter_numbers),
            message=message,
            details={
                "chapter_numbers": sorted(chapter_numbers),
                "download_plan_count": download_plan,
                "download_policy": follow.download_policy,
                "notification_policy": follow.notification_policy,
                "notification_count": follow.notification_count,
            },
            notification_visible=notification_visible,
        )
    db.add(event)
    return event


class MetadataChapterEvent(BaseModel):
    chapter_number: int
    chapter_id: int | None = None
    title: str | None = None
    url: str | None = None
    word_count: int | None = None
    category: str | None = None


class MetadataRefreshEvent(BaseModel):
    event: str
    delivery_id: str | None = None
    job_id: str | int
    metadata_novel_id: int
    source_id: int
    site: str
    new_chapter_numbers: list[int] = Field(default_factory=list)
    chapters: list[MetadataChapterEvent] = Field(default_factory=list)
    message: str | None = None
    hiatus: dict | None = None


def claim_metadata_webhook_delivery(db: Session, event: MetadataRefreshEvent) -> bool:
    """Atomically claim a source job delivery before processing its effects."""
    # New metadata workers provide an immutable outbox delivery ID. Retain a
    # deterministic legacy key for older workers, while including the event
    # type so a failed attempt cannot suppress a later successful refresh.
    delivery_key = event.delivery_id or f"{event.source_id}:{event.job_id}:{event.event}"
    try:
        # A savepoint lets a duplicate-key conflict roll back only the insert,
        # preserving the request transaction for the no-op response.
        with db.begin_nested():
            db.add(
                MetadataWebhookDelivery(
                    delivery_key=delivery_key,
                    source_job_id=str(event.job_id),
                    source_id=event.source_id,
                    event_type=event.event,
                )
            )
            db.flush()
    except IntegrityError:
        return False
    return True


@router.post("/internal/metadata-events")
def receive_metadata_event(
    event: MetadataRefreshEvent,
    db: Session = Depends(get_db),
    webhook_secret: str | None = Header(default=None, alias="X-Nexus-Webhook-Secret"),
):
    expected_secret = os.getenv("NEXUS_NOVEL_WEBHOOK_SECRET", "").strip()
    if not expected_secret or not hmac.compare_digest(
        (webhook_secret or "").encode(), expected_secret.encode()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
    if not claim_metadata_webhook_delivery(db, event):
        return {"accepted": True, "created_events": 0, "queued_downloads": 0}
    if event.event == "source_refresh_failed":
        created_events = 0
        for novel in db.query(Novel).filter(Novel.metadata_id == event.metadata_novel_id).all():
            if not novel.library:
                continue
            follow = get_existing_follow(db, novel.library.user_id, novel)
            if not follow:
                continue
            if follow.state in {"completed", "dropped", "ignored"}:
                continue
            db.add(NovelUpdateEvent(
                user_id=novel.library.user_id,
                novel_id=novel.id,
                event_type="source_failed",
                message=event.message or "Source refresh failed",
                details={"source_job_id": str(event.job_id), "source_id": event.source_id, "site": event.site},
                notification_visible=follow.notification_policy == "immediate",
            ))
            created_events += 1
        db.commit()
        return {"accepted": True, "created_events": created_events, "queued_downloads": 0}
    if event.event == "source_returned_from_hiatus":
        created_events = 0
        for novel in db.query(Novel).filter(Novel.metadata_id == event.metadata_novel_id).all():
            if not novel.library:
                continue
            follow = get_existing_follow(db, novel.library.user_id, novel)
            if not follow or follow.state in {"completed", "dropped", "ignored"}:
                continue
            db.add(NovelUpdateEvent(
                user_id=follow.user_id,
                novel_id=novel.id,
                event_type="resumed",
                chapter_count=len(event.new_chapter_numbers),
                first_chapter_number=min(event.new_chapter_numbers) if event.new_chapter_numbers else None,
                last_chapter_number=max(event.new_chapter_numbers) if event.new_chapter_numbers else None,
                message=event.message or "This story returned after a long update gap.",
                details={"source_job_id": str(event.job_id), "source_id": event.source_id, "site": event.site, "hiatus": getattr(event, "hiatus", None)},
                notification_visible=follow.notification_policy == "immediate",
            ))
            created_events += 1
        db.commit()
        return {"accepted": True, "created_events": created_events, "queued_downloads": 0}
    if event.event != "source_refresh_completed" or not event.new_chapter_numbers:
        return {"accepted": True, "created_events": 0, "queued_downloads": 0}

    novels = db.query(Novel).filter(Novel.metadata_id == event.metadata_novel_id).all()
    created_events = 0
    queued_downloads = 0
    for novel in novels:
        if not novel.library:
            continue
        follow = get_existing_follow(db, novel.library.user_id, novel)
        if not follow:
            continue
        if follow.state in {"on_hold", "completed", "dropped", "ignored"}:
            continue
        chapters_by_number = {chapter.chapter_number: chapter for chapter in event.chapters}
        chapter_rows = {}
        for number in event.new_chapter_numbers:
            chapter = db.query(Chapter).filter(Chapter.novel_id == novel.id, Chapter.chapter_number == number).first()
            source = chapters_by_number.get(number)
            if chapter and source and source.category:
                sync_chapter_category(chapter, source.category)
            if not chapter:
                chapter = Chapter(
                    novel_id=novel.id,
                    chapter_number=number,
                    title=source.title if source else f"Chapter {number}",
                    site_chapter_id=source.chapter_id if source else None,
                    source_url=source.url if source else None,
                    word_count=source.word_count if source else None,
                    content_status=ContentStatus.MISSING,
                    category=(source.category if source and source.category else "story"),
                )
                db.add(chapter)
                db.flush()
            chapter_rows[number] = chapter
        update = create_update_event(
            db,
            novel,
            event_type="new_chapters",
            chapter_numbers=event.new_chapter_numbers,
            message=f"{len(event.new_chapter_numbers)} new chapter(s) available",
        )
        if update:
            update.details = {**(update.details or {}), "source_job_id": str(event.job_id), "source_id": event.source_id, "site": event.site}
        created_events += 1
        if follow.download_policy == "next_chapter":
            requested = 1
        elif follow.download_policy == "next_n":
            requested = max(follow.download_count or 0, 0)
        else:
            requested = 0
        if requested:
            active_jobs = {
                job.chapter_id
                for job in db.query(ChapterDownloadJob)
                .filter(
                    ChapterDownloadJob.user_id == novel.library.user_id,
                    ChapterDownloadJob.novel_id == novel.id,
                    ChapterDownloadJob.status.in_({"queued", "processing"}),
                )
                .all()
            }
            for chapter in sorted(chapter_rows.values(), key=lambda row: row.chapter_number)[:requested]:
                if chapter.id in active_jobs:
                    continue
                db.add(ChapterDownloadJob(user_id=novel.library.user_id, library_id=novel.library.id, novel_id=novel.id, chapter_id=chapter.id))
                queued_downloads += 1
        queued_downloads += queue_auto_downloads(
            db, user_id=novel.library.user_id, library_id=novel.library.id, novel=novel
        )
    db.commit()
    return {"accepted": True, "created_events": created_events, "queued_downloads": queued_downloads}


def _run_metadata_call(coro, loop: asyncio.AbstractEventLoop | None):
    """Run a metadata client coroutine from a background-task thread.

    The pooled metadata client belongs to the application's event loop; using
    it from a fresh ``asyncio.run`` loop fails with "bound to a different event
    loop". Schedule the call on the loop that owns the client instead.
    """
    if loop is None:
        return asyncio.run(coro)
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def scrape_novel_background(
    novel_id: int,
    metadata_id: int,
    db_session_factory,
    loop: asyncio.AbstractEventLoop | None = None,
):
    """Background task to scrape and update novel metadata."""
    db = db_session_factory()
    try:
        logger.info(
            "Starting background scrape",
            novel_id=novel_id,
            metadata_id=metadata_id,
        )

        try:
            scraped_data = _run_metadata_call(
                metadata_client.wait_for_scrape_complete(metadata_id), loop
            )
            if scraped_data.get("status") == "error":
                # "description" is the story blurb, not an error: never surface it.
                error_message = scraped_data.get("last_error") or scraped_data.get("error")
                raise RuntimeError(
                    error_message if isinstance(error_message, str) and error_message.strip()
                    else "Metadata scrape failed"
                )

            story_id = scraped_data.get("story_id")

            novel_data = {
                "title": clean_title(scraped_data.get("title"), scraped_data.get("source_url")),
                "author": scraped_data.get("author"),
                "author_site_id": scraped_data.get("author_id"),
                "source_url": scraped_data.get("source_url"),
                "img_url": scraped_data.get("img_url"),
                "description": scraped_data.get("description"),
                "word_count": scraped_data.get("word_count"),
                "reviews": scraped_data.get("reviews"),
                "favorites": scraped_data.get("favorites"),
                "follows": scraped_data.get("follows"),
                "status": scraped_data.get("status"),
                "views": scraped_data.get("views"),
                "rating": scraped_data.get("rating"),
                "publish_date": scraped_data.get("publish_date"),
                "updated_date": scraped_data.get("updated_date"),
                "chapter_count": scraped_data.get("chapter_count"),
                "story_id": story_id,
                "site_story_id": story_id,
                "scrape_status": "completed",
                "scrape_error": None,
            }

            novel_services.update_novel(db, novel_id, novel_data)

            chapters_data = _run_metadata_call(
                metadata_client.get_chapters_from_metadata(metadata_id), loop
            )
            for chapter_meta in chapters_data:
                chapter_data = {
                    "novel_id": novel_id,
                    "chapter_number": chapter_meta.get("chapter_number"),
                    "title": chapter_meta.get("title"),
                    "site_chapter_id": chapter_meta.get("chapter_id"),
                    "word_count": chapter_meta.get("word_count"),
                    "content_status": ContentStatus.MISSING,
                    "category": chapter_meta.get("category") or "story",
                }
                create_chapter(db, chapter_data)

            logger.info(
                "Background scrape completed",
                novel_id=novel_id,
                metadata_id=metadata_id,
            )

        except Exception as e:
            logger.error(
                "Background scrape failed",
                novel_id=novel_id,
                error=str(e),
            )
            novel_services.update_novel(
                db, novel_id, {"scrape_status": "failed", "scrape_error": str(e)}
            )
    finally:
        db.close()


SUPPORTED_HOSTS = frozenset({
    "www.royalroad.com",
    "forums.spacebattles.com",
    "www.fanfiction.net",
    "archiveofourown.org",
    "www.webnovel.com",
    "webnovel.com",
    "forums.sufficientvelocity.com",
    "forum.questionablequesting.com",
    "www.scribblehub.com",
})


def supported_src(url):
    # Match the parsed host, not a substring: "http://10.0.0.1/?www.royalroad.com"
    # must not reach the scraper, which fetches whatever URL it is given.
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in SUPPORTED_HOSTS


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


def check_library(db, library_id, current_user):
    library = get_library_by_id(db, library_id)
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
    return library


@router.post("/", response_model=NovelSchema, status_code=status.HTTP_201_CREATED)
async def add_novel(
    novel: NovelCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate the target library before inspecting an existing URL. This keeps
    # duplicate imports safe across users while making retries from the UI
    # idempotent for the library that already owns the novel.
    library = check_library(db, novel.library_id, current_user)

    existing_novel = novel_services.get_novel_by_url(
        db, novel.url, library.id
    ).first()
    if existing_novel:
        return existing_novel

    if not supported_src(novel.url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a supported source url"
        )

    site_name = get_site_name_from_url(novel.url)
    if not site_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine site from URL",
        )

    scrape_result = await metadata_client.scrape_novel_by_url(novel.url, site_name)

    if not scrape_result or not scrape_result.get("success"):
        message = (
            scrape_result.get("message", "Failed to start scraping")
            if scrape_result
            else "Failed to start scraping"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add novel: {message}",
        )

    metadata_id = scrape_result.get("novel_id")
    if not metadata_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add novel: No metadata ID returned",
        )

    title = clean_title(None, novel.url) or "New Novel"

    novel_data = {
        "title": title,
        "url": novel.url,
        "library_id": novel.library_id,
        "metadata_id": metadata_id,
        "novel_site": site_name,
        "scrape_status": "pending",
    }

    novel_obj = novel_services.create_novel(db, novel_data)

    from config.database import SessionLocal

    background_tasks.add_task(
        scrape_novel_background,
        int(novel_obj.id),
        metadata_id,
        SessionLocal,
        asyncio.get_running_loop(),
    )

    return novel_obj


@router.get("/refresh/{novel_id}", response_model=NovelSchema)
async def refresh_novel_metadata(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)

    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    metadata_id = novel.metadata_id

    if not metadata_id:
        site_name = get_site_name_from_url(novel.url)
        if not site_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not determine site from URL",
            )

        scrape_result = await metadata_client.scrape_novel_by_url(novel.url, site_name)

        if not scrape_result or not scrape_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to scrape novel",
            )

        metadata_id = scrape_result.get("novel_id")
        if not metadata_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get metadata ID from scrape",
            )

        novel_services.update_novel(db, novel_id, {"metadata_id": metadata_id})

    try:
        refreshed_data = await metadata_client.refresh_novel_metadata(metadata_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Metadata server error while refreshing novel: {exc.response.text}",
        ) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh metadata: {exc}",
        ) from exc

    story_id = refreshed_data.get("story_id")

    novel_data = {
        "title": clean_title(refreshed_data.get("title"), refreshed_data.get("source_url")),
        "author": refreshed_data.get("author"),
        "author_site_id": refreshed_data.get("author_id"),
        "source_url": refreshed_data.get("source_url"),
        "img_url": refreshed_data.get("img_url"),
        "description": refreshed_data.get("description"),
        "word_count": refreshed_data.get("word_count"),
        "reviews": refreshed_data.get("reviews"),
        "favorites": refreshed_data.get("favorites"),
        "follows": refreshed_data.get("follows"),
        "status": refreshed_data.get("status"),
        "views": refreshed_data.get("views"),
        "rating": refreshed_data.get("rating"),
        "publish_date": refreshed_data.get("publish_date"),
        "updated_date": refreshed_data.get("updated_date"),
        "chapter_count": refreshed_data.get("chapter_count"),
        "analyzed_at": refreshed_data.get("analyzed_at"),
        "analysis_type": refreshed_data.get("analysis_type"),
        "analyzed_chapter_count": refreshed_data.get("analyzed_chapter_count"),
        "parsed_at": refreshed_data.get("parsed_at"),
        "story_id": story_id,
        "site_story_id": story_id,
    }

    updated_novel = novel_services.update_novel(db, novel_id, novel_data)

    chapters_data = await metadata_client.get_chapters_from_metadata(metadata_id)
    existing_chapters = {
        ch.chapter_number: ch for ch in get_chapters_by_novel_id(db, novel_id).all()
    }
    new_chapter_numbers = []

    for chapter_meta in chapters_data:
        chapter_num = chapter_meta.get("chapter_number")
        if chapter_num in existing_chapters:
            sync_chapter_category(existing_chapters[chapter_num], chapter_meta.get("category"))
        else:
            new_chapter_numbers.append(chapter_num)
            chapter_data = {
                "novel_id": novel_id,
                "chapter_number": chapter_num,
                "title": chapter_meta.get("title"),
                "site_chapter_id": chapter_meta.get("chapter_id"),
                "word_count": chapter_meta.get("word_count"),
                "content_status": ContentStatus.MISSING,
                "category": chapter_meta.get("category") or "story",
            }
            create_chapter(db, chapter_data)

    create_update_event(
        db,
        novel,
        event_type="new_chapters",
        chapter_numbers=new_chapter_numbers,
        message=f"{len(new_chapter_numbers)} new chapter(s) available",
    )
    if new_chapter_numbers and novel.library:
        queue_auto_downloads(db, user_id=novel.library.user_id, library_id=novel.library.id, novel=novel)
    db.commit()

    metadata_client.invalidate_novel_cache(novel.metadata_id)

    return updated_novel


@router.put("/{novel_id:int}", response_model=NovelSchema)
async def rescrape_novel(
    novel_id: int,
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    metadata_id = novel.metadata_id

    if not metadata_id:
        if not novel.url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Novel has no source URL",
            )

        site_name = get_site_name_from_url(novel.url)
        if not site_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not determine site from URL",
            )

        scrape_result = await metadata_client.scrape_novel_by_url(novel.url, site_name)
        if not scrape_result or not scrape_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to start scraping: {scrape_result.get('message', 'Unknown error') if scrape_result else 'No result'}",
            )

        metadata_id = scrape_result.get("novel_id")
        if not metadata_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get metadata ID from scrape",
            )

        novel_services.update_novel(
            db,
            novel_id,
            {
                "metadata_id": metadata_id,
                "scrape_status": "pending",
                "scrape_error": None,
            },
        )

        from config.database import SessionLocal

        background_tasks.add_task(
            scrape_novel_background,
            int(novel_id),
            metadata_id,
            SessionLocal,
            asyncio.get_running_loop(),
        )
    else:
        try:
            metadata_id_int = int(metadata_id)
            refreshed_data = await metadata_client.refresh_novel_metadata(
                metadata_id_int
            )

            story_id = refreshed_data.get("story_id")

            if not story_id:
                metadata_client.invalidate_novel_cache(metadata_id_int)
                chapters_data = await metadata_client.get_chapters_from_metadata(
                    metadata_id_int
                )
                if chapters_data and len(chapters_data) > 0:
                    story_id = chapters_data[0].get("story_id")

            novel_data = {
                "title": clean_title(refreshed_data.get("title"), refreshed_data.get("source_url")),
                "author": refreshed_data.get("author"),
                "author_site_id": refreshed_data.get("author_id"),
                "source_url": refreshed_data.get("source_url"),
                "img_url": refreshed_data.get("img_url"),
                "description": refreshed_data.get("description"),
                "word_count": refreshed_data.get("word_count"),
                "reviews": refreshed_data.get("reviews"),
                "favorites": refreshed_data.get("favorites"),
                "follows": refreshed_data.get("follows"),
                "status": refreshed_data.get("status"),
                "views": refreshed_data.get("views"),
                "rating": refreshed_data.get("rating"),
                "publish_date": refreshed_data.get("publish_date"),
                "updated_date": refreshed_data.get("updated_date"),
                "chapter_count": refreshed_data.get("chapter_count"),
                "analyzed_at": refreshed_data.get("analyzed_at"),
                "analysis_type": refreshed_data.get("analysis_type"),
                "analyzed_chapter_count": refreshed_data.get("analyzed_chapter_count"),
                "parsed_at": refreshed_data.get("parsed_at"),
                "story_id": story_id,
                "site_story_id": story_id,
            }
            novel_services.update_novel(db, novel_id, novel_data)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to refresh metadata: {exc}",
            ) from exc

    return novel_services.get_novel_by_id(db, novel_id)


@router.patch("/{novel_id:int}/follow", response_model=NovelSchema)
def update_follow_state(
    novel_id: int,
    update: NovelFollowUpdate,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

    follow = get_or_create_follow(db, current_user.id, novel)
    follow.state = update.follow_state
    follow.followed_at = follow.followed_at or datetime.now(UTC)
    follow.download_policy = update.download_policy
    follow.download_count = update.download_count
    follow.notification_policy = update.notification_policy
    follow.notification_count = update.notification_count
    novel.follow_state = update.follow_state
    novel.followed_at = follow.followed_at
    # Applying an automatic-download policy should also honor it immediately
    # for chapters already known to the catalog. Future refresh webhooks will
    # queue subsequent chapters through the same durable-job path.
    if update.download_policy == "next_chapter":
        queue_missing_chapters(
            db,
            user_id=current_user.id,
            library_id=library_id,
            novel_id=novel.id,
            count=1,
        )
    elif update.download_policy == "next_n":
        queue_missing_chapters(
            db,
            user_id=current_user.id,
            library_id=library_id,
            novel_id=novel.id,
            count=max(update.download_count, 1),
        )
    db.commit()
    db.refresh(novel)
    return novel


@router.get("/{novel_id:int}/follow", response_model=NovelFollowSettings)
def get_follow_settings(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
    follow = get_or_create_follow(db, current_user.id, novel)
    db.commit()
    return NovelFollowSettings(
        novel_id=novel.id,
        follow_state=follow.state,
        download_policy=follow.download_policy,
        download_count=follow.download_count,
        notification_policy=follow.notification_policy,
        notification_count=follow.notification_count,
    )


@router.get("/updates", response_model=list[NovelUpdateEventSchema])
def get_update_events(
    library_id: int,
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    query = (
        db.query(NovelUpdateEvent)
        .join(Novel, Novel.id == NovelUpdateEvent.novel_id)
        .filter(
            NovelUpdateEvent.user_id == current_user.id,
            Novel.library_id == library_id,
            NovelUpdateEvent.notification_visible.is_(True),
        )
    )
    if unread_only:
        query = query.filter(NovelUpdateEvent.read_at.is_(None))
    return query.order_by(desc(NovelUpdateEvent.created_at)).limit(min(max(limit, 1), 100)).all()


@router.post("/updates/{event_id:int}/read", response_model=NovelUpdateEventSchema)
def mark_update_event_read(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = (
        db.query(NovelUpdateEvent)
        .filter(NovelUpdateEvent.id == event_id, NovelUpdateEvent.user_id == current_user.id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update event not found")
    event.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event


@router.get("/", response_model=list[NovelSchema])
async def get_novels(
    library_id: int,
    title: str = "",
    search: str = "",
    author_name: str | None = None,
    genre_id: int | None = None,
    shelf_id: int | None = None,
    user_tag: str | None = None,
    min_rating: int | None = Query(None, ge=1, le=5),
    sort_by: str = Query("default", pattern="^(default|updated_since_read|personal_rating)$"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)

    query = novel_services.get_novels(db).filter(Novel.library_id == library_id)

    if title:
        query = query.filter(Novel.title == title)

    if author_name:
        query = query.filter(Novel.author == author_name)

    if genre_id:
        query = query.filter(Novel.genre_id == genre_id)

    if search:
        query = query.filter(Novel.title.like(f"%{search}%"))

    if shelf_id is not None:
        shelf_novels = organization.novel_ids_on_shelf(db, current_user, shelf_id)
        query = query.filter(Novel.id.in_(list(shelf_novels)))

    if user_tag:
        query = query.filter(Novel.id.in_(list(organization.novel_ids_with_user_tag(db, current_user, user_tag))))

    if min_rating is not None:
        query = query.filter(Novel.id.in_(list(organization.novel_ids_with_min_rating(db, current_user, min_rating))))

    if sort_by != "default":
        # User-data sorts need every match before paginating.
        ordered = organization.sort_novels(db, current_user, query.all(), sort_by)
        novels = ordered[skip : skip + limit]
    else:
        novels = query.offset(skip).limit(limit).all()

    for novel in novels:
        if novel.metadata_id and not novel.title:
            try:
                metadata_client.invalidate_novel_cache(novel.metadata_id)
                metadata = await metadata_client.get_novel_metadata(novel.metadata_id)
                if metadata and metadata.get("title"):
                    novel_data = {
                        "title": clean_title(metadata.get("title"), metadata.get("source_url") or novel.url),
                        "author": metadata.get("author"),
                        "author_site_id": metadata.get("author_id"),
                        "source_url": metadata.get("source_url"),
                        "img_url": metadata.get("img_url"),
                        "description": metadata.get("description"),
                        "word_count": metadata.get("word_count"),
                        "reviews": metadata.get("reviews"),
                        "favorites": metadata.get("favorites"),
                        "follows": metadata.get("follows"),
                        "status": metadata.get("status"),
                        "views": metadata.get("views"),
                        "rating": metadata.get("rating"),
                        "publish_date": metadata.get("publish_date"),
                        "updated_date": metadata.get("updated_date"),
                        "chapter_count": metadata.get("chapter_count"),
                    }
                    novel_services.update_novel(db, novel.id, novel_data)
            except Exception as e:
                logger.warning(
                    "Error fetching metadata for novel",
                    error=str(e),
                    novel_id=novel.id,
                )

    db.commit()
    attach_next_unread(db, current_user.id, novels)

    return novels


@router.get("/{novel_id:int}", response_model=NovelSchema)
async def get_novel_by_id(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    if novel.metadata_id:
        try:
            metadata_client.invalidate_novel_cache(novel.metadata_id)
            metadata = await metadata_client.get_novel_metadata(novel.metadata_id)
            if metadata and metadata.get("title"):
                novel_data = {
                    "title": clean_title(metadata.get("title"), metadata.get("source_url") or novel.url),
                    "author": metadata.get("author"),
                    "author_site_id": metadata.get("author_id"),
                    "source_url": metadata.get("source_url"),
                    "img_url": metadata.get("img_url"),
                    "description": metadata.get("description"),
                    "word_count": metadata.get("word_count"),
                    "reviews": metadata.get("reviews"),
                    "favorites": metadata.get("favorites"),
                    "follows": metadata.get("follows"),
                    "status": metadata.get("status"),
                    "views": metadata.get("views"),
                    "rating": metadata.get("rating"),
                    "publish_date": metadata.get("publish_date"),
                    "updated_date": metadata.get("updated_date"),
                    "chapter_count": metadata.get("chapter_count"),
                    "analyzed_at": metadata.get("analyzed_at"),
                    "analysis_type": metadata.get("analysis_type"),
                    "analyzed_chapter_count": metadata.get("analyzed_chapter_count"),
                    "parsed_at": metadata.get("parsed_at"),
                }
                novel = novel_services.update_novel(db, novel_id, novel_data)

                chapters_data = await metadata_client.get_chapters_from_metadata(
                    novel.metadata_id
                )
                existing_chapters = {ch.chapter_number: ch for ch in novel.chapters}
                for chapter_meta in chapters_data:
                    chapter_num = chapter_meta.get("chapter_number")
                    if chapter_num in existing_chapters:
                        sync_chapter_category(existing_chapters[chapter_num], chapter_meta.get("category"))
                    else:
                        chapter_data = {
                            "novel_id": novel_id,
                            "chapter_number": chapter_num,
                            "title": chapter_meta.get("title"),
                            "site_chapter_id": chapter_meta.get("chapter_id"),
                            "word_count": chapter_meta.get("word_count"),
                            "content_status": ContentStatus.MISSING,
                            "category": chapter_meta.get("category") or "story",
                        }
                        create_chapter(db, chapter_data)

                db.commit()
                db.refresh(novel)
        except Exception as e:
            logger.warning(
                "Error fetching metadata",
                error=str(e),
                novel_id=novel_id,
            )

    attach_next_unread(db, current_user.id, [novel])
    return novel


@router.post("/delete/{novel_id:int}", response_model=NovelSchema)
def delete_novel_by_id(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    # The novel must live in the caller's library; otherwise any user could
    # delete another user's novel by pairing its id with their own library.
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    check_library(db, library_id, current_user)
    base_dir = os.path.realpath(
        os.path.join(os.environ.get("DOWNLOAD_PATH", "/data/downloads"), str(current_user.username), str(library_id))
    )
    # Titles come from source sites; keep the folder strictly inside base_dir.
    novel_path = os.path.realpath(os.path.join(base_dir, novel.title or ""))

    if os.path.dirname(novel_path) == base_dir and os.path.isdir(novel_path):
        shutil.rmtree(novel_path)
    else:
        logger.debug("Directory does not exist", path=novel_path)

    novel_services.delete_novel(db, novel.id)
    return novel


@router.post("/update/", response_model=NovelSchema)
def update_novel(
    novel: NovelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel_data = {"title": novel.title, "url": novel.url}
    novel = novel_services.get_novel_by_id(db, novel.id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel.id} not found",
        )
    check_library(db, novel.library_id, current_user)

    novel = novel_services.update_novel(db, novel.id, novel_data)
    return novel
