"""Private saved-query shelves and explicitly activated catalog alerts."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.auth.dependencies import get_current_user
from app.models.user import User
from config.database import get_db
from app.schemas.catalog_watch import (PrepareWatch, ActivateWatch, PauseWatch, WatchPageInput,
    WatchState, CatalogResultPage, CatalogMatchPage, ReadMatch, MatchReadResult)
from app.services import catalog_watch_service as service, catalog_query_client as catalog


def private(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'

router = APIRouter(prefix='/catalog-watches', tags=['catalog watches'], dependencies=[Depends(private)])

@router.get('/{search_id}', response_model=WatchState)
def get_state(search_id:int, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    return service.state(db,user.id,search_id)

@router.post('/{search_id}/prepare', response_model=WatchState)
async def prepare(search_id:int, payload:PrepareWatch, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    user_id=user.id
    snap=await run_in_threadpool(service.snapshot,db,user_id,search_id,payload.expected_revision)
    remote=await catalog.request('prepare',{'definition':snap['definition'],'visibility':snap['visibility'],'mode':payload.mode})
    return await run_in_threadpool(service.save_prepared,db,user_id,search_id,snap['proof'],payload.mode,remote)

@router.post('/{search_id}/activate', response_model=WatchState)
async def activate(search_id:int, payload:ActivateWatch, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    user_id=user.id
    snap=await run_in_threadpool(service.snapshot,db,user_id,search_id,payload.expected_revision,need_watch=True)
    if snap['prepared_revision']!=payload.prepared_revision:
        service.fail('catalog_watch_changed','The prepared query changed. Review its current preview.')
    remote=await catalog.request('baseline',{'prepared':snap['prepared'],'limit':500})
    return await run_in_threadpool(service.activate,db,user_id,search_id,snap['proof'],payload.prepared_revision,remote)

@router.post('/{search_id}/pause', response_model=WatchState)
def pause(search_id:int, payload:PauseWatch, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    return service.pause(db,user.id,search_id,payload.expected_revision,payload.watch_revision)

@router.post('/{search_id}/results', response_model=CatalogResultPage)
async def results(search_id:int, payload:WatchPageInput, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    user_id=user.id
    snap=await run_in_threadpool(service.snapshot,db,user_id,search_id,need_watch=True)
    remote=await catalog.request('results',{'prepared':snap['prepared'],'offset':payload.offset,'limit':payload.limit})
    return await run_in_threadpool(service.result_page,db,user_id,search_id,snap['proof'],remote,payload.offset,payload.limit)

@router.get('/{search_id}/matches', response_model=CatalogMatchPage)
def matches(search_id:int, offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100), db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    return service.matches(db,user.id,search_id,offset,limit)

@router.post('/{search_id}/matches/{match_id}/read', response_model=MatchReadResult)
def read_match(search_id:int, match_id:int,payload:ReadMatch,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return service.read_match(db,user.id,search_id,match_id,payload.watch_revision)
