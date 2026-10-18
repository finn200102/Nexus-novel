"""Bounded private reading summaries and pages of recorded checkpoints."""
from typing import Literal
from pydantic import BaseModel
from app.schemas.chapter import Chapter


class ChapterReadingCurrentResponse(BaseModel):
    chapter_id: int | None
    chapter_number: int
    ordinal: int | None
    followed_ordinal: int | None
    percent: float


class ChapterReadingSummaryResponse(BaseModel):
    novel_id: int
    reading_run_key: str | None
    revision: int
    total_chapters: int
    categories: list[str]
    categories_truncated: bool
    followed_total: int
    completed_chapters: int
    followed_completed_chapters: int
    completion_basis: Literal['recorded_checkpoints']
    completed_reading: bool
    current: ChapterReadingCurrentResponse | None
    next_unread_chapter_id: int | None
    next_unread_chapter_number: int | None


class ChapterReadingItemResponse(Chapter):
    ordinal: int
    followed_ordinal: int | None
    followed: bool
    completed_checkpoint: bool
    max_percent: float | None


class ChapterReadingPageResponse(BaseModel):
    novel_id: int
    reading_run_key: str | None
    revision: int
    total: int
    offset: int
    limit: int
    items: list[ChapterReadingItemResponse]
