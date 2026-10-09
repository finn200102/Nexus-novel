from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import library_organization_service as organization
from config.database import get_db

router = APIRouter(prefix="/personal", tags=["personal data"], responses={404: {"description": "Not found"}})


class PersonalWrite(BaseModel):
    """A partial update: only the fields present in the request body change.

    Send ``notes`` or ``rating`` as null to clear them. ``user_tags`` replaces
    the tag list. Null for ``followed_categories``, ``auto_download`` and
    ``keep_ahead`` leaves the stored value alone.
    """

    notes: str | None = Field(default=None, max_length=20000)
    rating: int | None = Field(default=None, ge=1, le=5)
    user_tags: list[str] | None = Field(default=None, max_length=60)
    followed_categories: list[str] | None = Field(default=None, max_length=20)
    auto_download: bool | None = None
    keep_ahead: int | None = Field(default=None, ge=1, le=200)
    notify_when_complete: bool | None = None


@router.get("/novels/{novel_id}")
def get_personal(novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    organization.owned_novel(db, current_user, novel_id)
    return organization.get_personal(db, current_user, novel_id)


@router.put("/novels/{novel_id}")
def set_personal(novel_id: int, payload: PersonalWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return organization.set_personal(db, current_user, novel_id, payload.model_dump(exclude_unset=True))


@router.get("/tags")
def user_tags(q: str = Query("", max_length=60), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The user's own tags for autocomplete, most used first."""
    return {"tags": organization.user_tag_vocabulary(db, current_user, q)}


@router.get("/library/{library_id}")
def library_personal(library_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Notes flag, rating, user tags and shelf ids for every novel in one library."""
    novel_ids = organization.library_novel_ids(db, current_user, library_id)
    personal = organization.personal_for_novels(db, current_user, novel_ids)
    shelves = organization.shelf_ids_by_novel(db, current_user, novel_ids)
    return {
        "novels": {
            str(novel_id): {**data, "shelf_ids": shelves.get(novel_id, [])}
            for novel_id, data in personal.items()
        }
    }
