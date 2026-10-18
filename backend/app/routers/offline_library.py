from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.offline_library import OfflineManifestPage, OfflineTranslationContent
from app.services import offline_library_service as service
from config.database import get_db

router = APIRouter(prefix='/reader', tags=['private offline copies'])


@router.get('/stories/{novel_id}/offline-manifest', response_model=OfflineManifestPage)
def manifest(novel_id: int, response: Response, offset: int = Query(0, ge=0, le=1_000_000), limit: int = Query(100, ge=1, le=200),
    followed_only: bool = False, downloaded_only: bool = False, from_chapter: int | None = Query(None, ge=-2_147_483_648, le=2_147_483_647),
    expected_manifest_epoch: str | None = Query(None, pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'),
    expected_manifest_revision: str | None = Query(None, pattern=r'^(0|[1-9][0-9]{0,63})$'),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return service.manifest(db, user.id, novel_id, offset, limit, followed_only=followed_only, from_chapter=from_chapter, downloaded_only=downloaded_only,
        expected_manifest_epoch=expected_manifest_epoch, expected_manifest_revision=expected_manifest_revision)


@router.get('/offline/translations/{job_id}', response_model=OfflineTranslationContent, response_model_exclude_unset=True)
def translation(job_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return service.translation_content(db, user.id, job_id)
