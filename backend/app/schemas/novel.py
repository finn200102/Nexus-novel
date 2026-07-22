from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional
from datetime import datetime


class NovelCreate(BaseModel):
    url: str
    library_id: int


class Novel(BaseModel):
    id: int
    title: str
    url: str
    description: Optional[str] = None
    cover_image: Optional[str] = None
    library_id: int
    metadata_id: Optional[int] = None
    author: Optional[str] = None
    author_site_id: Optional[int] = None
    source_url: Optional[str] = None
    story_id: Optional[int] = None
    novel_site: Optional[str] = None
    img_url: Optional[str] = None
    word_count: Optional[int] = None
    reviews: Optional[int] = None
    favorites: Optional[int] = None
    follows: Optional[int] = None
    status: Optional[str] = None
    views: Optional[int] = None
    rating: Optional[int] = None
    publish_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    chapter_count: Optional[int] = None
    analyzed_at: Optional[datetime] = None
    analysis_type: Optional[str] = None
    analyzed_chapter_count: Optional[int] = None
    parsed_at: Optional[datetime] = None
    follow_state: Literal["plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"] = "plan_to_read"
    followed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NovelSearch(BaseModel):
    title: str
    url: str
    cover_image: Optional[str] = None


class NovelUpdate(BaseModel):
    id: int
    title: str
    url: str


class NovelFollowUpdate(BaseModel):
    follow_state: Literal["plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"]
    download_policy: Literal["none", "next_chapter", "next_n"] = "none"
    download_count: int = Field(default=0, ge=0, le=100)
    notification_policy: Literal["immediate", "daily_digest", "weekly_digest", "after_n"] = "immediate"


class NovelFollowSettings(BaseModel):
    novel_id: int
    follow_state: Literal["plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"]
    download_policy: Literal["none", "next_chapter", "next_n"]
    download_count: int
    notification_policy: Literal["immediate", "daily_digest", "weekly_digest", "after_n"]


class NovelUpdateEvent(BaseModel):
    id: int
    novel_id: int
    event_type: str
    chapter_count: int
    first_chapter_number: Optional[int] = None
    last_chapter_number: Optional[int] = None
    message: str
    details: dict = Field(default_factory=dict)
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
