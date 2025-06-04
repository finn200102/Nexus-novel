from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.novel import Novel
from app.models.author import Author
from app.models.tag import Tag
from app.models.genre import Genre
from app.models.chapter import Chapter

def create_author(db: Session, author_data: dict):

    # check if author already exists
    if db.query(Author).filter(Author.name == author_data["name"]).first():
        return None

    author = Author(**author_data)
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


def get_author_by_name(db: Session, name):
    """
    Returns authors that match that name
    """

    authors = db.query(Author).filter(Author.name == name)
    return authors


def get_author_by_id(db: Session, id):
    """
    Returns author that match that id
    """
    author = db.query(Author).filter(Author.id == id).first()
    if not author:
        return None
    return author


def delete_author(db: Session, author_id):
    """
    Deletes a author from database
    """

    author = db.query(Author).filter(Author.id == author_id).first()
    if author:
        db.delete(author)
        db.commit()


def update_author(db: Session, author_id, author_data):
    """
    Update the author with author_data which can be complete new data or just part of it
    """
    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        return None

    # Update author attributes
    for key, value in author_data.items():
        if hasattr(author, key):
            setattr(author, key, value)

    db.commit()
    db.refresh(author)
    return author
