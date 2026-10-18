from sqlalchemy.orm import Session
from app.models.library import Library

def create_library(db: Session, library_data: dict):
        
    library = Library(**library_data)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


def get_librarys(db: Session):
    """
    Returns all librarys
    """

    librarys = db.query(Library)
    return librarys


def get_library_by_id(db: Session, id):
    """
    Returns library that matches that id
    """

    library = db.query(Library).filter(Library.id == id).first()
    return library

def get_library_by_name(db: Session, name, user_id=None):
    """
    Returns library that matches that name
    """

    query = db.query(Library).filter(Library.name == name)
    if user_id is not None:
        query = query.filter(Library.user_id == user_id)
    library = query.first()
    return library


def delete_library(db: Session, library_id):
    """
    Deletes a Library from database
    """

    library = db.query(Library).filter(Library.id == library_id).first()
    if library:
        from app.services.story_audio_cleanup import stage_story_audio_removal,finish_story_audio_removal
        try:
            plans=[stage_story_audio_removal(db,novel) for novel in list(library.novels)]
            db.delete(library)
            db.commit()
        except Exception:
            db.rollback()
            raise
        for plan in plans:
            finish_story_audio_removal(plan)


def update_library(db: Session, library_id, library_data):
    """
    Update the Library with Library_data which can be complete new data or just part of it
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    print("here in update", library)
    print(library_data)
    if not library:
        return None

    # Update Library attributes
    for key, value in library_data.items():
        if hasattr(library, key):
            setattr(library, key, value)

    db.commit()
    db.refresh(library)
    return library
