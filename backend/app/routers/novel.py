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
from app.models.user import User
from app.models.novel import Novel
from app.models.follow import UserNovelFollow
from app.models.update_event import NovelUpdateEvent
from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
from app.schemas.metadata_event_proof import MetadataEventManifestProof
from app.services.creator_follow_service import NEW_WORK_EVENTS, handle_new_work_event
from app.services.auto_download_service import queue_auto_downloads
import app.services.novel_services as novel_services
import app.services.library_organization_service as organization
from app.services.library_services import get_library_by_id
from app.services.reading_order import attach_next_unread
from app.auth.dependencies import get_current_user
from app.services import content_limit_service, metadata_client
from app.services.source_refresh_guard import await_source, capture_source, revalidate_source, refresh_fields
from app.services.chapter_manifest_service import ingest_metadata_snapshot
from app.services.download_job_service import queue_missing_chapters
from app.logging_config import get_logger
from app.services.novel_title import clean_title
import asyncio
import hmac
import os
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
    try:
        # Another reader request can initialize these settings concurrently.
        # A savepoint keeps its unique-key conflict from aborting other work.
        with db.begin_nested():
            db.add(follow)
            db.flush()
    except IntegrityError:
        existing = get_existing_follow(db, user_id, novel)
        if existing is None:
            raise
        return existing
    return follow


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
    new_chapter_numbers: list[int] = Field(default_factory=list, max_length=1000)
    chapters: list[MetadataChapterEvent] = Field(default_factory=list, max_length=1000)
    manifest_proof: MetadataEventManifestProof | None = None
    changed_chapter_count: int | None = Field(None, ge=0, le=1_000_000)
    chunk_index: int | None = Field(None, ge=0, le=1_000_000)
    chunk_count: int | None = Field(None, ge=1, le=1_000_000)
    message: str | None = None
    hiatus: dict | None = None
    # author_new_work / series_new_work: the followed target and the new work.
    target: dict | None = None
    work: dict | None = None


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
async def receive_metadata_event(
    event: MetadataRefreshEvent,
    db: Session = Depends(get_db),
    webhook_secret: str | None = Header(default=None, alias="X-Nexus-Webhook-Secret"),
):
    expected_secret = os.getenv("NEXUS_NOVEL_WEBHOOK_SECRET", "").strip()
    if not expected_secret or not hmac.compare_digest(
        (webhook_secret or "").encode(), expected_secret.encode()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
    if event.event == 'source_refresh_completed':
        from app.services.metadata_event_ingestion import receive_completed
        return await receive_completed(db, event)
    if not claim_metadata_webhook_delivery(db, event):
        return {"accepted": True, "created_events": 0, "queued_downloads": 0}
    if event.event in NEW_WORK_EVENTS:
        created_events = handle_new_work_event(db, event.event, event.model_dump())
        db.commit()
        return {"accepted": True, "created_events": created_events, "queued_downloads": 0}
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
                chapter_count=event.changed_chapter_count if event.changed_chapter_count is not None else len(event.new_chapter_numbers),
                first_chapter_number=min(event.new_chapter_numbers) if event.new_chapter_numbers else None,
                last_chapter_number=max(event.new_chapter_numbers) if event.new_chapter_numbers else None,
                message=event.message or "This story returned after a long update gap.",
                details={"source_job_id": str(event.job_id), "source_id": event.source_id, "site": event.site, "hiatus": getattr(event, "hiatus", None)},
                notification_visible=follow.notification_policy == "immediate",
            ))
            created_events += 1
        db.commit()
        return {"accepted": True, "created_events": created_events, "queued_downloads": 0}
    return {"accepted": True, "created_events": 0, "queued_downloads": 0}


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
    job_id: str | None = None,
):
    """Background task to scrape and update novel metadata."""
    db = db_session_factory()
    authority = None
    try:
        logger.info(
            "Starting background scrape",
            novel_id=novel_id,
            metadata_id=metadata_id,
        )

        try:
            novel = db.query(Novel).filter_by(id=novel_id).first()
            if novel is None:
                return
            if novel.metadata_id != metadata_id:
                raise HTTPException(409, 'The linked source changed before this import started')
            authority = capture_source(db, novel.library.user_id, novel)
            scraped_data = _run_metadata_call(
                metadata_client.wait_for_scrape_complete(metadata_id, **({"job_id": job_id} if job_id else {})), loop
            )
            novel = revalidate_source(db, authority)
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

            novel = novel_services.update_novel(db, novel_id, refresh_fields(db, novel, scraped_data, novel_data))

            authority = capture_source(db, novel.library.user_id, novel)
            snapshot = _run_metadata_call(
                metadata_client.get_chapter_manifest(metadata_id), loop
            )
            novel = revalidate_source(db, authority)
            ingest_metadata_snapshot(db, novel, snapshot)
            db.commit()

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
            db.rollback()
            if authority is None:
                return
            try:
                revalidate_source(db, authority)
            except HTTPException:
                return
            novel_services.update_novel(
                db, novel_id, {"scrape_status": "failed", "scrape_error": str(e)}
            )
    finally:
        db.close()


