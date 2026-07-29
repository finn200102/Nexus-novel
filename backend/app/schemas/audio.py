from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudioProviderSnapshot(BaseModel):
    id: str = Field(default="custom")
    base_url: str
    model: str
    voice: str
    language_code: str | None = None
    execution_mode: Literal["browser", "server"] = "server"


class AudioJobCreate(BaseModel):
    library_id: int
    novel_id: int
    chapter_number: int
    provider: AudioProviderSnapshot


class AudioJobResponse(BaseModel):
    id: int
    status: str
    provider_id: str
    provider_model: str
    provider_voice: str
    total_parts: int
    completed_parts: int
    attempt_count: int
    max_attempts: int
    error_code: str | None = None
    error: str | None = None
    audio_ready: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderCheckRequest(BaseModel):
    provider_id: str = "custom"
    base_url: str
    model: str
    voice: str
    language_code: str | None = None


class ProviderPreviewRequest(ProviderCheckRequest):
    text: str = Field(default="Nexus Novel is ready to read this chapter aloud.", max_length=600)


class ProviderCapability(BaseModel):
    id: str
    label: str
    execution_mode: Literal["browser", "server"]
    safe_segment_size: int
    experimental: bool
    supports_preview: bool = True
    supports_voice_preview: bool = True
    response_formats: list[str] = ["mp3", "wav"]
