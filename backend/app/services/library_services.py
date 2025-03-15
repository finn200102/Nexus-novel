from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.novel import Novel
from app.models.author import Author
from app.models.library import Library
from app.models.user import User
from app.models.tag import Tag
from app.models.genre import Genre
from app.models.chapter import Chapter
from app.schemas.user import UserCreate

def create_library(db: Session, library_data: dict):
        
    library = Library(**library_data)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


def get_library_by_name(db: Session, name):
    """
    Returns Librarys that match that name
    """

    librarys = db.query(Library).filter(Library.name == name)
    return librarys


def delete_library(db: Session, library_id):
    """
    Deletes a Library from database
    """

    library = db.query(Library).filter(Library.id == library_id).first()
    if library:
        db.delete(library)
        db.commit()


def update_library(db: Session, library_id, library_data):
    """
    Update the Library with Library_data which can be complete new data or just part of it
    """
    library = db.query(Library).filter(Library.id == library_id).first()

    if not library:
        return None

    # Update Library attributes
    for key, value in library_data.items():
        if hasattr(library, key):
            setattr(library, key, value)

    db.commit()
    db.refresh(library)
    return library
