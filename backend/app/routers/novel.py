from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import Novel as NovelSchema
from ..schemas.novel import NovelCreate, NovelUpdate
from app.models.chapter import ContentStatus
from app.models.user import User
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.library import Library
import app.services.novel_services as novel_services
from app.services.author_services import create_author, get_author_by_name
from app.services.chapter_services import (
    create_chapter,
    get_chapters,
    get_chapters_by_novel_id,
)
from app.services.library_services import get_library_by_id
import app.services.chapter_services as chapter_services
from app.auth.dependencies import get_current_user
from app.services import metadata_client
from app.logging_config import get_logger
import os
import shutil

logger = get_logger(__name__)

router = APIRouter(
    prefix="/novel",
    tags=["novels"],
    responses={404: {"description": "Not found"}},
)


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if novel_services.get_novel_by_url(db, novel.url).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Novel already exists"
        )

    check_library(db, novel.library_id, current_user)

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

    scraped_data = await metadata_client.scrape_novel_by_url(novel.url, site_name)

    metadata_id = (
        scraped_data.get("id") if scraped_data and scraped_data.get("id") else None
    )

    if (
        not metadata_id
        and scraped_data is None
        or (scraped_data and not scraped_data.get("id"))
    ):
        try:
            search_result = await metadata_client.search_novel_by_url(novel.url)
            if search_result and search_result.get("data"):
                metadata_id = search_result["data"][0].get("id")
                scraped_data = search_result["data"][0]
        except Exception as e:
            logger.warning(
                "Error searching for novel",
                extra={"extra": {"error": str(e), "url": novel.url}},
            )

    title_from_url = novel.url.split("/")[-1] if novel.url else "New Novel"

    if scraped_data and scraped_data.get("title"):
        title = scraped_data.get("title")
    else:
        title = title_from_url.replace("-", " ").title()

    if scraped_data and scraped_data.get("author"):
        author_name = scraped_data.get("author")
        authors_db = get_author_by_name(db, author_name).first()
        if authors_db:
            author = authors_db
        else:
            author_data = {
                "name": author_name,
                "site_author_id": scraped_data.get("author_id")
                if scraped_data
                else None,
                "site": site_name,
            }
            author = create_author(db, author_data)
    else:
        author = None
        author_name = None

    novel_data = {
        "title": title,
        "url": novel.url,
        "library_id": novel.library_id,
        "metadata_id": metadata_id,
        "author": author_name,
        "author_site_id": scraped_data.get("author_id") if scraped_data else None,
        "author_id": author.id if author else None,
        "source_url": scraped_data.get("source_url") if scraped_data else None,
        "story_id": scraped_data.get("story_id") if scraped_data else None,
        "site_story_id": scraped_data.get("story_id") if scraped_data else None,
        "novel_site": scraped_data.get("novel_site") if scraped_data else site_name,
        "img_url": scraped_data.get("img_url") if scraped_data else None,
        "description": scraped_data.get("description") if scraped_data else None,
        "word_count": scraped_data.get("word_count") if scraped_data else None,
        "reviews": scraped_data.get("reviews") if scraped_data else None,
        "favorites": scraped_data.get("favorites") if scraped_data else None,
        "follows": scraped_data.get("follows") if scraped_data else None,
        "status": scraped_data.get("status") if scraped_data else None,
        "views": scraped_data.get("views") if scraped_data else None,
        "rating": scraped_data.get("rating") if scraped_data else None,
        "publish_date": scraped_data.get("publish_date") if scraped_data else None,
        "updated_date": scraped_data.get("updated_date") if scraped_data else None,
        "chapter_count": scraped_data.get("chapter_count") if scraped_data else None,
        "analyzed_at": scraped_data.get("analyzed_at") if scraped_data else None,
        "analysis_type": scraped_data.get("analysis_type") if scraped_data else None,
        "analyzed_chapter_count": scraped_data.get("analyzed_chapter_count")
        if scraped_data
        else None,
        "parsed_at": scraped_data.get("parsed_at") if scraped_data else None,
    }

    novel_obj = novel_services.create_novel(db, novel_data)

    if metadata_id:
        try:
            chapters_data = await metadata_client.get_chapters_from_metadata(
                metadata_id
            )
            for chapter_meta in chapters_data:
                chapter_data = {
                    "novel_id": novel_obj.id,
                    "chapter_number": chapter_meta.get("chapter_number"),
                    "title": chapter_meta.get("title"),
                    "site_chapter_id": chapter_meta.get("chapter_id"),
                    "word_count": chapter_meta.get("word_count"),
                    "content_status": ContentStatus.MISSING,
                }
                create_chapter(db, chapter_data)
        except Exception as e:
            logger.warning(
                "Error fetching chapters",
                extra={"extra": {"error": str(e), "novel_id": novel_obj.id}},
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
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    if not novel.metadata_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Novel does not have metadata_id - cannot refresh",
        )

    refreshed_data = await metadata_client.refresh_novel_metadata(novel.metadata_id)

    novel_data = {
        "title": refreshed_data.get("title"),
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
    }

    updated_novel = novel_services.update_novel(db, novel_id, novel_data)

    chapters_data = await metadata_client.get_chapters_from_metadata(novel.metadata_id)
    existing_chapter_numbers = {
        ch.chapter_number for ch in get_chapters_by_novel_id(db, novel_id).all()
    }

    for chapter_meta in chapters_data:
        chapter_num = chapter_meta.get("chapter_number")
        if chapter_num not in existing_chapter_numbers:
            chapter_data = {
                "novel_id": novel_id,
                "chapter_number": chapter_num,
                "title": chapter_meta.get("title"),
                "site_chapter_id": chapter_meta.get("chapter_id"),
                "word_count": chapter_meta.get("word_count"),
                "content_status": ContentStatus.MISSING,
            }
            create_chapter(db, chapter_data)

    metadata_client.invalidate_novel_cache(novel.metadata_id)

    return updated_novel


