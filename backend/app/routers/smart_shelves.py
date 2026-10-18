from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response, Path
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models import SmartShelf, User
from app.schemas.smart_shelf import SmartShelfWrite, SmartShelfUpdate, SmartShelfResponse, SmartShelfPageInput, SmartShelfResults, SmartShelfDeleted
from app.services import smart_shelf_service as service


def private(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


router = APIRouter(prefix='/smart-shelves', tags=['smart shelves'], dependencies=[Depends(private)])
SmartShelfId = Annotated[int, Path(ge=1, le=2147483647)]


@router.get('', response_model=list[SmartShelfResponse])
def list_shelves(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [service.present(db, row) for row in db.query(SmartShelf).filter_by(user_id=user.id).order_by(SmartShelf.name_key, SmartShelf.id)]


@router.post('', status_code=201, response_model=SmartShelfResponse)
def create_shelf(payload: SmartShelfWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.create(db, user.id, payload)


@router.put('/{shelf_id}', response_model=SmartShelfResponse)
def update_shelf(shelf_id: SmartShelfId, payload: SmartShelfUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.update(db, user.id, shelf_id, payload)


@router.delete('/{shelf_id}', response_model=SmartShelfDeleted)
def delete_shelf(shelf_id: SmartShelfId, expected_revision: str = Query(pattern=r'^[0-9a-f]{64}$'), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.delete(db, user.id, shelf_id, expected_revision)


@router.post('/{shelf_id}/results', response_model=SmartShelfResults)
def shelf_results(shelf_id: SmartShelfId, payload: SmartShelfPageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return service.results(db, user.id, shelf_id, payload.offset, payload.limit)
    finally:
        # Complete the primitive DTO before releasing locks. No transaction
        # waits on response serialization or any external call.
        db.rollback()
