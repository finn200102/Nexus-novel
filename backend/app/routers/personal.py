from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import library_organization_service as organization
from config.database import get_db

router = APIRouter(prefix="/personal", tags=["personal data"], responses={404: {"description": "Not found"}})


class PersonalWrite(BaseModel):
    notes: str | None = Field(default=None, max_length=20000)
    rating: int | None = Field(default=None, ge=1, le=5)
    user_tags: list[str] = Field(default_factory=list, max_length=60)
    # Omit to keep the stored categories; send a list to replace them.
    followed_categories: list[str] | None = Field(default=None, max_length=20)


@router.get("/novels/{novel_id}")
def get_personal(novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    organization.owned_novel(db, current_user, novel_id)
    return organization.get_personal(db, current_user, novel_id)


@router.put("/novels/{novel_id}")
def set_personal(novel_id: int, payload: PersonalWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return organization.set_personal(
        db,
        current_user,
        novel_id,
        notes=payload.notes,
        rating=payload.rating,
        user_tags=payload.user_tags,
        followed_categories=payload.followed_categories,
    )


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
