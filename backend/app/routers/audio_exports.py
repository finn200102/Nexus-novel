"""Account-owned M4B exports and scoped streaming downloads."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.auth.dependencies import Authenticated, get_current_auth, get_current_user
from app.auth.jwt import SECRET_KEY, ALGORITHM
from app.auth.sessions import _cookie_secure, REFRESH_COOKIE, session_for_refresh_token
from app.models.account import UserSession
from app.models.audio_export import AudioExportJob
from app.models.user import User
from app.schemas.audio_export import AudioExportCreate, AudioExportResponse
from app.services.audio_export_service import ACTIVE, ExportError, delete_export, queue_export, ready_path
from app.services.podcast_service import public_api_base
from config.database import get_db

router = APIRouter(prefix='/audio/exports', tags=['audio exports'])
COOKIE_NAME = 'nexus_audio_export'


def owned(db, user_id, job_id):
    job = db.query(AudioExportJob).filter_by(id=job_id,user_id=user_id).first()
    if job is None:
        raise HTTPException(404, 'Audio export not found')
    return job


def view(job):
    return AudioExportResponse.model_validate({
        **{name:getattr(job,name) for name in AudioExportResponse.model_fields if hasattr(job,name)},
        'file_ready': ready_path(job) is not None})


@router.post('', response_model=AudioExportResponse, status_code=202)
def create(request:AudioExportCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    try:
        return view(queue_export(db,user_id=user.id,novel_id=request.novel_id,audio_job_ids=request.audio_job_ids))
    except ExportError as exc:
        raise HTTPException(404 if exc.code=='not_found' else 409,str(exc)) from None


@router.get('',response_model=list[AudioExportResponse])
def listing(novel_id:int|None=Query(None,gt=0),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),
            db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    query=db.query(AudioExportJob).filter_by(user_id=user.id)
    if novel_id is not None:
        query=query.filter_by(novel_id=novel_id)
    return [view(job) for job in query.order_by(AudioExportJob.created_at.desc(),AudioExportJob.id.desc()).offset(offset).limit(limit).all()]


@router.get('/{job_id}',response_model=AudioExportResponse)
def status(job_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return view(owned(db,user.id,job_id))


@router.post('/{job_id}/cancel',response_model=AudioExportResponse)
def cancel(job_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    job=owned(db,user.id,job_id)
    if job.status not in ACTIVE:
        raise HTTPException(409,'This export is not active')
    job.status='cancelled';job.lease_owner=None;job.lease_expires_at=None
    job.finished_at=datetime.now(UTC).replace(tzinfo=None)
    db.commit();db.refresh(job);return view(job)


@router.post('/{job_id}/retry',response_model=AudioExportResponse)
def retry(job_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    job=owned(db,user.id,job_id)
    if job.status not in ('failed','cancelled','retry_wait') and not (job.status=='completed' and ready_path(job) is None):
        raise HTTPException(409,'Only interrupted exports or missing files can be retried')
    job.status='queued';job.error=None;job.error_code=None;job.finished_at=None;job.next_attempt_at=None
    job.lease_owner=None;job.lease_expires_at=None;job.attempt_count=0;job.completed_chapters=0
    db.commit();db.refresh(job);return view(job)


@router.delete('/{job_id}',status_code=204)
def delete(job_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    try:
        delete_export(db,owned(db,user.id,job_id))
    except ExportError as exc:
        raise HTTPException(409,str(exc)) from None


@router.post('/{job_id}/download')
def download_ticket(job_id:int,request:Request,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    job=owned(db,auth.user.id,job_id)
    if ready_path(job) is None:
        raise HTTPException(404,'The M4B file is not ready')
    if auth.session is None:
        raise HTTPException(409,'Sign in with a browser session to request a streaming download')
    token=jwt.encode({'type':'audio_export_download','sub':str(auth.user.id),'sid':str(auth.session.id),
        'export_id':job.id,'exp':datetime.now(UTC)+timedelta(minutes=5)},SECRET_KEY,algorithm=ALGORITHM)
    public = urlsplit(public_api_base(request))
    url=f'{public.path.rstrip("/")}/audio/exports/{job.id}/file'
    response.set_cookie(COOKIE_NAME,token,max_age=300,httponly=True,samesite='strict',
        secure=_cookie_secure(request) or public.scheme == 'https',path=url)
    response.headers['Cache-Control']='no-store'
    return {'url':url,'expires_in':300}


@router.get('/{job_id}/file')
def file(job_id:int,request:Request,db:Session=Depends(get_db)):
    scheme,token=get_authorization_scheme_param(request.headers.get('authorization'))
    if scheme.lower()=='bearer' and token:
        user=get_current_auth(token=token,db=db).user
    else:
        try:
            data=jwt.decode(request.cookies.get(COOKIE_NAME,''),SECRET_KEY,algorithms=[ALGORITHM])
            if data.get('type')!='audio_export_download' or data.get('export_id')!=job_id:
                raise ValueError()
            session=db.get(UserSession,int(data['sid']))
            user=db.get(User,int(data['sub']))
            if session is None or session.revoked_at is not None or user is None or user.is_disabled or session.user_id!=user.id:
                raise ValueError()
            # Switching browser accounts also invalidates the old ticket, even
            # when the old account's session remains active on another device.
            if request.cookies.get(REFRESH_COOKIE):
                current=session_for_refresh_token(db,request.cookies[REFRESH_COOKIE])
                if current is None or current.id!=session.id:
                    raise ValueError()
        except (JWTError,ValueError,TypeError,KeyError):
            raise HTTPException(401,'Sign in and request this export download again') from None
    job=owned(db,user.id,job_id)
    path=ready_path(job)
    if path is None:
        raise HTTPException(404,'The M4B file is not ready')
    return FileResponse(path,media_type='audio/mp4',filename=f'story-{job.novel_id}.m4b',
        headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
