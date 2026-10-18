"""Catalog presentation contracts shared in shape with metadata responses."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator

class SiteEnum(str, Enum):
    fanfiction = "fanfiction"
    archive = "archive"
    royalroad = "royalroad"
    spacebattles = "spacebattles"
    sufficientvelocity = "sufficientvelocity"
    questionablequesting = "questionablequesting"
    scribblehub = "scribblehub"
    webnovel = "webnovel"
    webserial = "webserial"

class NovelListItem(BaseModel):
    """Summary of a novel for list endpoints."""

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "title": "Example Story Title",
                    "author": "Author Name",
                    "author_id": 12345,
                    "source_url": "https://www.fanfiction.net/s/12345678",
                    "novel_site": "fanfiction",
                    "img_url": "https://www.fanfiction.net/cover/12345678.jpg",
                    "description": "A great story about...",
                    "word_count": 50000,
                    "views": 10000,
                    "favorites": 500,
                    "follows": 50,
                    "reviews": 100,
                    "status": "In Progress",
                    "rating": 4.5,
                    "chapter_count": 25,
                    "created_at": "2024-01-15T10:00:00",
                    "updated_at": "2024-01-15T10:00:00",
                }
            ]
        },
    }

    id: int
    title: str
    author: str | None = None
    author_id: int | None = None
    source_url: str
    novel_site: SiteEnum | None = None
    img_url: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    fandoms: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    content_rating: str = "not_rated"
    word_count: int | None = None
    views: int | None = None
    favorites: int | None = None
    kudos: int | None = None
    bookmarks: int | None = None
    comments: int | None = None
    follows: int | None = None
    reviews: int | None = None
    status: str | None = None
    rating: float | None = None
    chapter_count: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("tags", "genres", "fandoms", "characters", "relationships", mode="before")
    @classmethod
    def default_empty_list(cls, v) -> list[str]:
        return v or []

class GroupedWork(BaseModel):
    group_key: str
    reviewed: bool
    title: str
    representative: NovelListItem
    editions: list[NovelListItem]
    matching_edition_count: int

class GroupedWorkPage(BaseModel):
    data: list[GroupedWork]
    total: int
    next_cursor: int | None
    has_more: bool
