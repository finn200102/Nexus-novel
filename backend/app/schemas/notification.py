from datetime import datetime

from pydantic import BaseModel, Field


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=64)


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)


class PushSubscriptionResponse(BaseModel):
    id: int
    user_agent: str | None = None
    created_at: datetime | None = None
    last_success_at: datetime | None = None
    failure_count: int = 0


class ChannelCreateRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    label: str = Field(default="", max_length=120)
    enabled: bool = True


class ChannelUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=3, max_length=2000)
    label: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class ChannelResponse(BaseModel):
    """Never includes the Apprise URL itself, only its scheme and host."""

    id: int
    kind: str
    label: str
    url_hint: str
    enabled: bool
    last_error: str | None = None
    created_at: datetime | None = None
