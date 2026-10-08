"""Versioned per-user export document (libraries, novels, progress, etc.).

Everything is keyed by source URL and chapter number, never by database id,
so an export can be imported into a different Nexus instance.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EXPORT_FORMAT = "nexus-user-export"
EXPORT_VERSION = 1


class ExportProgress(BaseModel):
    chapter_number: int
    position: int = 0
    percent: float = 0


class ExportHistoryPoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chapter_number: int
    day: str = Field(alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_percent: int = 0


class ExportAnnotation(BaseModel):
    chapter_number: int
    annotation_type: Literal["bookmark", "note", "highlight"] = "bookmark"
    position: int = 0
    percent: float = 0
    quote: Optional[str] = None
    note: Optional[str] = None


class ExportNovel(BaseModel):
    url: str = Field(min_length=1, max_length=255)
    title: Optional[str] = None
    site: Optional[str] = None
    metadata_id: Optional[int] = None
    follow_state: Optional[Literal["plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"]] = None
    followed_at: Optional[datetime] = None
    progress: Optional[ExportProgress] = None
    history: list[ExportHistoryPoint] = Field(default_factory=list)
    annotations: list[ExportAnnotation] = Field(default_factory=list)


class ExportLibrary(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    novels: list[ExportNovel] = Field(default_factory=list)


class ExportSavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)
    notify_on_match: bool = False


class UserDataDocument(BaseModel):
    format: Literal["nexus-user-export"]
    version: int
    exported_at: Optional[datetime] = None
    libraries: list[ExportLibrary] = Field(default_factory=list)
    saved_searches: list[ExportSavedSearch] = Field(default_factory=list)
