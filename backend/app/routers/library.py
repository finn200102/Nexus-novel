from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.library import Library as LibrarySchema
from ..schemas.library import LibraryCreate
import app.services.library_services as library_services

router = APIRouter(
    prefix="/library",
    tags=["librarys"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=LibrarySchema, status_code=status.HTTP_201_CREATED)
def add_library(library: LibraryCreate, db: Session = Depends(get_db)):
    if library_services.get_library_by_name(db, library.name):
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Library already exists"
            )

    library_data={"name": library.name}
    library = library_services.create_library(db, library_data)
    
    return library


@router.get("/", response_model=list[LibrarySchema])
def get_librarys(
        name: str = None,
        user_id: int = None,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db)):
    """
    Get librarys with pagination and optional filtering
    """
    # Start with base query
    query = library_services.get_librarys(db)

    # Apply filters if provided
    if name:
        query = query.filter(Library.name == name)

    if user_id:
        query = query.filter(Library.user_id == user_id)

    # Apply pagination and return results
    librarys = query.offset(skip).limit(limit).all()
    return librarys


@router.get("/{library_id:int}", response_model=LibrarySchema)
def get_library_by_id(library_id: int, db: Session = Depends(get_db)):
    """
    Get a single library by ID
    """
    library = library_services.get_library_by_id(db, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library with ID {library_id} not found"
        )
    return library
