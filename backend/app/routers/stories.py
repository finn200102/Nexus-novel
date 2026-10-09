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
from app.services import metadata_client
from app.services.hiatus_view import hiatus_view
from config.database import get_db

router = APIRouter(prefix="/stories", tags=["stories"], responses={404: {"description": "Not found"}})


@router.get("/{metadata_id:int}")
async def get_story(metadata_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The current user's library copies of a catalog story (empty when not in a library), plus hiatus info."""
    rows = (
        db.query(Novel, Library)
        .join(Library, Novel.library_id == Library.id)
        .filter(Library.user_id == current_user.id, Novel.metadata_id == metadata_id)
        .order_by(Library.name, Novel.id)
        .all()
    )
    try:
        raw_hiatus = await metadata_client.get_hiatus_status(metadata_id)
    except RuntimeError:
        raw_hiatus = None
    # Source link: the original story page and site, taken from the first library copy.
    source = None
    if rows:
        first = rows[0][0]
        source = {
            "url": first.source_url or first.url,
            "site": first.novel_site,
        }
    return {
        "metadata_id": metadata_id,
        "hiatus": hiatus_view(raw_hiatus),
        "source": source,
        "library_entries": [
            {
                "novel_id": novel.id,
                "library_id": library.id,
                "library_name": library.name,
                "title": novel.title,
                "follow_state": novel.follow_state,
                "scrape_status": novel.scrape_status,
                "source_url": novel.source_url or novel.url,
                "site": novel.novel_site,
            }
            for novel, library in rows
        ],
    }
