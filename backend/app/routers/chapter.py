from fastapi import APIRouter, Depends, status, HTTPException
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
from scripts.novel_downloader import download_novel_chapter
#from scripts.tts import text_to_mp3
from app.services.audio_service.tts import text_to_mp3
from pathlib import Path
import os
import sys
from dotenv import load_dotenv
import logging

import pybindings
from app.services.novel_downloader.fetcher import fetch_story_data_by_url, fetch_chapter
from app.services.novel_downloader.parser import parse_novel_data, parse_author_data, parse_chapter_data, parse_single_chapter_data
import asyncio

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
logger = logging.getLogger(__name__)

def supported_src(url):
    supported = ["www.royalroad.com",
                 "forums.spacebattles.com",
                 "www.fanfiction.net",
                 "archiveofourown.org"]
    def check_url_supported(url):
        for s in supported:
            if s in url:
                return True
        return False

    return check_url_supported(url)

def get_site_name_from_url(url):
    if "royalroad" in url:
        return 'royalroad'
    if 'fanfiction' in url:
        return 'fanfiction'
    if 'spacebattles' in url:
        return 'spacebattles'
    if 'archiveofourown' in url:
        return 'archive'

def check_chapter(db, novel_id, chapter_number, current_user):
    chapter = chapter_services.get_chapter_by_chapter_number(db, chapter_number,
                                                             novel_id)
    if not chapter:
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chapter already exists"
            )

    # Check if novel exists
    novel = novel_services.get_novel_by_id(db, chapter.novel_id)
    if not novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {chapter.novel_id} not found"
        )

    # Check if library exists
    library = library_services.get_library_by_id(db, novel.library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {novel.library_id} not found"
        )

    # Check if user owns the library
    if library.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission for this library"
        )
    return chapter


@router.post("/", response_model=ChapterSchema, status_code=status.HTTP_201_CREATED)
def add_chapter(chapter: ChapterCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):

    query = chapter_services.get_chapter_by_chapter_number(db, chapter.chapter_number,
                                                             chapter.novel_id)
    
    if query:
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chapter already exists"
            )
    # Create chapter data dictionary
    chapter_data = {
        "novel_id": chapter.novel_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "content_status": chapter.content_status.value 
    }
    new_chapter = chapter_services.create_chapter(db, chapter_data)
    
    return new_chapter

@router.get("/download/{library_id}/{novel_id:int}/{chapter_number:int}", response_model=ChapterSchema)
def download_chapter(library_id: int, novel_id: int, chapter_number: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    novel = novel_services.get_novel_by_id(db, chapter.novel_id)



    #base_dir = "/Users/finng/Home/Programmieren/Projects/nexus-novel/backend/app/downloads/"
    base_dir = os.environ.get("DOWNLOAD_PATH")

    # fetch chapter
    site_story_id = novel.site_story_id
    site_chapter_id = chapter.site_chapter_id
    site_name = get_site_name_from_url(novel.url)
    py_chapter = asyncio.run(fetch_chapter(site_story_id, chapter_number, site_chapter_id, site_name))
    chapter_data = parse_single_chapter_data(py_chapter)

    if chapter_data:
        chapter_data["content_status"] = "PRESENT"
        chapter_services.update_chapter(db, chapter.id, chapter_data)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapter did not get downloaded"
        )
    return chapter_services.get_chapter_by_id(db, chapter.id)

        

