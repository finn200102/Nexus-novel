"""Account-authorized source lifecycle reviews with server-owned audit actors."""
from typing import Literal
from fastapi import APIRouter,Depends,Query,Response,HTTPException
from pydantic import BaseModel
from app.routers.catalog_reviews import ReviewAdministrator,review_admin,admin_request,reauthorize
from app.schemas.source_manifest_review import (Key,Hash,SourceManifestReviewContext,SourceManifestReviewPreviewInput,
    SourceManifestReviewAction,SourceManifestReviewView,SourceManifestReviewResult,SourceManifestReviewPage,
    SourceManifestReviewCapture,ManifestSource)
from app.services import metadata_client
from starlette.concurrency import run_in_threadpool


def private(response:Response):response.headers['Cache-Control']='private, no-store'


router=APIRouter(prefix='/admin/source-manifest-reviews',tags=['source lifecycle reviews'],dependencies=[Depends(private)])


class SourceManifestCaptureSummary(SourceManifestReviewCapture):
    captured_at:str
    authority_kind:Literal['adapter_stable','raw_observation','reviewed_mapping']
    review_id:Key|None


class SourceManifestHead(BaseModel):
    protocol:Literal[1]
    novel_id:int
    manifest_key:Key
    revision:Hash
    source:ManifestSource
    capture:SourceManifestCaptureSummary|None


@router.get('/novels/{novel_id}/head',response_model=SourceManifestHead)
async def head(novel_id:int,user:ReviewAdministrator=Depends(review_admin)):
    if not 0<novel_id<2**31:raise HTTPException(422,'Invalid catalog story identity')
    try:
        result=await metadata_client._manifest_request(f'/chapters/novel/{novel_id}/source-manifest-head')
    except metadata_client.ChapterManifestError as exc:
        await run_in_threadpool(reauthorize,user)
        raise HTTPException(409 if exc.retryable else 503,detail={'code':exc.category,'message':str(exc)}) from exc
    await run_in_threadpool(reauthorize,user)
    return result


@router.get('/novels/{novel_id}/context',response_model=SourceManifestReviewContext)
async def context(novel_id:int,capture_id:Key,offset:int=Query(0,ge=0,le=200000),limit:int=Query(100,ge=1,le=1000),
    expected_manifest_key:Key|None=None,expected_revision:Hash|None=None,user:ReviewAdministrator=Depends(review_admin)):
    if not 0<novel_id<2**31:raise HTTPException(422,'Invalid catalog story identity')
    params=dict(capture_id=capture_id,offset=offset,limit=limit,
        expected_manifest_key=expected_manifest_key,expected_revision=expected_revision)
    return await admin_request(user,'GET',f'/source-manifest-reviews/novels/{novel_id}/context',
        params={key:value for key,value in params.items() if value is not None})


@router.post('/preview',response_model=SourceManifestReviewView)
async def preview(value:SourceManifestReviewPreviewInput,offset:int=Query(0,ge=0,le=200000),limit:int=Query(100,ge=1,le=1000),
    user:ReviewAdministrator=Depends(review_admin)):
    return await admin_request(user,'POST','/source-manifest-reviews/preview',
        {**value.model_dump(mode='json'),'actor_id':user.storage_id},params={'offset':offset,'limit':limit})


@router.get('',response_model=SourceManifestReviewPage)
async def history(novel_id:int|None=Query(None,gt=0,le=2147483647),offset:int=Query(0,ge=0,le=2147483647),
    limit:int=Query(25,ge=1,le=100),user:ReviewAdministrator=Depends(review_admin)):
    params=dict(novel_id=novel_id,offset=offset,limit=limit)
    return await admin_request(user,'GET','/source-manifest-reviews',params={k:v for k,v in params.items() if v is not None})


@router.get('/{review_id}',response_model=SourceManifestReviewView)
async def detail(review_id:Key,offset:int=Query(0,ge=0,le=200000),limit:int=Query(100,ge=1,le=1000),
    user:ReviewAdministrator=Depends(review_admin)):
    return await admin_request(user,'GET',f'/source-manifest-reviews/{review_id}',params={'offset':offset,'limit':limit})


@router.post('/{review_id}/apply',response_model=SourceManifestReviewResult)
async def apply(review_id:Key,value:SourceManifestReviewAction,user:ReviewAdministrator=Depends(review_admin)):
    return await admin_request(user,'POST',f'/source-manifest-reviews/{review_id}/apply',
        {**value.model_dump(mode='json'),'actor_id':user.storage_id})


@router.post('/{review_id}/undo',response_model=SourceManifestReviewResult)
async def undo(review_id:Key,value:SourceManifestReviewAction,user:ReviewAdministrator=Depends(review_admin)):
    return await admin_request(user,'POST',f'/source-manifest-reviews/{review_id}/undo',
        {**value.model_dump(mode='json'),'actor_id':user.storage_id})
