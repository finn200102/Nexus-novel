from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AudioExportCreate(BaseModel):
    novel_id: int = Field(gt=0)
    audio_job_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=200)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def distinct_jobs(self):
        if len(set(self.audio_job_ids)) != len(self.audio_job_ids):
            raise ValueError("Choose each chapter recording once")
        return self


class AudioExportChapter(BaseModel):
    audio_job_id: int
    chapter_key: str | None = None
    manifest_epoch: str | None = None
    manifest_revision: str | None = None
    chapter_archived: bool = False
    chapter_number: int
    original_chapter_number: int | None = None
    title: str
    source_version: str | None = None
    duration_seconds: float | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


class AudioExportResponse(BaseModel):
    id: int
    novel_id: int
    status: str
    total_chapters: int
    completed_chapters: int
    audio_bytes: int | None = None
    duration_seconds: float | None = None
    attempt_count: int
    max_attempts: int
    error_code: str | None = None
    error: str | None = None
    file_ready: bool
    chapters: list[AudioExportChapter]
    created_at: datetime
    updated_at: datetime
