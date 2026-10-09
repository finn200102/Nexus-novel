from datetime import datetime

from pydantic import BaseModel, Field


class WebhookCreateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    # Empty or missing means unsigned requests.
    secret: str | None = Field(default=None, max_length=200)
    event_types: list[str] = Field(default_factory=lambda: ["new_chapters"], min_length=1)
    enabled: bool = True


class WebhookUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    secret: str | None = Field(default=None, max_length=200)
    clear_secret: bool = False
    event_types: list[str] | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class WebhookItem(BaseModel):
    id: int
    url_hint: str
    has_secret: bool
    event_types: list[str]
    enabled: bool
    last_status_code: int | None
    last_error: str | None
    last_delivered_at: datetime | None
    consecutive_failures: int
    created_at: datetime | None


class WebhookTestResult(BaseModel):
    ok: bool
    status_code: int | None
    error: str | None


class PersonalFeedStatus(BaseModel):
    active: bool
    feed_url: str | None = None
