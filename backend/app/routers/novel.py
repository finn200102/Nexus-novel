from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import Novel as UserSchema
from ..schemas.novel import NovelCreate
from app.services.novel_services import *
from scripts.get_metadata import get_story_metadata

router = APIRouter(
    prefix="/novel",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)

@router.post("/novel", response_model=NovelSchema, status_code=status.HTTP_201_CREATED)
def add_novel(novel: NovelCreate, db: Session = Depends(get_db)):
    if get_novel_by_title(db, novel.title).first():
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Novel already exists"
            )
    
    result = create_novel(db, novel_data={"title": novel.title})
    print(result)
    
    return result
