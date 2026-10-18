"""Authenticated review proxy; audit actors always come from the account."""
from uuid import UUID
from dataclasses import dataclass
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from config.database import get_db
from app.auth.dependencies import get_current_auth, Authenticated
from app.models.user import User
from app.models.account import UserSession
from app.routers.admin_integrations import metadata_admin
from app.schemas.reviewed_vocabulary import (
    Kind, State, TermCreate, TermView, TermPage, AliasCreate, AliasView, AliasPage,
    PreviewInput, PreviewView, RawPage, StoryScopePage,
)
from app.schemas.reviewed_edition_review import EditionReviewView, EditionReviewResult, EditionReviewPage

router = APIRouter(prefix='/admin', tags=['catalog reviews'])


@dataclass
class ReviewAdministrator:
    user_id: int
    storage_id: str
    session_id: int
    db: Session


def review_admin(db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    if not auth.user.is_admin:
        raise HTTPException(403, detail='Administrator access required')
    result=ReviewAdministrator(auth.user.id,auth.user.storage_id,auth.session.id,db)
    db.commit()
    return result


def reauthorize(admin):
    db=admin.db
    db.expire_all()
    user=db.get(User,admin.user_id)
    session=db.get(UserSession,admin.session_id)
    valid=bool(user and not user.is_disabled and user.is_admin and user.storage_id==admin.storage_id
        and session and session.user_id==admin.user_id and session.revoked_at is None)
    db.commit()
    if not valid:
        raise HTTPException(403, detail='Administrator access changed. Sign in again.')


async def admin_request(admin, method, path, payload=None, params=None):
    result=await metadata_admin(method,path,payload,params)
    await run_in_threadpool(reauthorize,admin)
    return result


class AliasDecisionInput(PreviewInput):
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    operation_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')
    review_token: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(None, max_length=2000)


class EditionPreviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_novel_id: int = Field(gt=0, le=2147483647, strict=True)
    target_novel_id: int = Field(gt=0, le=2147483647, strict=True)


class EditionActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1, strict=True)
    operation_id: str = Field(min_length=1, max_length=120)


class ReviewLookupItem(BaseModel):
    novel_id: int
    story_key: str
    title: str
    author: str | None
    site: str | None
    source_url: str


class ReviewLookupPage(BaseModel):
    items: list[ReviewLookupItem]
    total: int
    offset: int
    limit: int
    has_more: bool


@router.get('/review-catalog/lookup', response_model=ReviewLookupPage)
async def lookup(q: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                 limit: int = Query(20, ge=1, le=100), user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET','/review-catalog/lookup', params={'q':q,'offset':offset,'limit':limit})


@router.get('/vocabulary/terms', response_model=TermPage)
async def terms(kind: Kind | None = None, q: str | None = Query(None,max_length=200),
    fandom_term_id: UUID | None = None, story_key: UUID | None = None,
    ids: list[UUID] | None = Query(None,max_length=100), offset: int = Query(0,ge=0,le=1000000),
    limit: int = Query(50,ge=1,le=100), user: ReviewAdministrator = Depends(review_admin)):
    params={'kind':kind,'q':q,'fandom_term_id':str(fandom_term_id) if fandom_term_id else None,
        'story_key':str(story_key) if story_key else None,'ids':[str(i) for i in ids] if ids else None,'offset':offset,'limit':limit}
    return await admin_request(user,'GET','/vocabulary/terms',params={k:v for k,v in params.items() if v is not None})


@router.post('/vocabulary/terms', response_model=TermView)
async def create_term(value: TermCreate, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST','/vocabulary/terms',value.model_dump(mode='json'))


@router.get('/vocabulary/raw', response_model=RawPage)
async def raw(kind: Kind, q: str | None = Query(None,max_length=200), site: str | None = Query(None,max_length=80),
    offset: int = Query(0,ge=0,le=1000000), limit: int = Query(50,ge=1,le=100), user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET','/vocabulary/raw',params={k:v for k,v in dict(kind=kind,q=q,site=site,offset=offset,limit=limit).items() if v is not None})


@router.get('/vocabulary/story-scopes', response_model=StoryScopePage)
async def scopes(q: str | None = Query(None,max_length=200), offset: int = Query(0,ge=0,le=1000000),
    limit: int = Query(50,ge=1,le=100), user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET','/vocabulary/story-scopes',params={k:v for k,v in dict(q=q,offset=offset,limit=limit).items() if v is not None})


@router.get('/vocabulary/aliases', response_model=AliasPage)
async def aliases(state: State | None = None, kind: Kind | None = None, term_id: UUID | None = None,
    offset: int = Query(0,ge=0,le=1000000), limit: int = Query(50,ge=1,le=100), user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET','/vocabulary/aliases',params={k:v for k,v in dict(state=state,kind=kind,term_id=str(term_id) if term_id else None,offset=offset,limit=limit).items() if v is not None})


@router.post('/vocabulary/aliases', response_model=AliasView)
async def create_alias(value: AliasCreate, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST','/vocabulary/aliases',value.model_dump(mode='json'))


@router.get('/vocabulary/aliases/{alias_id}', response_model=AliasView)
async def alias(alias_id: UUID, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET',f'/vocabulary/aliases/{alias_id}')


@router.post('/vocabulary/aliases/{alias_id}/preview', response_model=PreviewView)
async def preview_alias(alias_id: UUID, value: PreviewInput, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST',f'/vocabulary/aliases/{alias_id}/preview',value.model_dump(mode='json'))


@router.post('/vocabulary/aliases/{alias_id}/decide', response_model=AliasView)
async def decide_alias(alias_id: UUID, value: AliasDecisionInput, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST',f'/vocabulary/aliases/{alias_id}/decide',{**value.model_dump(mode='json'),'actor':user.storage_id})


@router.get('/edition-group-reviews', response_model=EditionReviewPage)
async def editions(offset: int = Query(0,ge=0), limit: int = Query(25,ge=1,le=100), user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET','/edition-group-reviews',params={'offset':offset,'limit':limit})


@router.post('/edition-group-reviews/preview', response_model=EditionReviewView)
async def preview_editions(value: EditionPreviewInput, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST','/edition-group-reviews/preview',{**value.model_dump(),'actor':user.storage_id})


@router.get('/edition-group-reviews/{review_id}', response_model=EditionReviewView)
async def edition(review_id: UUID, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'GET',f'/edition-group-reviews/{review_id}')


@router.post('/edition-group-reviews/{review_id}/apply', response_model=EditionReviewResult)
async def apply_editions(review_id: UUID, value: EditionActionInput, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST',f'/edition-group-reviews/{review_id}/apply',{**value.model_dump(),'actor':user.storage_id})


@router.post('/edition-group-reviews/{review_id}/undo', response_model=EditionReviewResult)
async def undo_editions(review_id: UUID, value: EditionActionInput, user: ReviewAdministrator = Depends(review_admin)):
    return await admin_request(user,'POST',f'/edition-group-reviews/{review_id}/undo',{**value.model_dump(),'actor':user.storage_id})
