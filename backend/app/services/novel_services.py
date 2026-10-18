from sqlalchemy.orm import Session
from app.models.novel import Novel
from app.models.tag import Tag
from app.services.completion_service import create_completion_events

def create_novel(db: Session, novel_data: dict):
    # extract data if present
    tags_data = novel_data.pop("tags", [])

    novel = Novel(**novel_data)

    # check for 
    if tags_data:
        for tag_name in tags_data:
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            # create tag if not present
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            novel.tags.append(tag)

    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def get_novels(db: Session):
    """
    Returns all novels
    """

    novels = db.query(Novel)
    return novels


def get_novel_by_id(db: Session, id):
    """
    Returns novel that matches that id
    """

    novel = db.query(Novel).filter(Novel.id == id).first()
    return novel


def get_novel_by_title(db: Session, title):
    """
    Returns novels that match that title
    """

    novels = db.query(Novel).filter(Novel.title == title)
    return novels


def get_novel_by_url(db: Session, url, library_id=None):
    """
    Returns novels that match that url
    """

    novels = db.query(Novel).filter(Novel.url == url)
    if library_id is not None:
        novels = novels.filter(Novel.library_id == library_id)
    return novels


def delete_novel(db: Session, novel_id):
    """
    Deletes a novel from database
    """

    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if novel:
        from app.services.story_audio_cleanup import stage_story_audio_removal,finish_story_audio_removal
        try:
            plan=stage_story_audio_removal(db,novel)
            db.delete(novel)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finish_story_audio_removal(plan)


def update_novel(db: Session, novel_id, novel_data):
    """
    Update the novel with novel_data which can be complete new data or just part of it
    """
    novel = db.query(Novel).filter(Novel.id == novel_id).first()

    if not novel:
        return None

    # Extract tags data if present
    tags_data = novel_data.pop("tags", None)

    old_status = novel.status

    # Update novel attributes
    for key, value in novel_data.items():
        if hasattr(novel, key):
            setattr(novel, key, value)
    create_completion_events(db, novel, old_status, novel.status)

    # Handle tags if provided
    if tags_data is not None:
        # Clear existing tags if we're updating tags
        novel.tags.clear()

        # Add new tags
        for tag_name in tags_data:
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            novel.tags.append(tag)

    db.commit()
    db.refresh(novel)
    return novel
