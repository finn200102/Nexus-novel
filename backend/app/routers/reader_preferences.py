import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.reader_preference import ReaderPreference, ReaderPreferenceOperation
from app.models.user import User
from app.routers.reader_tools import own_novel
from config.database import get_db
from app.schemas.reader_preferences import PreferenceWrite,ReaderPreferenceResponse

router = APIRouter(prefix="/reader/preferences", tags=["reader preferences"])


def view(scope, row):
    return {"scope": scope, "revision": row.revision if row else 0, "values": row.values if row else {}}


def read(db, user, novel_id=None):
    if novel_id is not None:
        own_novel(db, user, novel_id)
    scope = f"story:{novel_id}" if novel_id is not None else "global"
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=scope).first()
    return view(scope, row)


def write(db, user, value, novel_id=None):
    if novel_id is not None:
        own_novel(db, user, novel_id)
        if value.values.model_fields_set - {"typography"}:
            raise HTTPException(422, detail="Per-story settings contain only typography; layout and controls are account defaults.")
    scope = f"story:{novel_id}" if novel_id is not None else "global"
    # Serialize first writes and revisions, including independently created scopes.
    db.query(User).filter(User.id == user.id).with_for_update().first()
    payload = {"scope": scope, **value.model_dump()}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    previous = db.query(ReaderPreferenceOperation).filter_by(user_id=user.id, operation_id=value.operation_id).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, detail="This operation id already belongs to another settings change.")
        return previous.response
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=scope).first()
    current = view(scope, row)
    if current["revision"] != value.expected_revision:
        raise HTTPException(409, detail={"message": "Settings changed on another device.", "current": current})
    if row is None:
        row = ReaderPreference(user_id=user.id, novel_id=novel_id, scope=scope, revision=0)
        db.add(row)
    row.values = value.values.model_dump(exclude_none=True)
    row.revision += 1
    response = view(scope, row)
    db.add(ReaderPreferenceOperation(user_id=user.id, operation_id=value.operation_id, fingerprint=fingerprint, response=response))
    db.commit()
    return response


@router.get("", response_model=ReaderPreferenceResponse, response_model_exclude_unset=True)
def global_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return read(db, user)


@router.put("", response_model=ReaderPreferenceResponse, response_model_exclude_unset=True)
def save_global(value: PreferenceWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return write(db, user, value)


@router.get("/stories/{novel_id}", response_model=ReaderPreferenceResponse, response_model_exclude_unset=True)
def story_preferences(novel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return read(db, user, novel_id)


@router.put("/stories/{novel_id}", response_model=ReaderPreferenceResponse, response_model_exclude_unset=True)
def save_story(novel_id: int, value: PreferenceWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return write(db, user, value, novel_id)
