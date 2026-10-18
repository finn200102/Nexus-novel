from datetime import datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field


class EditionMember(BaseModel):
    edition_id:int
    novel_id:int
    title:str
    author:str|None
    description:str|None=None
    source_url:str
    site:str|None
    language:str|None
    edition_kind:str
    created_at:str|None=None
    updated_at:str|None=None
    content_rating:str
    tags:list[str]
    genres:list[str]
    fandoms:list[str]


class EditionGroupResponse(BaseModel):
    group_key:str
    canonical_work_id:int
    revision:int
    title:str
    reviewed:bool
    edition_count:int
    editions:list[EditionMember]


class EditionReviewPreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_novel_id:int=Field(gt=0,le=2147483647,strict=True)
    target_novel_id:int=Field(gt=0,le=2147483647,strict=True)
    actor:str=Field(min_length=1,max_length=120)


class EditionReviewAction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=1,strict=True)
    operation_id:str=Field(min_length=1,max_length=120)
    actor:str=Field(min_length=1,max_length=120)


class EditionReviewView(BaseModel):
    id:str
    revision:int
    status:Literal['preview','applied','undone']
    source_group:EditionGroupResponse
    target_group:EditionGroupResponse
    facts_fingerprint:str
    expires_at:datetime
    created_at:datetime
    applied_at:datetime|None
    undone_at:datetime|None
    warnings:list[str]
    can_undo:bool
    undo_blocked_reason:str|None
    result_group:EditionGroupResponse|None


class EditionReviewResult(BaseModel):
    review:EditionReviewView
    replayed:bool


class EditionReviewSummary(BaseModel):
    id:str
    revision:int
    status:Literal['preview','applied','undone']
    source_group_key:str
    target_group_key:str
    source_title:str
    target_title:str
    created_at:datetime
    applied_at:datetime|None
    undone_at:datetime|None


class EditionReviewPage(BaseModel):
    items:list[EditionReviewSummary]
    total:int
    offset:int
    limit:int
