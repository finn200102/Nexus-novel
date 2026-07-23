from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DownloadQueueRequest(BaseModel):
    library_id: int
    novel_id: int
    count: int = Field(default=1, ge=1, le=100)


class DownloadJobResponse(BaseModel):
    id: int
    library_id: int
    novel_id: int
    chapter_id: int
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_attempt_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    error_code: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DownloadJobAction(BaseModel):
    reason: str | None = None