@router.get("/update/chapters/{novel_id:int}", response_model=NovelSchema)
def update_novelchapters_by_id(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    return novel


@router.get("/", response_model=list[NovelSchema])
async def get_novels(
    library_id: int,
    title: str = "",
    search: str = "",
    author_name: str | None = None,
    genre_id: int | None = None,
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

    novels = query.offset(skip).limit(limit).all()

    for novel in novels:
        if novel.metadata_id and not novel.title:
            try:
                metadata_client.invalidate_novel_cache(novel.metadata_id)
                metadata = await metadata_client.get_novel_metadata(novel.metadata_id)
                if metadata and metadata.get("title"):
                    novel_data = {
                        "title": metadata.get("title"),
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
                    extra={"extra": {"error": str(e), "novel_id": novel.id}},
                )

    db.commit()

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
    if not novel:
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
                    "title": metadata.get("title"),
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
                existing_chapter_numbers = {ch.chapter_number for ch in novel.chapters}
                for chapter_meta in chapters_data:
                    chapter_num = chapter_meta.get("chapter_number")
                    if chapter_num not in existing_chapter_numbers:
                        chapter_data = {
                            "novel_id": novel_id,
                            "chapter_number": chapter_num,
                            "title": chapter_meta.get("title"),
                            "site_chapter_id": chapter_meta.get("chapter_id"),
                            "word_count": chapter_meta.get("word_count"),
                            "content_status": ContentStatus.MISSING,
                        }
                        create_chapter(db, chapter_data)

                db.commit()
                db.refresh(novel)
        except Exception as e:
            logger.warning(
                "Error fetching metadata",
                extra={"extra": {"error": str(e), "novel_id": novel_id}},
            )

    return novel


@router.post("/delete/{novel_id:int}", response_model=NovelSchema)
def delete_novel_by_id(
    novel_id: int,
    library_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found",
        )

    library = check_library(db, library_id, current_user)
    base_dir = os.environ.get("DOWNLOAD_PATH")
    base_dir = os.path.join(base_dir, str(current_user.username), str(library_id))
    novel_path = os.path.join(base_dir, novel.title)

    if os.path.isdir(novel_path):
        shutil.rmtree(novel_path)
    else:
        logger.debug("Directory does not exist", extra={"extra": {"path": novel_path}})

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
    library = check_library(db, novel.library_id, current_user)

    novel = novel_services.update_novel(db, novel.id, novel_data)
    return novel
