"""Account-private guide access. Synchronous DB work runs off the event loop."""
from fastapi import APIRouter, Depends, Query, Response, HTTPException, Header
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_auth
from app.models import User
from app.models.account import UserSession
from app.schemas.reader_guide import GuideInput, GuideCreate, GuideAction, GuideRetry, GuidePreview, GuideJob, GuideArtifact, GuideState
from app.services import reader_guide_service as service

router = APIRouter(prefix='/reader/stories/{novel_id}/guide', tags=['private guide'])


def current_user(auth=Depends(get_current_auth), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=auth.user.id).with_for_update().populate_existing().first()
    session = db.query(UserSession).filter_by(id=auth.session.id, user_id=auth.user.id).populate_existing().first()
    if user is None or user.is_disabled or session is None or session.revoked_at is not None:
        raise HTTPException(401, 'Session ended; sign in again')
    return user


def private(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


@router.get('', response_model=GuideState)
def state(novel_id: int, response: Response, offset: int = Query(0, ge=0, le=2147483647), limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.state(db, user.id, novel_id, offset, limit)


@router.post('/preview', response_model=GuidePreview)
def preview(novel_id: int, value: GuideInput, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.preview(db, user.id, novel_id, value)


@router.post('/jobs', response_model=GuideJob)
def create(novel_id: int, value: GuideCreate, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.queue(db, user.id, novel_id, value)


@router.get('/jobs/{job_id}', response_model=GuideJob)
def job(novel_id: int, job_id: int, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.job_view(db, service.owned_job(db, user.id, novel_id, job_id))


@router.post('/jobs/{job_id}/cancel', response_model=GuideJob)
def cancel(novel_id: int, job_id: int, value: GuideAction, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.action(db, user.id, novel_id, job_id, value, 'cancel')


@router.post('/jobs/{job_id}/retry', response_model=GuideJob)
def retry(novel_id: int, job_id: int, value: GuideRetry, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    return service.action(db, user.id, novel_id, job_id, value, 'retry')


@router.get('/artifacts/{artifact_id}', response_model=GuideArtifact)
def artifact(novel_id: int, artifact_id: int, response: Response, db: Session = Depends(get_db), user=Depends(current_user)):
    private(response)
    cache = {}
    row = service.visible_artifact(db, user.id, novel_id, artifact_id, read_cache=cache)
    return service.artifact_view(db, row, read_cache=cache)


@router.get('/artifacts/{artifact_id}/media')
def media(novel_id: int, artifact_id: int, range_header: str | None = Header(None, alias='Range'), db: Session = Depends(get_db), user=Depends(current_user)):
    artifact = service.visible_artifact(db, user.id, novel_id, artifact_id)
    if not artifact.media_data:
        raise HTTPException(404, 'Private portrait not found')
    body = artifact.media_data
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Accept-Ranges': 'bytes'}
    status = 200
    if range_header:
        import re
        match = re.fullmatch(r'bytes=(\d{0,12})-(\d{0,12})', range_header)
        if not match or not any(match.groups()):
            raise HTTPException(416, 'Unsupported image range', headers={'Content-Range': f'bytes */{len(body)}'})
        first, last = match.groups()
        start = int(first) if first else max(0, len(body)-int(last))
        end = min(int(last), len(body)-1) if first and last else len(body)-1
        if start >= len(body) or start > end:
            raise HTTPException(416, 'Image range unavailable', headers={'Content-Range': f'bytes */{len(body)}'})
        headers['Content-Range'] = f'bytes {start}-{end}/{len(body)}'
        body, status = body[start:end+1], 206
    return Response(content=body, media_type=artifact.media_type, status_code=status, headers=headers)
