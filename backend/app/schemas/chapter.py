from pydantic import BaseModel, ConfigDict
from enum import Enum
from typing import Optional
from datetime import datetime


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
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    content_status: ContentStatus = ContentStatus.MISSING


class Chapter(BaseModel):
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


class ChapterContent(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    content: str
    source_url: Optional[str] = None


class ChapterUpdate(BaseModel):
    id: int
    novel_id: int
    title: Optional[str] = None
    content_status: ContentStatus


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


class ReadingProgressUpdate(BaseModel):
    chapter_number: int
    position: int = 0
    percent: float = 0


class ReadingProgressResponse(BaseModel):
    novel_id: int
    chapter_number: Optional[int] = None
    position: int
    percent: float
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReadingAnnotationCreate(BaseModel):
    chapter_number: int
    annotation_type: str = "bookmark"
    position: int = 0
    percent: float = 0
    quote: Optional[str] = None
    note: Optional[str] = None


class ReadingAnnotationResponse(BaseModel):
    id: int
    novel_id: int
    chapter_id: int
    chapter_number: int
    annotation_type: str
    position: int
    percent: float
    quote: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
