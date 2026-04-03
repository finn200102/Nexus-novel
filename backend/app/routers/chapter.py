from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from config.database import get_db
from app.models.user import User
from ..schemas.chapter import Chapter as ChapterSchema
from ..schemas.chapter import ChapterCreate, ChapterUpdate, ChapterContent
from app.models.chapter import Chapter
from app.models.novel import Novel
import app.services.chapter_services as chapter_services
import app.services.library_services as library_services
import app.services.novel_services as novel_services
from app.auth.dependencies import get_current_user
from app.models.chapter import ContentStatus

from pathlib import Path
import os
import sys
from dotenv import load_dotenv
from app.logging_config import get_logger, get_request_id

import pybindings
from app.services.novel_downloader.fetcher import fetch_story_data_by_url, fetch_chapter
from app.services import metadata_client
from app.services.novel_downloader.parser import (
    parse_novel_data,
    parse_author_data,
    parse_chapter_data,
    parse_single_chapter_data,
)
import asyncio
from datetime import datetime

import textwrap
import nltk
import random

# Load environment variables
load_dotenv()

router = APIRouter(
    prefix="/chapter",
    tags=["chapters"],
    responses={404: {"description": "Not found"}},
)
logger = get_logger(__name__)


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

        current_retry_count = chapter.retry_count or 0
        chapter_services.update_chapter(
            db,
            chapter_id,
            {
                "content_status": ContentStatus.PROCESSING,
                "download_started_at": datetime.utcnow(),
                "download_finished_at": None,
                "download_error": None,
                "retry_count": current_retry_count + 1,
            },
        )

        novel = novel_services.get_novel_by_id(db, novel_id)
        if not novel:
            logger.error("Novel not found for background download", novel_id=novel_id)
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.utcnow(),
                    "download_error": "Novel not found",
                },
            )
            return

        site_story_id = novel.story_id or novel.site_story_id
        metadata_id = novel.metadata_id
        site_name = get_site_name_from_url(novel.url)

        logger.info(
            "Starting story_id resolution",
            extra={
                "novel_id": novel_id,
                "current_story_id": site_story_id,
                "metadata_id": metadata_id,
            },
        )

        if not site_story_id and metadata_id:
            logger.info(
                "story_id is null, trying to fetch from metadata",
                extra={"novel_id": novel_id},
            )

            try:
                metadata_client.cache.invalidate(f"novel:{int(metadata_id)}")
                metadata_data = asyncio.run(
                    metadata_client.get_novel_metadata(int(metadata_id))
                )
                fetched_story_id = (
                    metadata_data.get("story_id") if metadata_data else None
                )
                logger.info(
                    "get_novel_metadata response",
                    extra={
                        "metadata_id": metadata_id,
                        "has_data": bool(metadata_data),
                        "story_id": fetched_story_id,
                    },
                )

                if fetched_story_id:
                    site_story_id = fetched_story_id
                    logger.info(
                        "Got story_id from get_novel_metadata",
                        extra={"novel_id": novel_id, "story_id": site_story_id},
                    )
                    novel_services.update_novel(
                        db,
                        novel.id,
                        {
                            "story_id": fetched_story_id,
                            "site_story_id": fetched_story_id,
                        },
                    )
                else:
                    logger.warning(
                        "get_novel_metadata returned null story_id, trying chapters endpoint",
                        extra={"metadata_id": metadata_id},
                    )
            except Exception as e:
                logger.error(
                    "Failed to get story_id from metadata",
                    extra={"metadata_id": metadata_id, "error": str(e)},
                )

        if not site_story_id and metadata_id:
            logger.info(
                "Trying to get story_id from chapters metadata",
                extra={"novel_id": novel_id},
            )
            try:
                metadata_client.invalidate_novel_cache(int(metadata_id))
                chapters_data = asyncio.run(
                    metadata_client.get_chapters_from_metadata(int(metadata_id))
                )
                chapter_count = len(chapters_data) if chapters_data else 0
                first_story_id = (
                    chapters_data[0].get("story_id") if chapters_data else None
                )
                logger.info(
                    "get_chapters_from_metadata response",
                    extra={
                        "metadata_id": metadata_id,
                        "chapter_count": chapter_count,
                        "first_story_id": first_story_id,
                    },
                )

                if chapters_data and len(chapters_data) > 0:
                    fetched_story_id = chapters_data[0].get("story_id")
                    if fetched_story_id:
                        site_story_id = fetched_story_id
                        logger.info(
                            "Got story_id from chapters metadata",
                            extra={"novel_id": novel_id, "story_id": site_story_id},
                        )
                        novel_services.update_novel(
                            db,
                            novel.id,
                            {
                                "story_id": fetched_story_id,
                                "site_story_id": fetched_story_id,
                            },
                        )
                    else:
                        logger.warning(
                            "No story_id found in chapters metadata either",
                            extra={"metadata_id": metadata_id},
                        )
            except Exception as e:
                logger.error(
                    "Failed to get story_id from chapters metadata",
                    extra={"metadata_id": metadata_id, "error": str(e)},
                )

        if not site_story_id:
            logger.info(
                "story_id is null, extracting from URL",
                extra={"novel_id": novel_id},
            )
            import re

            novel_url = str(novel.url) if novel.url else ""
            match = re.search(r"/book/[^_]+_(\d+)", novel_url)
            if match:
                site_story_id = match.group(1)
                logger.info(
                    "Extracted story_id from URL",
                    extra={"novel_id": novel_id, "story_id": site_story_id},
                )
            else:
                logger.error("Could not extract story_id from URL", novel_id=novel_id)
                chapter_services.update_chapter(
                    db,
                    chapter_id,
                    {
                        "content_status": ContentStatus.FAILED,
                        "download_finished_at": datetime.utcnow(),
                        "download_error": "Could not determine story_id from URL",
                    },
                )
                return

        site_chapter_id = chapter.site_chapter_id
        if site_chapter_id is None:
            logger.error(
                "Chapter missing site_chapter_id for background download",
                chapter_id=chapter_id,
            )
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.utcnow(),
                    "download_error": "Chapter missing site_chapter_id",
                },
            )
            return

        if not site_name:
            logger.error(
                "Could not determine site name for background download",
                novel_id=novel_id,
            )
            chapter_services.update_chapter(
                db,
                chapter_id,
                {
                    "content_status": ContentStatus.FAILED,
                    "download_finished_at": datetime.utcnow(),
                    "download_error": "Could not determine site name from URL",
                },
            )
            return

        try:
            import time
            import asyncio

            start_time = time.time()
            try:
                py_chapter = asyncio.run(
                    fetch_chapter(
                        int(site_story_id),
                        chapter_number,
                        int(site_chapter_id),
                        site_name,
                        timeout=60.0,
                    )
                )
            except asyncio.TimeoutError:
                logger.error("Chapter download timed out", chapter_id=chapter_id)
                chapter_services.update_chapter(
                    db,
                    chapter_id,
                    {
                        "content_status": ContentStatus.FAILED,
                        "download_finished_at": datetime.utcnow(),
                        "download_error": "Download timed out after 60 seconds",
                    },
                )
                return
            elapsed = time.time() - start_time
            logger.info(
                f"Chapter download took {elapsed:.2f} seconds", chapter_id=chapter_id
            )

            chapter_data = parse_single_chapter_data(py_chapter)

            if chapter_data:
                chapter_data["content_status"] = ContentStatus.PRESENT
                chapter_data["download_finished_at"] = datetime.utcnow()
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
                        "download_finished_at": datetime.utcnow(),
                        "download_error": "No data returned from scraper",
                    },
                )
                logger.error(
                    "Background chapter download failed - no data returned",
                    chapter_id=chapter_id,
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
                    "download_finished_at": datetime.utcnow(),
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
    return None


def check_chapter(db, novel_id, chapter_number, current_user):
    chapter = chapter_services.get_chapter_by_chapter_number(
        db, chapter_number, novel_id
    )
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Chapter already exists"
        )

    # Check if novel exists
    novel = novel_services.get_novel_by_id(db, chapter.novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {chapter.novel_id} not found",
        )

    # Check if library exists
    library = library_services.get_library_by_id(db, novel.library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {novel.library_id} not found",
        )

    # Check if user owns the library
    if library.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission for this library",
        )
    return chapter


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

    chapter_services.update_chapter(
        db, chapter.id, {"content_status": ContentStatus.PROCESSING}
    )

    background_tasks.add_task(
        download_chapter_background,
        chapter.id,
        novel_id,
        chapter_number,
        library_id,
        SessionFactory,
    )

    return chapter


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
    # foramt text for chapter

    MIN_SENTENCES_PER_PARAGRAPH = 3
    MAX_SENTENCES_PER_PARAGRAPH = 5
    WRAP_WIDTH = 90

    sentences = nltk.sent_tokenize(chapter.content)
    paragraphs = []
    current_paragraph_sentences = []
    # Loop through the sentences and group them into paragraphs
    while sentences:
        # Decide how many sentences this paragraph will have
        num_sentences = random.randint(
            MIN_SENTENCES_PER_PARAGRAPH, MAX_SENTENCES_PER_PARAGRAPH
        )

        # Grab that many sentences, but not more than are left
        sentences_for_this_paragraph = sentences[:num_sentences]
        del sentences[:num_sentences]  # Remove them from the main list

        # Join them into a single string for this paragraph
        paragraph_text = " ".join(sentences_for_this_paragraph)
        paragraphs.append(paragraph_text)

    # 2. Now, format each paragraph with textwrap
    formatted_paragraphs = []
    for p_text in paragraphs:
        wrapped_text = textwrap.fill(p_text, width=WRAP_WIDTH)
        formatted_paragraphs.append(wrapped_text)

    # 3. Join the formatted paragraphs with two newlines to separate them
    final_story_text = "\n\n".join(formatted_paragraphs)

    return ChapterContent(
        id=chapter.id,
        novel_id=chapter.novel_id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        content=final_story_text,  # chapter.content
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
