"""Versioned per-user export document (libraries, novels, progress, etc.).

Stories use source URLs. Reading material uses explicit chapter references;
foreign references require review rather than binding by chapter number.
"""

from datetime import datetime
from uuid import UUID
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.reader_preferences import PreferenceValues, Typography
from app.schemas.chapter import SavedLocatorFields
from app.schemas.discovery_preferences import DiscoveryPreferences
from app.schemas.pronunciation import PronunciationRule
from app.schemas.reading_activity import ActivityValues,ExportReadingGoal

EXPORT_FORMAT = "nexus-user-export"
EXPORT_VERSION = 2


class ExportChapterReference(BaseModel):
    """Portable evidence, never authority to bind another instance by ordinal."""
    ref: str = Field(min_length=1,max_length=128)
    chapter_key: UUID | None = None
    manifest_epoch: UUID | None = None
    metadata_manifest_key: UUID | None = None
    metadata_chapter_key: UUID | None = None
    source_version: str | None = Field(None,max_length=64)
    chapter_number: int | None = Field(None,ge=-(2**31),le=2**31-1)
    title: str | None = Field(None,max_length=1000)
    archived: bool = False
    source_site: str | None = Field(None,max_length=100)
    source_story_id: str | None = Field(None,max_length=255)
    source_url: str | None = Field(None,max_length=2000)


class ExportProgress(SavedLocatorFields):
    chapter_ref: str | None = Field(None,max_length=128)
    furthest_chapter_ref: str | None = Field(None,max_length=128)
    reading_run_key: Optional[UUID] = None
    chapter_number: int = Field(ge=-(2**31),le=2**31-1)
    position: int = 0
    percent: float = 0
    block_id: Optional[str] = Field(None, max_length=128)
    text_offset: int = Field(0, ge=0, le=16_000_000)
    furthest_chapter_number: Optional[int] = Field(None, ge=-(2**31),le=2**31-1)
    furthest_percent: Optional[float] = None


