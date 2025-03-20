from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from app.models.user import User
from ..schemas.chapter import Chapter as ChapterSchema
from ..schemas.chapter import ChapterCreate
from app.models.chapter import Chapter
import app.services.chapter_services as chapter_services
from app.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/chapter",
    tags=["librarys"],
    responses={404: {"description": "Not found"}},
)


@router.post("/", response_model=ChapterSchema, status_code=status.HTTP_201_CREATED)
def add_chapter(chapter: ChapterCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    if chapter_services.get_chapter_by_chapter_number(db, chapter.chapter_number,
                                                      chapter.novel_id):
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
