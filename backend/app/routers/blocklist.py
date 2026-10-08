from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.blocklist import BlocklistEntry
from app.models.user import User
from app.services import blocklist_service
from config.database import get_db

router = APIRouter(prefix="/blocklist", tags=["blocklist"], responses={404: {"description": "Not found"}})


class BlocklistEntryWrite(BaseModel):
    kind: Literal["tag", "fandom", "genre", "author", "word"]
    value: str = Field(min_length=1, max_length=200)


def present(entry: BlocklistEntry) -> dict:
    return {"id": entry.id, "kind": entry.kind, "value": entry.value, "created_at": entry.created_at.isoformat() if entry.created_at else None}


@router.get("")
def list_blocklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [present(entry) for entry in blocklist_service.list_entries(db, current_user)]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_blocklist_entry(payload: BlocklistEntryWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    value = blocklist_service.normalize_value(payload.value)
    if not value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Value is required")
    existing = (
        db.query(BlocklistEntry)
        .filter(BlocklistEntry.user_id == current_user.id, BlocklistEntry.kind == payload.kind, BlocklistEntry.value == value)
        .first()
    )
    if existing:
        return present(existing)
    entry = BlocklistEntry(user_id=current_user.id, kind=payload.kind, value=value)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return present(entry)


@router.delete("/{entry_id}")
def delete_blocklist_entry(entry_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    entry = db.query(BlocklistEntry).filter(BlocklistEntry.id == entry_id, BlocklistEntry.user_id == current_user.id).first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blocklist entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": True}
