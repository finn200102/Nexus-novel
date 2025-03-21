from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.novel import Novel as NovelSchema
from ..schemas.novel import NovelCreate
from app.models.user import User
from app.models.library import Library
import app.services.novel_services as novel_services
from app.services.author_services import create_author, get_author_by_name
from app.services.library_services import get_library_by_id
from scripts.get_metadata import get_story_metadata
from app.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/novel",
    tags=["novels"],
    responses={404: {"description": "Not found"}},
)

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

    # get metadata
    metadata = get_story_metadata(novel.url)
    
    # check if author already exists
    authors = get_author_by_name(db, metadata["author"])
    # create author
    author_data = {
        "name": metadata["author"]
    }
    if authors.first():
        author = authors.first()
    else:
        author = create_author(db, author_data)

    novel_data={"url": novel.url,
                "title": metadata["title"],
                "library_id": novel.library_id
                }
    
    novel_data["author_id"] = author.id
    novel = novel_services.create_novel(db, novel_data)
    
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
    query = novel_services.get_novels(db)

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


@router.get("/search/", response_model=list[NovelSchema])
def search_novels(
        q: str,
        library_id: int,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    """
    Search novels by title (partial match)
    """
    # check library
    check_library(db, library_id, current_user)
    query = novel_services.get_novels(db).filter(Novel.title.ilike(f"%{q}%"))
    novels = query.offset(skip).limit(limit).all()
    return novels


