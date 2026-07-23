from datetime import date, datetime

from pydantic import BaseModel


class ActivityEventResponse(BaseModel):
    id: int
    novel_id: int
    novel_title: str
    event_type: str
    chapter_count: int
    first_chapter_number: int | None = None
    last_chapter_number: int | None = None
    message: str
    details: dict = {}
    notification_visible: bool
    read_at: datetime | None = None
    created_at: datetime


class ActivityDay(BaseModel):
    date: date
    event_count: int
    chapter_count: int
    stories_resumed: int
    source_failures: int
    downloads_completed: int


class ActivitySummary(BaseModel):
    start_date: date
    end_date: date
    event_count: int
    chapter_count: int
    stories_resumed: int
    source_failures: int
    downloads_completed: int
    unread_count: int
