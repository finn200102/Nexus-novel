from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import library_organization_service as organization
from config.database import get_db

router = APIRouter(prefix="/shelves", tags=["shelves"], responses={404: {"description": "Not found"}})


class ShelfCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShelfUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    position: int | None = Field(default=None, ge=0, le=100000)


@router.get("")
def list_shelves(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return organization.list_shelves(db, current_user)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_shelf(payload: ShelfCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.create_shelf(db, current_user, payload.name)
    return organization.present_shelf(db, shelf)


@router.patch("/{shelf_id}")
def update_shelf(shelf_id: int, payload: ShelfUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shelf = organization.update_shelf(db, current_user, shelf_id, name=payload.name, position=payload.position)
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
