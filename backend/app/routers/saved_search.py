from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.saved_search import SavedSearch
from app.models.user import User

router = APIRouter(prefix="/saved-searches", tags=["saved searches"])

class SavedSearchWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)
    notify_on_match: bool = False

def present(value: SavedSearch):
    return {"id": value.id, "name": value.name, "filters": value.filters or {}, "notify_on_match": value.notify_on_match, "created_at": value.created_at.isoformat(), "updated_at": value.updated_at.isoformat()}

@router.get("")
def list_saved_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [present(item) for item in db.query(SavedSearch).filter(SavedSearch.user_id == current_user.id).order_by(SavedSearch.updated_at.desc()).all()]

@router.post("", status_code=201)
def create_saved_search(payload: SavedSearchWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = SavedSearch(user_id=current_user.id, name=payload.name.strip(), filters=payload.filters, notify_on_match=payload.notify_on_match)
    db.add(item); db.commit(); db.refresh(item)
    return present(item)

@router.delete("/{search_id}")
def delete_saved_search(search_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(SavedSearch).filter(SavedSearch.id == search_id, SavedSearch.user_id == current_user.id).first()
    if not item: raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(item); db.commit(); return {"deleted": True}
