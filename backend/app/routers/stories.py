"""The story page's view of a catalog story: where it sits in the user's libraries.

A story is identified by its catalog (metadata) id. The same work can be in
several of the user's libraries, each a separate library novel, so this
returns every copy. Catalog facts come from ``/discovery/novels/{id}``.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from config.database import get_db

router = APIRouter(prefix="/stories", tags=["stories"], responses={404: {"description": "Not found"}})


@router.get("/{metadata_id:int}")
def get_story(metadata_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The current user's library copies of a catalog story (empty when not in a library)."""
    rows = (
        db.query(Novel, Library)
        .join(Library, Novel.library_id == Library.id)
        .filter(Library.user_id == current_user.id, Novel.metadata_id == metadata_id)
        .order_by(Library.name, Novel.id)
        .all()
    )
    return {
        "metadata_id": metadata_id,
        "library_entries": [
            {
                "novel_id": novel.id,
                "library_id": library.id,
                "library_name": library.name,
                "title": novel.title,
                "follow_state": novel.follow_state,
                "scrape_status": novel.scrape_status,
            }
            for novel, library in rows
        ],
    }