class ExportHistoryPoint(BaseModel):
    chapter_ref: str | None = Field(None,max_length=128)
    model_config = ConfigDict(populate_by_name=True)

    chapter_number: int = Field(ge=-(2**31),le=2**31-1)
    day: str = Field(alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_percent: int = 0
    reading_run_key: Optional[UUID] = None


class ExportReadingRunEvent(BaseModel):
    kind: Literal["started", "completed", "abandoned"]
    occurred_at: Optional[datetime] = None
    inferred: bool = False
    reason: Optional[str] = Field(None, max_length=500)


class ExportReadingContinuityCompletion(BaseModel):
    occurred_at: Optional[datetime] = None
    inferred: bool = False


class ExportReadingContinuity(BaseModel):
    key: UUID
    work_key: UUID
    logical_ordinal: int = Field(ge=1)
    completion: Optional[ExportReadingContinuityCompletion] = None


class ExportReadingRun(BaseModel):
    continuity: Optional[ExportReadingContinuity] = None
    reading_run_key: UUID
    ordinal: int = Field(ge=1)
    status: Literal["active", "completed", "abandoned"]
    started_at: Optional[datetime] = None
    started_at_inferred: bool = False
    completed_at: Optional[datetime] = None
    completed_at_inferred: bool = False
    abandoned_at: Optional[datetime] = None
    abandon_reason: Optional[str] = Field(None, max_length=500)
    archived_at: Optional[datetime] = None
    progress: Optional[ExportProgress] = None
    events: list[ExportReadingRunEvent] = Field(default_factory=list, max_length=5000)


class ExportAnnotation(SavedLocatorFields):
    chapter_ref: str | None = Field(None,max_length=128)
    chapter_number: int | None = Field(None,ge=-(2**31),le=2**31-1)
    annotation_type: Literal["bookmark", "note", "highlight"] = "bookmark"
    position: int = 0
    percent: float = 0
    quote: Optional[str] = None
    note: Optional[str] = None
    block_id: Optional[str] = Field(None, max_length=128)
    text_offset: int = Field(0, ge=0, le=16_000_000)


class ExportPersonal(BaseModel):
    """Private notes, personal rating and user tags. Optional on each novel."""

    notes: Optional[str] = Field(default=None, max_length=20000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    user_tags: list[str] = Field(default_factory=list, max_length=30)


class ExportPronunciation(BaseModel):
    rules: list[PronunciationRule] = Field(default_factory=list, max_length=64)
    inherit_account: bool = True

    @field_validator("rules")
    @classmethod
    def unique_terms(cls, values):
        if len({rule.source for rule in values}) != len(values):
            raise ValueError("Each written pronunciation may appear only once")
        return values


class PortableStoryIdentity(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_account_key: UUID
    story_epoch: UUID


class ExportNovel(BaseModel):
    portable_story: PortableStoryIdentity | None = None
    chapter_refs: list[ExportChapterReference] = Field(default_factory=list,max_length=200000)
    pending_reading_imports: list[dict] = Field(default_factory=list,max_length=1000)
    url: str | None = Field(None,min_length=1,max_length=255)
    title: Optional[str] = None
    site: Optional[str] = None
    metadata_id: Optional[int] = None
    follow_state: Optional[Literal["plan_to_read", "reading", "on_hold", "completed", "dropped", "ignored"]] = None
    followed_at: Optional[datetime] = None
    progress: Optional[ExportProgress] = None
    history: list[ExportHistoryPoint] = Field(default_factory=list)
    annotations: list[ExportAnnotation] = Field(default_factory=list)
    personal: Optional[ExportPersonal] = None
    reader_typography: Optional[Typography] = None
    pronunciation: Optional[ExportPronunciation] = None
    reading_runs: list[ExportReadingRun] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def known_reading_runs(self):
        if self.url is None and self.portable_story is None:
            raise ValueError("A private story without a URL requires its portable story identity")
        keys = [str(run.reading_run_key) for run in self.reading_runs]
        if len(keys) != len(set(keys)):
            raise ValueError("Each reading run may appear only once per story")
        references = [point.reading_run_key for point in self.history] + ([self.progress.reading_run_key] if self.progress else [])
        if any(key is not None and str(key) not in keys for key in references):
            raise ValueError("Every referenced reading run must be included in this story")
        return self


class ExportLibrary(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    novels: list[ExportNovel] = Field(default_factory=list)


class ExportSavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)
    notify_on_match: bool = False


class ExportShelfNovel(BaseModel):
    """A member uses its source link or opaque private story origin."""
    library: str = Field(min_length=1,max_length=100)
    url: str | None = Field(None,min_length=1,max_length=255)
    portable_story: PortableStoryIdentity | None = None

    @model_validator(mode='after')
    def known_member(self):
        if self.url is None and self.portable_story is None:raise ValueError('A private shelf member needs its portable story identity')
        return self


class ExportShelf(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position: int = 0
    novels: list[ExportShelfNovel] = Field(default_factory=list)


class ExportSmartShelf(BaseModel):
    """Portable names and rules only, never instance IDs or evaluated members."""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    definition: dict
    libraries: list[str] | None = Field(None, max_length=100)
    static_shelf: str | None = Field(None, max_length=120)
    needs_review: bool = False

    @field_validator('definition')
    @classmethod
    def bounded_definition(cls, value):
        import json
        if len(json.dumps(value, ensure_ascii=False).encode()) > 16384:
            raise ValueError('Smart shelf criteria exceed 16 KiB')
        return value

    @field_validator('libraries')
    @classmethod
    def named_libraries(cls, value):
        if value is not None and any(not name.strip() or len(name) > 100 for name in value):
            raise ValueError('Choose valid library names for this smart shelf')
        return value


class ExportBlocklistEntry(BaseModel):
    kind: Literal["tag", "fandom", "genre", "author", "word"]
    value: str = Field(min_length=1, max_length=200)


class UserDataDocument(BaseModel):
    format: Literal["nexus-user-export"]
    version: int
    exported_at: Optional[datetime] = None
    libraries: list[ExportLibrary] = Field(default_factory=list)
    saved_searches: list[ExportSavedSearch] = Field(default_factory=list)
    # Optional keys added within format version 1: older exports omit them.
    shelves: list[ExportShelf] = Field(default_factory=list)
    smart_shelves: list[ExportSmartShelf] = Field(default_factory=list, max_length=500)
    blocklist: list[ExportBlocklistEntry] = Field(default_factory=list)
    reader_preferences: Optional[PreferenceValues] = None
    discovery_preferences: Optional[DiscoveryPreferences] = None
    pronunciation: Optional[ExportPronunciation] = None
    activity_preferences: Optional[ActivityValues] = None
    reading_goals: list[ExportReadingGoal] = Field(default_factory=list,max_length=200)

    @field_validator('reading_goals')
    @classmethod
    def unique_goal_years(cls,values):
        if len({entry.year for entry in values})!=len(values):raise ValueError('Each reading goal year may appear only once')
        return values
