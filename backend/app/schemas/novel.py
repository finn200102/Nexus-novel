from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
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
