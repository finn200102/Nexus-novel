from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import Novel as NovelSchema
from ..schemas.novel import NovelCreate
from app.services.novel_services import *
from app.services.author_services import create_author
from scripts.get_metadata import get_story_metadata

router = APIRouter(
    prefix="/novel",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)

@router.post("/add", response_model=NovelSchema, status_code=status.HTTP_201_CREATED)
def add_novel(novel: NovelCreate, db: Session = Depends(get_db)):
    if get_novel_by_url(db, novel.url).first():
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Novel already exists"
            )
    # get metadata
    metadata = get_story_metadata(novel.url)
    # create author
    author_data = {
        "name": metadata["author"]
    }
    author = create_author(db, author_data)


    novel_data={"url": novel.url,
                "title": metadata["title"]}
    if author:
        novel_data["author_id"] = author.id
    novel = create_novel(db, novel_data)
    
    return novel


