from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.novel import Novel
from app.models.tag import Tag
from app.models.genre import Genre
from app.models.chapter import Chapter


def create_chapter(db: Session, chapter_data: dict):
    """
    Create a new chapter from the chapterdata
    """
    chapter = Chapter(**chapter_data)
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter

def get_chapters(db: Session):
    """
    Returns all chapters
    """

    chapters = db.query(Chapter)
    return chapters

def get_chapter_by_id(db: Session, id):
    """
    Returns chapter that matches that id
    """

    chapter = db.query(Chapter).filter(Chapter.id == id).first()
    return chapter

def get_chapters_by_novel_id(db: Session, novel_id):
    """
    Returns chapters that matches that novel_id
    """

    chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id)
    return chapters

def get_chapter_by_chapter_number(db: Session, chapter_number, novel_id):
    """
    Returns chapter with chapter_number and novel_id
    """
    chapter = db.query(Chapter).filter(Chapter.novel_id == novel_id).filter(Chapter.chapter_number == chapter_number).first()
    return chapter
