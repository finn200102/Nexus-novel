# routers/app_passwords.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.ereader import AppPasswordCreate, AppPasswordCreated, AppPasswordItem
from app.services import app_password_service
from config.database import get_db

router = APIRouter(
    prefix="/app-passwords",
    tags=["app passwords"],
    responses={404: {"description": "Not found"}},
)


def _item(row) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "scope": row.scope,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
    }


@router.get("", response_model=list[AppPasswordItem])
def list_app_passwords(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [_item(row) for row in app_password_service.list_for_user(db, current_user.id)]


@router.post("", response_model=AppPasswordCreated, status_code=status.HTTP_201_CREATED)
def create_app_password(
    payload: AppPasswordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        row, secret = app_password_service.create(db, current_user, payload.label, payload.scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {**_item(row), "secret": secret}


@router.delete("/{app_password_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_app_password(
    app_password_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not app_password_service.revoke(db, current_user.id, app_password_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App password not found")
    return None
