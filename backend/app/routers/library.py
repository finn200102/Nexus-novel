from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from ..schemas.library import Library as LibrarySchema
from ..schemas.library import LibraryCreate
from app.models.user import User
from app.models.library import Library
import app.services.library_services as library_services
from app.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/library",
    tags=["librarys"],
    responses={404: {"description": "Not found"}},
)

def check_library(db, library_id, current_user):
    """
    Check if library exists and is owned by curretn user
    """
    # Check if library exists and user has access to it
    library = library_services.get_library_by_id(db, library_id)
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

    return library
    

@router.post("/", response_model=LibrarySchema, status_code=status.HTTP_201_CREATED)
def add_library(library: LibraryCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    if library_services.get_library_by_name(db, library.name):
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Library already exists"
            )

    library_data={"name": library.name,
                  "user_id": current_user.id}
    library = library_services.create_library(db, library_data)
    
    return library


@router.get("/", response_model=list[LibrarySchema])
def get_librarys(
        name: str = None,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    """
    Get librarys with pagination and optional filtering
    """
    
    # Start with base query
    query = library_services.get_librarys(db)

    # Apply filters if provided
    if name:
        query = query.filter(Library.name == name)

    query = query.filter(Library.user_id == current_user.id)

    # Apply pagination and return results
    librarys = query.offset(skip).limit(limit).all()
    return librarys


@router.get("/{library_id:int}", response_model=LibrarySchema)
def get_library_by_id(library_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """
    Get a single library by ID
    """

    library = check_library(db, library_id, current_user)
    return library