def scrape_within_limits(
    novel_id: int,
    metadata_id: int,
    db_session_factory,
    loop: asyncio.AbstractEventLoop | None,
    user_id: int,
    scrape=None,
    job_id: str | None = None,
):
    """Scrape a story added by link, then drop it again when it is outside the
    content limits of the profile that added it (household profiles)."""
    (scrape or scrape_novel_background)(novel_id, metadata_id, db_session_factory, loop, **({"job_id": job_id} if job_id else {}))
    db = db_session_factory()
    try:
        user = db.get(User, user_id)
        novel = db.get(Novel, novel_id)
        if user is None or novel is None or not content_limit_service.is_limited(user):
            return
        if novel.scrape_status != "completed":
            return
        if novel.metadata_id != metadata_id:
            return
        limits = content_limit_service.describe(user)
        from types import SimpleNamespace
        profile = SimpleNamespace(**limits)
        selected_metadata_id = novel.metadata_id
        authority = capture_source(db, user_id, novel)
        allowed = _run_metadata_call(content_limit_service.story_allowed(profile, selected_metadata_id), loop)
        try:
            novel = revalidate_source(db, authority)
        except HTTPException:
            return
        user = db.query(User).filter_by(id=user_id).populate_existing().first()
        if content_limit_service.describe(user) != limits:
            return
        if not allowed:
            logger.info("Story outside content limits removed", novel_id=novel_id, user_id=user_id)
            db.delete(novel)
            db.commit()
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


def is_web_serial_url(url):
    """An http(s) URL with a host that matches no known site: read as a web serial."""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def accepted_src(url):
    return supported_src(url) or is_web_serial_url(url)


def get_site_name_from_url(url):
    if not isinstance(url, str) or not url:
        return None
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
    return "webserial" if is_web_serial_url(url) else None


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

    if not accepted_src(novel.url):
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

    if content_limit_service.is_limited(current_user):
        # A story the catalog already knows is checked now; a new one once its
        # metadata scrape finishes (see scrape_within_limits).
        try:
            known = await metadata_client.get_novel_metadata(int(metadata_id)) or {}
        except Exception:  # pylint: disable=broad-except
            known = {}
        scraped = isinstance(known, dict) and known.get("status") != "scraping" and known.get("title") not in (None, "", "Scraping...")
        if scraped and not content_limit_service.item_allowed(current_user, known):
            raise content_limit_service.restricted()

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
        scrape_within_limits,
        int(novel_obj.id),
        metadata_id,
        SessionLocal,
        asyncio.get_running_loop(),
        int(current_user.id),
        job_id=scrape_result.get("job_id"),
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

        scrape_result, novel = await await_source(db, current_user.id, novel,
            metadata_client.scrape_novel_by_url, novel.url, site_name)

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
        refreshed_data, novel = await await_source(db, current_user.id, novel,
            metadata_client.refresh_novel_metadata, metadata_id)
    except HTTPException:
        raise
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

    updated_novel = novel_services.update_novel(db, novel_id, refresh_fields(db, novel, refreshed_data, novel_data))

    snapshot, novel = await await_source(db, current_user.id, novel,
        metadata_client.get_chapter_manifest, metadata_id)
    new_chapter_numbers = [chapter.chapter_number for chapter in ingest_metadata_snapshot(db, novel, snapshot)]

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

        scrape_result, novel = await await_source(db, current_user.id, novel,
            metadata_client.scrape_novel_by_url, novel.url, site_name)
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
            job_id=scrape_result.get("job_id"),
        )
    else:
        try:
            metadata_id_int = int(metadata_id)
            refreshed_data, novel = await await_source(db, current_user.id, novel,
                metadata_client.refresh_novel_metadata, metadata_id_int)

            story_id = refreshed_data.get("story_id")

            if not story_id:
                metadata_client.invalidate_novel_cache(metadata_id_int)
                chapters_data, novel = await await_source(db, current_user.id, novel,
                    metadata_client.get_chapters_from_metadata, metadata_id_int)
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
            novel_services.update_novel(db, novel_id, refresh_fields(db, novel, refreshed_data, novel_data))
        except HTTPException:
            raise
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
    from app.services.feedback_service import record_event, FOLLOW_STATE_EVENTS
    if follow.state != update.follow_state and update.follow_state in FOLLOW_STATE_EVENTS:
        record_event(db, user_id=current_user.id, novel_id=novel.id, kind=FOLLOW_STATE_EVENTS[update.follow_state])
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
                metadata, novel = await await_source(db, current_user.id, novel,
                    metadata_client.get_novel_metadata, novel.metadata_id)
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
                    novel_services.update_novel(db, novel.id, refresh_fields(db, novel, metadata, novel_data))
            except HTTPException:
                raise
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
    await content_limit_service.ensure_story_allowed(current_user, novel.metadata_id)

    if novel.metadata_id:
        try:
            metadata_client.invalidate_novel_cache(novel.metadata_id)
            metadata, novel = await await_source(db, current_user.id, novel,
                metadata_client.get_novel_metadata, novel.metadata_id)
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
                novel = novel_services.update_novel(db, novel_id, refresh_fields(db, novel, metadata, novel_data))

                snapshot, novel = await await_source(db, current_user.id, novel,
                    metadata_client.get_chapter_manifest, novel.metadata_id)
                ingest_metadata_snapshot(db, novel, snapshot)
                novel.chapter_manifest_review_required = False

                db.commit()
                db.refresh(novel)
        except HTTPException as exc:
            if not isinstance(exc.detail, dict) or exc.detail.get('code') != 'chapter_review_required':
                raise
            db.rollback()
            from app.models import Library
            novel = db.query(Novel).join(Library, Library.id == Novel.library_id).filter(
                Novel.id == novel_id, Novel.library_id == library_id, Library.user_id == current_user.id).populate_existing().first()
            if novel is None:
                raise HTTPException(404, 'Story not found')
            novel.chapter_manifest_review_required = True
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
