from datetime import datetime
from pydantic import BaseModel,Field
from app.schemas.chapter_identity import ChapterKey,ManifestRevision


class KoboVersionConfirmation(BaseModel):
    expected_fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
    expected_manifest_epoch:ChapterKey
    expected_manifest_revision:ManifestRevision
    reading_run_key:ChapterKey|None=None


class KoboBookVersion(BaseModel):
    entitlement_id:str
    novel_id:int
    title:str|None
    fingerprint:str
    generated_at:datetime|None
    chapter_count:int
    manifest_epoch:str
    manifest_revision:str
    reading_run_key:str|None
    confirmed:bool
    review_reason:str|None
    identity_known:bool


class KoboBookVersionPage(BaseModel):
    items:list[KoboBookVersion]
    total:int
    offset:int
    limit:int


class KoboVersionConfirmed(BaseModel):
    confirmed:bool
    fingerprint:str
