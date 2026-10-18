"""Account-owned review, apply and undo of reading continuity copies."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.source_migration import (SourceMigrationPreviewInput, SourceMigrationApplyInput, SourceMigrationUndoInput,
    SourceMigrationTargets, SourceMigrationChapters, SourceMigrationPreview, SourceMigrationRecord, SourceMigrationPage, SourceMigrationConflict)
from app.services import source_migration_service as service
from config.database import get_db

router = APIRouter(prefix='/reader/source-migrations', tags=['private source migration'])
ERRORS = {409: {'model': SourceMigrationConflict}}


def private(response):
    response.headers.update({'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})


@router.get('/targets', response_model=SourceMigrationTargets)
def targets(response:Response, source_novel_id:int=Query(gt=0), q:str=Query('',max_length=200), offset:int=Query(0,ge=0), limit:int=Query(50,ge=1,le=100), db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    private(response)
    return service.target_list(db,user.id,source_novel_id,q,offset,limit)


@router.get('/chapters/{novel_id}', response_model=SourceMigrationChapters)
def chapters(novel_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.chapter_list(db,user.id,novel_id,offset,limit)


@router.post('/preview', response_model=SourceMigrationPreview, responses=ERRORS)
def preview(value:SourceMigrationPreviewInput,response:Response,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.preview(db,user.id,value,offset,limit)


@router.post('/apply', response_model=SourceMigrationRecord, responses=ERRORS)
def apply(value:SourceMigrationApplyInput,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.apply(db,user.id,value)


@router.get('', response_model=SourceMigrationPage)
def history(response:Response,novel_id:int|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.history(db,user.id,novel_id,offset,limit)


@router.get('/{migration_id}', response_model=SourceMigrationRecord)
def detail(migration_id:int,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.detail(db,user.id,migration_id)


@router.post('/{migration_id}/undo', response_model=SourceMigrationRecord, responses=ERRORS)
def undo(migration_id:int,value:SourceMigrationUndoInput,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.undo(db,user.id,migration_id,value)
