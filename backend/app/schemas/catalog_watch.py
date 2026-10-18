"""Private catalog alert controls; preparation never activates delivery."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Revision = str

class PrepareWatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: Revision = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')
    mode: Literal['hybrid', 'lexical']

class ActivateWatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: Revision = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')
    prepared_revision: Revision = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')

class PauseWatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: Revision = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')
    watch_revision: Revision = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')

class WatchPageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(50, ge=1, le=100, strict=True)

class WatchState(BaseModel):
    search_id: int
    search_revision: str
    revision: str | None
    status: Literal['off', 'prepared', 'initializing', 'active', 'paused', 'error']
    mode: Literal['hybrid', 'lexical'] | None
    prepared_revision: str | None
    baseline_total: int | None
    match_count: int
    unread_count: int
    last_checked_at: datetime | None
    reason: str | None
    warnings: list[str]
    semantics: list[str]

class CatalogResultPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    has_more: bool

class CatalogMatchItem(BaseModel):
    id: int
    work_key: str
    novel: dict[str, Any]
    read_at: datetime | None
    matched_at: datetime

class CatalogMatchPage(BaseModel):
    items: list[CatalogMatchItem]
    total: int
    offset: int
    limit: int
    has_more: bool

class ReadMatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    watch_revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')

class MatchReadResult(BaseModel):
    read: Literal[True] = True
