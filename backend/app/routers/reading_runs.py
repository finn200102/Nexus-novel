from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.reading_runs import ReadingRunAction, ReadingRunDrop,ReadingRunStateResponse,ReadingJournalPageResponse
from app.services import reading_run_service as service
from config.database import get_db
router=APIRouter(prefix='/reading',tags=['private reading journal'])


def private(response):response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/stories/{novel_id}/runs',response_model=ReadingRunStateResponse,response_model_exclude_unset=True)
def runs(novel_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.state(db,user.id,novel_id,offset,limit)


@router.post('/stories/{novel_id}/runs/start',response_model=ReadingRunStateResponse,response_model_exclude_unset=True)
def start(novel_id:int,value:ReadingRunAction,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.action(db,user.id,novel_id,value,'start')


@router.post('/stories/{novel_id}/runs/finish',response_model=ReadingRunStateResponse,response_model_exclude_unset=True)
def finish(novel_id:int,value:ReadingRunAction,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.action(db,user.id,novel_id,value,'finish')


@router.post('/stories/{novel_id}/runs/drop',response_model=ReadingRunStateResponse,response_model_exclude_unset=True)
def drop(novel_id:int,value:ReadingRunDrop,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.action(db,user.id,novel_id,value,'drop')


@router.get('/journal',response_model=ReadingJournalPageResponse,response_model_exclude_unset=True)
def journal(response:Response,novel_id:int|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.journal(db,user.id,novel_id,offset,limit)
