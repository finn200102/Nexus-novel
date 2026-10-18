"""Saved original identity and private translation metadata, without provider secrets."""
from typing import Any
from pydantic import BaseModel,ConfigDict
from app.schemas.chapter_document import ChapterDocumentResponse


class TranslationIdentityResponse(BaseModel):
    chapter_key: str | None = None
    manifest_epoch: str | None = None
    manifest_revision: str | None = None
    chapter_number: int | None = None
    chapter_title: str | None = None
    current_content_version: str | None = None
    source_chapter_key: str | None = None
    source_manifest_epoch: str | None = None
    source_manifest_revision: str | None = None
    source_identity_current: bool = False
    source_identity_inferred: bool = False
    chapter_archived: bool = False
    chapter_title_snapshot: str | None = None
    chapter_number_snapshot: int | None = None


class TranslationJobResponse(TranslationIdentityResponse):
    model_config=ConfigDict(extra='allow')
    id: int
    novel_id: int
    chapter_id: int
    language: str
    status: str
    source_version: str
    provider: dict[str,Any]
    completed_blocks: int
    total_blocks: int
    document: ChapterDocumentResponse
    input_tokens: int
    output_tokens: int
    charged_usd: float
    error: str | None


class TranslationWorkspaceItem(TranslationIdentityResponse):
    id: int
    chapter_id: int
    language: str
    status: str
    source_version: str
    current_source_version: str | None
    source_current: bool
    exportable: bool
    completed_blocks: int
    total_blocks: int
    provider: dict[str,str | None]
    error: str | None


class TranslationWorkspacePage(BaseModel):
    novel_id: int
    total: int
    offset: int
    limit: int
    items: list[TranslationWorkspaceItem]


class TranslationChapterItem(BaseModel):
    id: int
    chapter_number: int
    title: str | None
    content_status: str
    source_version: str | None
    current_content_version: str | None
    chapter_key: str
    manifest_epoch: str
    manifest_revision: str
    downloaded: bool


class TranslationChapterPage(BaseModel):
    novel_id: int
    total: int
    offset: int
    limit: int
    items: list[TranslationChapterItem]
