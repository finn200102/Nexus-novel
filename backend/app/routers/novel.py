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
from app.services.chapter_services import create_chapter, get_chapters
from app.services.library_services import get_library_by_id
import app.services.chapter_services as chapter_services
from scripts.get_metadata import get_story_metadata
from app.auth.dependencies import get_current_user
import os
import shutil
import pybindings
from app.services.novel_downloader.fetcher import fetch_story_data_by_url
from app.services.novel_downloader.parser import parse_novel_data, parse_author_data, parse_chapter_data
import asyncio

router = APIRouter(
    prefix="/novel",
    tags=["novels"],
    responses={404: {"description": "Not found"}},
)

def supported_src(url):
    supported = ["www.royalroad.com",
                 "forums.spacebattles.com",
                 "www.fanfiction.net"]
    def check_url_supported(url):
        for s in supported:
            if s in url:
                return True
        return False

    return check_url_supported(url)


def check_library(db, library_id, current_user):
    """
    Check if library exists and is owned by curretn user
    """
    # Check if library exists and user has access to it
    library = get_library_by_id(db, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {library_id} not found"
        )

    # Check if user owns the library
    if library.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission for this library"
        )

@router.post("/", response_model=NovelSchema, status_code=status.HTTP_201_CREATED)
def add_novel(novel: NovelCreate, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    if novel_services.get_novel_by_url(db, novel.url).first():
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Novel already exists"
            )

    # check library
    check_library(db, novel.library_id, current_user)

    # check if url is supported
    if not supported_src(novel.url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a supported source url"
            )

    # Fetch chapter data from scraper

    py_story = asyncio.run(fetch_story_data_by_url(novel.url, 'fanfiction'))

    author_data = parse_author_data(py_story)
    
    # check author is present if not create

    authors_db = get_author_by_name(db, author_data.get('name')).first()
    if authors_db:
        author = authors_db

    else:
        author = create_author(db,
                               author_data)


    # parse the novel_data

    novel_data = parse_novel_data(py_story)
    novel_data['url'] = novel.url
    novel_data['library_id'] = novel.library_id
    novel_data['cover_image'] = ""
    novel_data['author_id'] = author.id

    # create novel

    novel = novel_services.create_novel(db, novel_data)

    # parse chapters

    chapter_list = parse_chapter_data(py_story)

    # update new values

    #[c.update({'novel_id': novel.id} for c in chapter_list]

    for idx, chapter in enumerate(chapter_list):
        chapter['novel_id'] = novel.id
        create_chapter(db, chapter)

    
    return novel


@router.get("/update/chapters/{novel_id:int}", response_model=NovelSchema)
def update_novelchapters_by_id(novel_id: int,
                    library_id: int,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """
    update chapters of a single novel by ID
    """
    # check library
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found"
        )
    metadata = get_story_metadata(novel.url)
    chapter_numbers = metadata["numChapters"]
    chapters = chapter_services.get_chapters_by_novel_id(db, novel.id)
    chapter_numbers_set = {chapter.chapter_number for chapter in chapters}
    for i in range(int(chapter_numbers)):
        chapter_num = i + 1
        if chapter_num not in chapter_numbers_set:
            chapter_data = {"novel_id": novel.id,
                            "chapter_number": chapter_num,
                            "title": "",
                            "content_status": ContentStatus.MISSING}
            create_chapter(db, chapter_data)    

    return novel
    




@router.get("/", response_model=list[NovelSchema])
def get_novels(
        library_id: int,
        title: str = None,
        author_name: int = None,
        genre_id: int = None,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    """
    Get novels with pagination and optional filtering
    """
    
    # check library
    check_library(db, library_id, current_user)
    
    # Start with base query
    query = novel_services.get_novels(db).filter(Novel.library_id == library_id)

    # Apply filters if provided
    if title:
        query = query.filter(Novel.title == title)

    if author_name:
        query = query.filter(Novel.author_name == author_name)

    if genre_id:
        query = query.filter(Novel.genre_id == genre_id)

    # Apply pagination and return results
    novels = query.offset(skip).limit(limit).all()
    return novels


@router.get("/{novel_id:int}", response_model=NovelSchema)
def get_novel_by_id(novel_id: int,
                    library_id: int,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """
    Get a single novel by ID
    """
    # check library
    check_library(db, library_id, current_user)
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found"
        )
    return novel


@router.post("/delete/{novel_id:int}", response_model=NovelSchema)
def delete_novel_by_id(novel_id: int, library_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """
    Delete a single novel by ID
    """
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found"
        )

    library = check_library(db, library_id, current_user)
    # delete local files
    base_dir = os.environ.get("DOWNLOAD_PATH")
    base_dir = os.path.join(base_dir, str(current_user.username), str(library_id))
    novel_path = os.path.join(base_dir, novel.title)
    
    if os.path.isdir(novel_path):
        shutil.rmtree(novel_path)
    else:
        print(f"Directory does not exist: {novel_path}")


    novel_services.delete_novel(db, novel.id)
    return novel


@router.post("/update/", response_model=NovelSchema)
def update_novel(novel: NovelUpdate, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    Update a single novel by novel_data
    """
    novel_data={"title": novel.title,
                "url": novel.url}
    novel = novel_services.get_novel_by_id(db, novel.id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel.id} not found"
        )
    library = check_library(db, novel.id, current_user)

    

    novel = novel_services.update_novel(db, novel.id, novel_data)
    return novel
