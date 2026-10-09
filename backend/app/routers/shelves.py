from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import library_organization_service as organization
from app.services import shelf_sharing_service as sharing
from config.database import get_db

router = APIRouter(prefix="/shelves", tags=["shelves"], responses={404: {"description": "Not found"}})


class ShelfCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShelfUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    position: int | None = Field(default=None, ge=0, le=100000)
    share_notes: bool | None = None


class ShareUpdate(BaseModel):
    permission: Literal["view", "collaborate"] = "view"


@router.get("")
def list_shelves(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return organization.list_shelves(db, current_user)


# ---------------------------------------------------------------- sharing
# Shared shelves carry catalog references only; see shelf_sharing_service.


@router.get("/shared")
def shared_with_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Shelves other users of this instance share with the current user."""
    return sharing.shared_with_me(db, current_user)


@router.get("/share-targets")
def share_targets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return sharing.share_targets(db, current_user)


@router.get("/{shelf_id}/stories")
async def shelf_stories(shelf_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """A shelf the user owns or that is shared with them, as catalog references."""
    return await sharing.shelf_stories(db, current_user, shelf_id)


@router.get("/{shelf_id}/shares")
def list_shares(shelf_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return sharing.list_shares(db, current_user, shelf_id)


@router.put("/{shelf_id}/shares/{user_id}")
def set_share(shelf_id: int, user_id: int, payload: ShareUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return sharing.set_share(db, current_user, shelf_id, user_id, payload.permission)


@router.delete("/{shelf_id}/shares/{user_id}")
def remove_share(shelf_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The owner stops sharing, or a recipient leaves the shelf (their own user id)."""
    sharing.remove_share(db, current_user, shelf_id, user_id)
    return {"deleted": True}


@router.put("/{shelf_id}/entries/{novel_id}")
async def add_own_story(shelf_id: int, novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Put a story from the current user's own library on a shelf they own or collaborate on."""
    sharing.add_own_novel(db, current_user, shelf_id, novel_id)
    return await sharing.shelf_stories(db, current_user, shelf_id)


@router.delete("/{shelf_id}/entries/{entry_id}")
async def remove_entry(shelf_id: int, entry_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sharing.remove_entry(db, current_user, shelf_id, entry_id)
    return await sharing.shelf_stories(db, current_user, shelf_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_shelf(payload: ShelfCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.create_shelf(db, current_user, payload.name)
    return organization.present_shelf(db, shelf)


@router.patch("/{shelf_id}")
def update_shelf(shelf_id: int, payload: ShelfUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.update_shelf(db, current_user, shelf_id, name=payload.name, position=payload.position)
    if payload.share_notes is not None:
        sharing.set_share_notes(db, current_user, shelf.id, payload.share_notes)
        db.refresh(shelf)
    return organization.present_shelf(db, shelf)


@router.delete("/{shelf_id}")
def delete_shelf(shelf_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    organization.delete_shelf(db, current_user, shelf_id)
    return {"deleted": True}


@router.put("/{shelf_id}/novels/{novel_id}")
def add_novel(shelf_id: int, novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.add_novel_to_shelf(db, current_user, shelf_id, novel_id)
    return organization.present_shelf(db, shelf)


@router.delete("/{shelf_id}/novels/{novel_id}")
def remove_novel(shelf_id: int, novel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.remove_novel_from_shelf(db, current_user, shelf_id, novel_id)
    return organization.present_shelf(db, shelf)
