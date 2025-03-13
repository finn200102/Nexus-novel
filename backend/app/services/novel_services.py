from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.novel import Novel
from app.models.tag import Tag
from app.models.genre import Genre
from app.models.chapter import Chapter

def create_novel(db: Session, novel_data: dict):
    # extract data if present
    tags_data = novel_data.pop("tags", [])

    novel = Novel(**novel_data)

    # check for tag
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
            
