"""Explicit per-reference review of private imported reading material."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field
from app.schemas.user_data import ExportChapterReference


class ImportReadingMapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ref: str=Field(min_length=1,max_length=128)
    chapter_key: UUID
    confirm_changed_content: bool=False
    restore_archived_content: bool=False


class ImportReadingPreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int=Field(ge=1)
    keep_existing_place: bool=False
    mappings: list[ImportReadingMapping]=Field(max_length=1000)


class ImportReadingApplyInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    review_token: str=Field(min_length=1,max_length=128)
    operation_id: str=Field(min_length=1,max_length=128)


class ImportReadingCandidate(BaseModel):
    chapter_key: str
    chapter_number: int
    title: str | None
    source_version: str
    archived: bool
    evidence: list[str]


class ImportReadingReferenceView(BaseModel):
    reference: ExportChapterReference
    applied: bool
    candidates: list[ImportReadingCandidate]
    candidates_truncated: bool
    archived_body_available: bool=False
    retained_originals: int=0
    backup_placeholder_key: UUID|None=None


class ImportReadingReviewView(BaseModel):
    id: int
    novel_id: int
    novel_title: str | None = None
    library_name: str | None = None
    revision: int
    total: int
    applied: int
    offset: int
    limit: int
    items: list[ImportReadingReferenceView]
    warnings: list[str]


class ImportReadingReviewPage(BaseModel):
    items: list[ImportReadingReviewView]
    total: int
    offset: int
    limit: int


class ImportReadingPreview(BaseModel):
    review_id: int
    review_token: str
    expires_at: str
    manifest_epoch: str
    manifest_revision: str
    selected: int
    warnings: list[str]


class ImportReadingApplied(BaseModel):
    id: int
    revision: int
    applied: int
    remaining: int
    progress: Literal['applied','kept_local','not_selected']


class ImportReadingChapterPage(BaseModel):
    items: list[ImportReadingCandidate]
    total: int
    offset: int
    limit: int
