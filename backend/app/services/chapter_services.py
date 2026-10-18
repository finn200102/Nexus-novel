from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.chapter import Chapter


def create_chapter(db: Session, chapter_data: dict):
    """
    Create a new chapter from the chapterdata
    """
    existing = get_chapter_by_chapter_number(db, chapter_data["chapter_number"], chapter_data["novel_id"])
    if existing:
        return existing
    chapter = Chapter(**chapter_data)
    try:
        with db.begin_nested():
            db.add(chapter)
            db.flush()
    except IntegrityError:
        existing = get_chapter_by_chapter_number(db, chapter_data["chapter_number"], chapter_data["novel_id"])
        if existing:
            return existing
        raise
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
    chapter = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id)
        .filter(Chapter.chapter_number == chapter_number)
        .first()
    )
    return chapter


def delete_chapter(db: Session, chapter_id):
    """
    Preserve a removed chapter's private originals and historical references.
    """

    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if chapter:
        from datetime import UTC,datetime
        chapter.archived=True
        chapter.archived_at=datetime.now(UTC).replace(tzinfo=None)
        db.commit()


def update_chapter(db: Session, chapter_id, chapter_data):
    """
    Update the Chapter with Chapter_data which can be complete new data or just part of it
    """
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).with_for_update().first()
    if not chapter:
        return None

    if "content" in chapter_data or "document" in chapter_data:
        from app.services.chapter_version_service import retain_current
        from app.services.chapter_document import from_text
        retain_current(db, chapter)
        if "content" in chapter_data and "document" not in chapter_data:
            chapter_data = {**chapter_data, "document": from_text(chapter_data["content"] or "")}

    # Update Chapter attributes
    for key, value in chapter_data.items():
        if hasattr(chapter, key):
            setattr(chapter, key, value)

    db.commit()
    db.refresh(chapter)
    return chapter
