"""Owner-only chapter identity observations and reviewed changes."""
from app.schemas.chapter_manifest import (ManifestPreviewInput, ManifestApplyInput, ManifestUndoInput,
    ManifestReviewView, ManifestReviewPage, ManifestReviewItemPage, ManifestRemoteChoicePage, ManifestOperationResponse)
from app.schemas.chapter import ChapterContent
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_auth, Authenticated
from app.schemas.chapter_manifest import ManifestStatePage, ManifestStateItem
from app.schemas.chapter_identity import ChapterKey
from app.services import chapter_manifest_service as service

router=APIRouter(tags=['chapter identity'])


@router.get('/novel/{novel_id:int}/manifest-state',response_model=ManifestStatePage)
def state(novel_id:int,response:Response,limit:int=Query(200,ge=1,le=1000),cursor:str|None=Query(None,max_length=4096),
          expected_manifest_epoch:str|None=None,expected_manifest_revision:str|None=None,
          db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.state_page(db,auth.user.id,novel_id,session_id=auth.session.id,limit=limit,cursor=cursor,
        expected_manifest_epoch=expected_manifest_epoch,expected_manifest_revision=expected_manifest_revision)


@router.get('/key/{novel_id:int}/{chapter_key}',response_model=ManifestStateItem)
def key(novel_id:int,chapter_key:ChapterKey,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.resolve_key(db,auth.user.id,novel_id,chapter_key,auth.session.id)




@router.post('/novel/{novel_id:int}/manifest/preview',response_model=ManifestReviewView)
async def preview(novel_id:int,value:ManifestPreviewInput,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return await service.preview(db,auth.user.id,novel_id,value,session_id=auth.session.id)


@router.post('/novel/{novel_id:int}/manifest/apply',response_model=ManifestOperationResponse)
async def apply(novel_id:int,value:ManifestApplyInput,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return await service.apply(db,auth.user.id,novel_id,value,session_id=auth.session.id)


@router.get('/novel/{novel_id:int}/manifest/reviews',response_model=ManifestReviewPage)
def reviews(novel_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.review_page(db,auth.user.id,novel_id,session_id=auth.session.id,offset=offset,limit=limit)


@router.get('/novel/{novel_id:int}/manifest/reviews/{review_id:int}',response_model=ManifestReviewView)
def review(novel_id:int,review_id:int,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.review_view(db,auth.user.id,novel_id,review_id,session_id=auth.session.id)


@router.get('/novel/{novel_id:int}/manifest/reviews/{review_id:int}/items',response_model=ManifestReviewItemPage)
def items(novel_id:int,review_id:int,response:Response,kind:str='items',offset:int=Query(0,ge=0),limit:int=Query(200,ge=1,le=200),db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.review_items(db,auth.user.id,novel_id,review_id,session_id=auth.session.id,kind=kind,offset=offset,limit=limit)


@router.get('/novel/{novel_id:int}/manifest/reviews/{review_id:int}/remote',response_model=ManifestRemoteChoicePage)
def remote(novel_id:int,review_id:int,response:Response,q:str=Query('',max_length=200),ids:list[str]=Query(default=[],max_length=100),offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.remote_choices(db,auth.user.id,novel_id,review_id,session_id=auth.session.id,q=q,ids=ids,offset=offset,limit=limit)


@router.post('/novel/{novel_id:int}/manifest/reviews/{review_id:int}/undo',response_model=ManifestOperationResponse)
def undo(novel_id:int,review_id:int,value:ManifestUndoInput,response:Response,db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.undo(db,auth.user.id,novel_id,review_id,value,session_id=auth.session.id)




@router.get('/key/{novel_id:int}/{chapter_key}/content',response_model=ChapterContent)
def keyed_content(novel_id:int,chapter_key:ChapterKey,response:Response,content_version:str|None=Query(None,pattern=r'^[a-f0-9]{64}$'),db:Session=Depends(get_db),auth:Authenticated=Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    return service.keyed_content(db,auth.user.id,novel_id,chapter_key,session_id=auth.session.id,content_version=content_version)
