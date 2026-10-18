"""Explicit lifecycle decisions; observation ordinals never imply identity."""
from datetime import datetime,timezone
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,field_serializer
from .chapter_manifest import ManifestSourceNamespace as ManifestSource

Key=Annotated[str,Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')]
Hash=Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class SourceLifecycleDecision(Strict):
    capture_ordinal:int=Field(ge=0,le=199999,strict=True)
    chapter_key:Key|None=None
    new_lifecycle:bool=Field(strict=True)

class SourceManifestReviewPreviewInput(Strict):
    novel_id:int=Field(gt=0,le=2147483647,strict=True)
    capture_id:Key
    expected_manifest_key:Key
    expected_revision:Hash
    mappings:list[SourceLifecycleDecision]=Field(default_factory=list,max_length=200000)
    archive_keys:list[Key]=Field(default_factory=list,max_length=200000)

class SourceManifestReviewAction(Strict):
    expected_revision:int=Field(ge=1,le=2147483647,strict=True)
    operation_id:Key
    review_token:str|None=Field(default=None,max_length=4096)

class SourceManifestOriginal(Strict):
    chapter_key:Key
    chapter_number:int
    title:str|None
    url:str|None
    archived:bool
    has_cached_content:bool

class SourceManifestCandidate(Strict):
    chapter_key:Key
    evidence:Literal['unique_meaningful_title']

class SourceManifestObservation(Strict):
    capture_ordinal:int
    chapter_number:int
    title:str|None
    url:str|None
    category:str
    candidates:list[SourceManifestCandidate]
    decision:SourceLifecycleDecision|None=None
    new_chapter_key:Key|None=None

class SourceManifestReviewCapture(Strict):
    id:Key
    fingerprint:Hash
    total:int
    source_complete:bool
    deletion_authoritative:bool
    authority_kind:str

class SourceManifestReviewContext(Strict):
    novel_id:int
    title:str|None
    manifest_key:Key
    revision:Hash
    source:ManifestSource
    capture:SourceManifestReviewCapture
    originals:list[SourceManifestOriginal]
    observations:list[SourceManifestObservation]
    original_total:int
    observation_total:int
    offset:int
    limit:int

class SourceManifestReviewView(Strict):
    id:Key
    novel_id:int|None
    original_novel_id:int
    title:str|None
    revision:int
    status:Literal['preview','applied','undone']
    ready:bool
    review_token:str|None
    expires_at:datetime
    created_at:datetime
    applied_at:datetime|None
    undone_at:datetime|None
    manifest_key:Key
    manifest_revision:Hash
    source:ManifestSource
    capture:SourceManifestReviewCapture
    facts_fingerprint:Hash
    counts:dict[str,int]
    warnings:list[str]
    can_undo:bool
    undo_blocked_reason:str|None
    applied_capture_id:Key|None
    originals:list[SourceManifestOriginal]
    observations:list[SourceManifestObservation]
    original_total:int
    observation_total:int
    offset:int
    limit:int

    @field_serializer('expires_at','created_at','applied_at','undone_at')
    def dates(self,value):return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None

class SourceManifestReviewResult(Strict):
    review:SourceManifestReviewView
    replayed:bool

class SourceManifestReviewSummary(Strict):
    id:Key
    novel_id:int|None
    original_novel_id:int
    title:str|None
    revision:int
    status:Literal['preview','applied','undone']
    created_at:datetime
    applied_at:datetime|None
    undone_at:datetime|None

    @field_serializer('created_at','applied_at','undone_at')
    def dates(self,value):return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None

class SourceManifestReviewPage(Strict):
    items:list[SourceManifestReviewSummary]
    total:int
    offset:int
    limit:int
