from datetime import datetime

from pydantic import BaseModel


class OperationCounts(BaseModel):
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class ServiceStatus(BaseModel):
    status: str
    detail: str | None = None
    checked_at: datetime


class OperationsSummary(BaseModel):
    library_id: int
    followed_stories: int
    reading_stories: int
    unread_updates: int
    source_failures: int
    downloads: OperationCounts
    metadata_server: ServiceStatus
    metadata_jobs: OperationCounts
    source_health: dict[str, int]
    refresh_schedules: int
    generated_at: datetime
