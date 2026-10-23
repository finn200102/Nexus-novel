from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chapter_identity import ChapterWriteIdentity


class AudioProviderSnapshot(BaseModel):
    id: str = Field(default="custom")
    base_url: str
    model: str
    voice: str
    language_code: str | None = None
    execution_mode: Literal["browser", "server"] = "server"


class AudioChapterIdentity(ChapterWriteIdentity):
    pass

class SelectedAudioChapterIdentity(AudioChapterIdentity):
    chapter_number: int = Field(ge=-2147483648, le=2147483647, strict=True)
    model_config = ConfigDict(extra="forbid")


class AudioJobCreate(AudioChapterIdentity):
    library_id: int
    novel_id: int
    chapter_number: int = Field(ge=-2147483648, le=2147483647, strict=True)
    voice_profile_id: int | None = None
    include_author_notes: bool = False
    preparation_provider_id: int | None = Field(default=None, gt=0)
    qwen_chunk_size: Literal[350, 800, 1500, 3000] | None = None
    provider: AudioProviderSnapshot


class AudioJobResponse(BaseModel):
    id: int
    chapter_id: int | None = None
    chapter_number: int | None = None
    chapter_key: str | None = None
    manifest_epoch: str | None = None
    manifest_revision: str | None = None
    source_chapter_key: str | None = None
    source_manifest_epoch: str | None = None
    source_manifest_revision: str | None = None
    chapter_archived: bool = False
    source_identity_current: bool = False
    source_identity_inferred: bool = False
    chapter_title_snapshot: str | None = None
    chapter_number_snapshot: int | None = None
    status: str
    provider_id: str
    provider_model: str
    provider_voice: str
    qwen_chunk_size: int | None = None
    generation_token_limit: int | None = None
    total_parts: int
    completed_parts: int
    attempt_count: int
    max_attempts: int
    error_code: str | None = None
    error: str | None = None
    source_version: str | None = None
    include_author_notes: bool | None = None
    voice_profile_id: int | None = None
    pronunciation_version: str | None = None
    preparation_version: str | None = None
    preparation_completed_parts: int | None = None
    speech_stage: Literal["preparing_text", "generating_audio"] | None = None
    audio_ready: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StoryAudioRecordingPage(BaseModel):
    items:list[AudioJobResponse]
    total:int
    offset:int
    limit:int


class StoryAudioChapter(BaseModel):
    chapter_key: str
    manifest_epoch: str
    manifest_revision: str
    id: int
    chapter_number: int
    title: str | None
    content_status: str
    downloaded: bool
    source_version: str | None
    latest_job: AudioJobResponse | None


class StoryAudioSummary(BaseModel):
    chapters: int
    downloaded: int
    ready: int
    queued: int
    needs_retry: int


class StoryAudioResponse(BaseModel):
    novel_id: int
    total: int
    offset: int
    limit: int
    summary: StoryAudioSummary
    chapters: list[StoryAudioChapter]


class StoryAudioCreate(BaseModel):
    chapter_identities: list[SelectedAudioChapterIdentity] | None = Field(default=None, max_length=200)
    chapter_numbers: list[Annotated[int, Field(ge=-2147483648, le=2147483647, strict=True)]] = Field(min_length=1, max_length=200)
    voice_profile_id: int | None = Field(default=None, gt=0)
    provider: AudioProviderSnapshot | None = None
    include_author_notes: bool = False
    preparation_provider_id: int | None = Field(default=None, gt=0)
    qwen_chunk_size: Literal[350, 800, 1500, 3000] | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def choose_one_provider(self):
        if self.chapter_identities is not None:
            numbers = [item.chapter_number for item in self.chapter_identities]
            if len(set(numbers)) != len(numbers) or set(numbers) != set(self.chapter_numbers):
                raise ValueError("Capture one identity for every selected chapter, without extras or duplicates")
            if any(any(getattr(item, name) is None for name in AudioChapterIdentity.model_fields) for item in self.chapter_identities):
                raise ValueError("Capture all four original chapter identity fields")
        if (self.voice_profile_id is None) == (self.provider is None):
            raise ValueError("Choose either a private narrator or a server speech provider")
        return self


class StoryAudioOutcome(BaseModel):
    error_code: str | None = None
    message: str | None = None
    chapter_number: int
    outcome: Literal["unavailable", "already_ready", "already_queued", "needs_retry", "queued"]
    job: AudioJobResponse | None = None


class StoryAudioBatchResponse(BaseModel):
    novel_id: int
    outcomes: list[StoryAudioOutcome]


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


class AudioSourceSpan(BaseModel):
    block_id: str
    text_offset: int
    text_length: int


class AudioManifestSegment(BaseModel):
    source_spans: list[AudioSourceSpan] = Field(default_factory=list)
    part_index: int
    block_id: str | None = None
    text_offset: int | None = None
    text_length: int | None = None
    start_seconds: float
    end_seconds: float


class AudioManifestResponse(BaseModel):
    job_id: int
    chapter_id: int | None = None
    chapter_number: int | None = None
    chapter_key: str | None = None
    manifest_epoch: str | None = None
    manifest_revision: str | None = None
    source_chapter_key: str | None = None
    source_manifest_epoch: str | None = None
    source_manifest_revision: str | None = None
    source_identity_current: bool = False
    source_identity_inferred: bool = False
    chapter_archived: bool = False
    chapter_title_snapshot: str | None = None
    chapter_number_snapshot: int | None = None
    source_version: str | None = None
    rendition: Literal["original"]
    include_author_notes: bool | None = None
    pronunciation_version: str | None = None
    precision: Literal["segment", "unavailable"]
    current_source: bool
    duration_seconds: float | None = None
    segments: list[AudioManifestSegment]


class ExpressionPreviewRequest(AudioChapterIdentity):
    model_config = ConfigDict(extra='forbid')
    novel_id: int
    chapter_number: int
    provider_id: int = Field(gt=0)
    include_author_notes: bool = False


class ExpressionPreviewPart(BaseModel):
    original_text: str
    text: str


class ExpressionPreviewResponse(BaseModel):
    parts: list[ExpressionPreviewPart]
    warnings: list[str]


class AudioPartResponse(BaseModel):
    part_index: int
    text: str
    synthesis_text: str | None = None
    status: str
    error: str | None = None
    duration_seconds: float | None = None


class AudioPartsResponse(BaseModel):
    parts: list[AudioPartResponse]
