from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.reader_provider_usage import (
    ReaderProviderRequestsPage, ReaderProviderReconcileInput, ReaderProviderReconcileResponse,
    ReaderProviderUsageConflictResponse,
)
from app.services import reader_provider_usage as usage

router = APIRouter(prefix='/reader/providers', tags=['reader provider accounting'])


@router.get('/{provider_id}/requests', response_model=ReaderProviderRequestsPage)
def requests(provider_id: int, response: Response, offset: int = Query(0, ge=0, le=1_000_000),
    limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return usage.listing(db, user.id, provider_id, offset, limit)


@router.post('/{provider_id}/requests/{request_key}/reconcile', response_model=ReaderProviderReconcileResponse,
    responses={409: {'model': ReaderProviderUsageConflictResponse}})
def reconcile(provider_id: int, request_key: str, value: ReaderProviderReconcileInput,
    response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return usage.reconcile(db, user.id, provider_id, request_key, value)