@router.get("/{novel_id:int}", response_model=list[ChapterSchema])
def get_chapters(
        novel_id: int,
        title: str = None,
        skip: int = 0,
        limit: int = 1000,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
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
def get_chapter_by_number(novel_id: int, chapter_number: int, db: Session = Depends(get_db),current_user: User = Depends(get_current_user)):
    """
    Get a single chapter by Number
    """

    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    return chapter


def check_chapter(db: Session, novel_id: int, chapter_number: int, user: User) -> Chapter:
    chapter = db.query(Chapter).filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    novel = db.query(Novel).filter_by(id=novel_id).first()
    if not novel or novel.library_id not in [lib.id for lib in user.libraries]:
        raise HTTPException(status_code=403, detail="Access denied to this novel/chapter")
    
    return chapter


from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

@router.get("/audio/{library_id}/{novel_id:int}/{chapter_number:int}", response_model=ChapterSchema)
def create_audio_chapter(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    chapter = check_chapter(db, novel_id, chapter_number, current_user)
    novel = novel_services.get_novel_by_id(db, chapter.novel_id)

    base_dir = os.environ.get("DOWNLOAD_PATH")
    if not base_dir:
        raise HTTPException(status_code=500, detail="DOWNLOAD_PATH not set in environment")

    output_file = os.path.join(base_dir, str(current_user.username), str(library_id), novel.title, f"chapter_{chapter_number}.mp3")

    # foramt text for chapter

    MIN_SENTENCES_PER_PARAGRAPH = 1
    MAX_SENTENCES_PER_PARAGRAPH = 2
    WRAP_WIDTH = 90

    sentences = nltk.sent_tokenize(chapter.content)
    paragraphs = []
    current_paragraph_sentences = []
    # Loop through the sentences and group them into paragraphs
    while sentences:
        # Decide how many sentences this paragraph will have
        num_sentences = random.randint(MIN_SENTENCES_PER_PARAGRAPH, MAX_SENTENCES_PER_PARAGRAPH)
        
        # Grab that many sentences, but not more than are left
        sentences_for_this_paragraph = sentences[:num_sentences]
        del sentences[:num_sentences] # Remove them from the main list

        # Join them into a single string for this paragraph
        paragraph_text = " ".join(sentences_for_this_paragraph)
        paragraphs.append(paragraph_text)


    # 2. Now, format each paragraph with textwrap
    formatted_paragraphs = []
    for p_text in paragraphs:
        wrapped_text = textwrap.fill(p_text, width=WRAP_WIDTH)
        formatted_paragraphs.append(wrapped_text)

    # 3. Join the formatted paragraphs with two newlines to separate them
    input_text = "\n\n".join(formatted_paragraphs)




    # Optionally mark status as PROCESSING
    chapter_services.update_chapter(db, chapter.id, {"audio_status": "PROCESSING"})

    # Run generation in background
    background_tasks.add_task(
        generate_audio_and_update_status,
        input_text,
        output_file,
        db,
        chapter.id
    )

    return chapter_services.get_chapter_by_id(db, chapter.id)

def generate_audio_and_update_status(input_text, output_file, db, chapter_id):
    logger.info(f"▶️ Starting TTS for chapter {chapter_id}")
    with open("dump", "w") as f:
        text = f.write(input_text)

    try:
        text_to_mp3(
            input_text=input_text,
            output_path=output_file,
        )
        logger.info(f"✅ Finished TTS for chapter {chapter_id}")
        chapter_services.update_chapter(db, chapter_id, {"audio_status": "PRESENT"})
    except Exception as e:
        logger.exception(f"❌ Failed TTS for chapter {chapter_id}: {e}")
        chapter_services.update_chapter(db, chapter_id, {"audio_status": "FAILED"})



import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse




@router.get("/content/library/{library_id:int}/{novel_id:int}/{chapter_number:int}/audio")
def stream_chapter_audio(
    library_id: int,
    novel_id: int,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Stream the audio (MP3) file of a chapter by library ID, novel ID, and chapter number.
    """
    logger.info("🔍 Requesting audio: library_id=%d, novel_id=%d, chapter_number=%d, user=%s",
                library_id, novel_id, chapter_number, current_user.username)

    library = library_services.get_library_by_id(db, library_id)
    if not library:
        logger.warning("❌ Library ID %d not found", library_id)
        raise HTTPException(status_code=404, detail=f"Library {library_id} not found")

    if library.user_id != current_user.id:
        logger.warning("🚫 User %s does not own library ID %d", current_user.username, library_id)
        raise HTTPException(status_code=403, detail="Forbidden")

    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        logger.warning("❌ Novel ID %d not found in library ID %d", novel_id, library_id)
        raise HTTPException(status_code=404, detail=f"Novel {novel_id} not found in library {library_id}")

    chapter = chapter_services.get_chapter_by_chapter_number(db, chapter_number, novel_id)
    if not chapter:
        logger.warning("❌ Chapter %d not found in novel %d", chapter_number, novel_id)
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found in novel {novel_id}")

    download_base = os.environ.get("DOWNLOAD_PATH")
    if not download_base:
        logger.error("❌ DOWNLOAD_PATH not set")
        raise HTTPException(status_code=500, detail="Server misconfiguration")

    story_path = os.path.join(download_base, current_user.username, str(library_id), novel.title)
    audio_file_path = os.path.join(story_path, f"chapter_{chapter_number}.mp3")

    logger.info("📁 Checking audio path: %s", audio_file_path)

    if not os.path.exists(audio_file_path):
        logger.warning("❌ Audio file missing at: %s", audio_file_path)
        raise HTTPException(status_code=404, detail=f"Audio file {audio_file_path} not found")

    logger.info("✅ Streaming file: %s", audio_file_path)
    audio_file = open(audio_file_path, "rb")
    return StreamingResponse(audio_file, media_type="audio/mpeg")



@router.get("/content/library/{library_id:int}/{novel_id:int}/{chapter_number:int}", response_model=ChapterContent)
def get_chapter_content(library_id: int, novel_id: int, chapter_number: int, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """
    Get a single chapter content by library ID, novel ID, and chapter number.
    """
    # Validate that the library exists and belongs to the user
    library = library_services.get_library_by_id(db, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {library_id} not found"
        )
    if library.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission for this library"
        )
    
    # Fetch the novel
    novel = novel_services.get_novel_by_id(db, novel_id)
    if not novel or novel.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Novel with ID {novel_id} not found in this library"
        )
    
    # Fetch the chapter
    chapter = chapter_services.get_chapter_by_chapter_number(db, chapter_number, novel_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter_number} not found in novel {novel_id}"
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
        num_sentences = random.randint(MIN_SENTENCES_PER_PARAGRAPH, MAX_SENTENCES_PER_PARAGRAPH)
        
        # Grab that many sentences, but not more than are left
        sentences_for_this_paragraph = sentences[:num_sentences]
        del sentences[:num_sentences] # Remove them from the main list

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
        content=final_story_text#chapter.content
    )





@router.delete("/{chapter_id:int}", response_model=ChapterSchema)
def delete_chapter_by_id(chapter_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    Delete a single chapter by ID
    """
    chapter = chapter_services.get_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chapter not found"
            )
    check_chapter(db, chapter.novel_id, chapter.chapter_number, current_user)
    chapter_services.delete_chapter(db, chapter_id)
    return chapter


@router.put("/", response_model=ChapterSchema)
def update_chapter(chapter: ChapterUpdate, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    Update a single chapter by chapter_data
    """
    chapter_data = {"title": chapter.title,
                    "content_status": chapter.content_status}
    ch = chapter_services.get_chapter_by_id(db, chapter.id)
    check_chapter(db, chapter.novel_id, ch.chapter_number, current_user)
    
    chapter_services.update_chapter(db, chapter.id, chapter_data)
    chapter = chapter_services.get_chapter_by_id(db, chapter.id)
    return chapter
