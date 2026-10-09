from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AppPasswordCreate(BaseModel):
    label: str = Field(default="", max_length=120)
    scope: Literal["opds", "kosync", "extension"]


class AppPasswordItem(BaseModel):
    id: int
    label: str
    scope: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class AppPasswordCreated(AppPasswordItem):
    # Shown once; the server keeps only a hash.
    secret: str


class KosyncProgressUpdate(BaseModel):
    document: str = Field(min_length=1, max_length=64)
    progress: str = Field(default="", max_length=512)
    percentage: float = Field(default=0, ge=0, le=1)
    device: str = Field(default="", max_length=100)
    device_id: str = Field(default="", max_length=100)
