from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from enum import Enum
from typing import Optional
from datetime import datetime
from .chapter_document import ChapterDocumentResponse
from .chapter_identity import ChapterWriteIdentity, ChapterIdentityResponse, ChapterKey, ManifestRevision


class ContentStatus(str, Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


class AudioStatus(str, Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


class ChapterCreate(BaseModel):
    expected_manifest_epoch: ChapterKey | None = None
    expected_manifest_revision: ManifestRevision | None = None
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    content_status: ContentStatus = ContentStatus.MISSING


class Chapter(ChapterIdentityResponse):
    id: int
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    content_status: ContentStatus
    audio_status: AudioStatus
    site_chapter_id: Optional[int] = None
    source_url: Optional[str] = None
    word_count: Optional[int] = None
    download_started_at: Optional[datetime] = None
    download_finished_at: Optional[datetime] = None
    download_error: Optional[str] = None
    retry_count: int = 0
    category: str = "story"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChapterContent(ChapterIdentityResponse):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    content: str
    source_url: Optional[str] = None
    document: Optional[ChapterDocumentResponse] = None
    source_version: str
    current_content_version: str
    archived: bool = False


class ChapterUpdate(ChapterWriteIdentity):
    id: int
    novel_id: int
    title: Optional[str] = None
    content_status: ContentStatus


class ChapterVersionSummary(BaseModel):
    content_version: str
    title: Optional[str] = None
    saved_at: Optional[datetime] = None
    byte_count: int
    current: bool
    reason: str


class ChapterVersionsPage(ChapterIdentityResponse):
    current_version: str
    versions: list[ChapterVersionSummary]
    next_cursor: Optional[int] = None


class ChapterDownloadQueueRequest(BaseModel):
    count: int = 1


class ChapterDownloadJob(BaseModel):
    id: int
    novel_id: int
    chapter_id: int
    status: str
    attempt_count: int
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TextQuoteFields(BaseModel):
    text_quote: Optional[str] = Field(None, max_length=240)
    quote_prefix: Optional[str] = Field(None, max_length=80)
    quote_suffix: Optional[str] = Field(None, max_length=80)
    locator_variant: Optional[str] = Field(None, max_length=128, pattern=r"^(original|(?:translation|parallel):[1-9][0-9]*)$")


class SavedLocatorFields(TextQuoteFields):
    locator_content_version: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")


class ReadingProgressUpdate(TextQuoteFields, ChapterWriteIdentity):
    reading_run_key: Optional[str] = Field(None, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    content_version: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")
    chapter_number: int
    position: int = 0
    percent: float = 0
    expected_revision: Optional[int] = Field(None, ge=0)
    operation_id: Optional[str] = Field(None, min_length=1, max_length=128)
    device_id: Optional[str] = Field(None, min_length=1, max_length=128)
    block_id: Optional[str] = Field(None, max_length=128)
    text_offset: int = Field(0, ge=0, le=16_000_000)
    intent: Literal["automatic", "rewind", "reconcile", "confirm_read"] = "automatic"


class ReadingProgressResponse(SavedLocatorFields):
    chapter_key: ChapterKey | None = None
    current_identity_inferred: bool = False
    source_content_version: str | None = None
    furthest_content_version: str | None = None
    furthest_chapter_key: ChapterKey | None = None
    furthest_identity_inferred: bool = False
    manifest_epoch: ChapterKey | None = None
    manifest_revision: ManifestRevision | None = None
    reading_run_key: Optional[str] = None
    novel_id: int
    chapter_number: Optional[int] = None
    position: int
    percent: float
    updated_at: datetime
    revision: int = 0
    furthest_chapter_number: int = 0
    furthest_percent: float = 0
    block_id: Optional[str] = None
    text_offset: int = 0

    model_config = ConfigDict(from_attributes=True)


class ReadingAnnotationCreate(SavedLocatorFields, ChapterWriteIdentity):
    chapter_number: int
    annotation_type: str = "bookmark"
    position: int = 0
    percent: float = 0
    quote: Optional[str] = None
    note: Optional[str] = None
    block_id: Optional[str] = Field(None, max_length=128)
    text_offset: int = Field(0, ge=0, le=16_000_000)


class ReadingAnnotationUpdate(ChapterWriteIdentity):
    note: str | None = Field(..., max_length=20000)

    model_config = ConfigDict(extra="forbid")


class ReadingAnnotationResponse(SavedLocatorFields, ChapterIdentityResponse):
    chapter_key: ChapterKey | None = None
    original_chapter_number: int | None = None
    archived: bool = False
    identity_unresolved: bool = False
    block_id: Optional[str] = None
    text_offset: int = 0
    id: int
    novel_id: int
    chapter_id: int
    chapter_number: int | None = None
    annotation_type: str
    position: int
    percent: float
    quote: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecentReadingProgressResponse(BaseModel):
    novel_id: int
    novel_title: str
    library_id: int
    chapter_number: int | None
    position: int
    percent: float
    updated_at: datetime


class ReadingHistoryEventResponse(BaseModel):
    chapter_key: ChapterKey | None = None
    identity_inferred: bool = False
    chapter_number: int
    date: str
    percent: int


class ReadingHistoryResponse(BaseModel):
    chapters_touched: int
    active_days: int
    current_streak_days: int
    events: list[ReadingHistoryEventResponse]


class RecapChapterResponse(BaseModel):
    number: int
    title: str | None


class RecapAnnotationResponse(BaseModel):
    chapter_number: int
    quote: str | None
    note: str | None
    type: str


class ChapterRecapResponse(BaseModel):
    spoiler_boundary_chapter: int | None
    summary: str
    chapters: list[RecapChapterResponse]
    annotations: list[RecapAnnotationResponse]


class ProcessingChapterDownloadResponse(BaseModel):
    id: int
    chapter_number: int
    title: str | None
    started_at: str | None
    retry_count: int


class FailedChapterDownloadResponse(BaseModel):
    id: int
    chapter_number: int
    title: str | None
    error: str | None
    retry_count: int
    finished_at: str | None


class NovelDownloadStatusResponse(BaseModel):
    total: int
    present: int
    missing: int
    processing: int
    failed: int
    chapters: list[Chapter] | None = None
    processing_chapters: list[ProcessingChapterDownloadResponse]
    failed_chapters: list[FailedChapterDownloadResponse]


class ChapterDownloadCancelledResponse(BaseModel):
    message: str
    chapter_id: int


class ChapterDownloadsCancelledResponse(BaseModel):
    message: str
    cancelled: int


class ChapterNavigationEntry(ChapterIdentityResponse):
    id: int
    chapter_number: int
    title: str | None


class ChapterNavigationResponse(ChapterIdentityResponse):
    novel_id: int
    chapter_id: int
    chapter_number: int
    previous: ChapterNavigationEntry | None
    next: ChapterNavigationEntry | None
