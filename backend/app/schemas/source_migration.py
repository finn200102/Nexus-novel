"""Explicit review contracts for private reading-source continuity."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.reading_runs import ReadingRunProgressResponse


class SourceMigrationMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_chapter_id: int = Field(gt=0)
    target_chapter_id: int | None = Field(default=None, gt=0)


class SourceMigrationPreviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_novel_id: int = Field(gt=0)
    target_novel_id: int = Field(gt=0)
    mappings: list[SourceMigrationMapping] = Field(default_factory=list, max_length=20000)

    @model_validator(mode='after')
    def distinct(self):
        if self.source_novel_id == self.target_novel_id:
            raise ValueError('Choose a different owned story copy')
        ids = [row.source_chapter_id for row in self.mappings]
        if len(ids) != len(set(ids)):
            raise ValueError('Each source chapter can be selected only once')
        targets = [row.target_chapter_id for row in self.mappings if row.target_chapter_id is not None]
        if len(targets) != len(set(targets)):
            raise ValueError('Each target chapter can be selected only once')
        return self


class SourceMigrationApplyInput(SourceMigrationPreviewInput):
    review_token: str = Field(min_length=1, max_length=4096)
    operation_id: str = Field(min_length=1, max_length=128)


class SourceMigrationUndoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=128)


class SourceMigrationStory(BaseModel):
    novel_id: int
    library_id: int
    title: str
    site: str | None
    source_url: str | None
    chapter_count: int
    current_progress: ReadingRunProgressResponse | None
    eligible: bool
    blocked_reason: str | None


class SourceMigrationTargets(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SourceMigrationStory]


class SourceMigrationChapter(BaseModel):
    id: int
    chapter_number: int
    title: str | None


class SourceMigrationChapters(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SourceMigrationChapter]


class SourceMigrationCandidate(BaseModel):
    target_chapter_id: int
    chapter_number: int
    title: str | None
    evidence: list[str]
    content_equal: bool


class SourceMigrationItem(BaseModel):
    source_chapter_id: int
    source_chapter_number: int
    source_title: str | None
    candidates: list[SourceMigrationCandidate]
    candidates_truncated: bool
    selected_target_chapter_id: int | None
    decision: Literal['matched', 'ambiguous', 'unmatched', 'manual', 'skipped']
    required_for_progress: bool
    annotation_count: int
    annotations_copyable: int
    approximate_position: bool
    receipt_copyable: bool


class SourceMigrationCounts(BaseModel):
    mapped: int
    skipped: int
    unresolved: int
    annotations_copied: int
    annotations_retained: int
    receipts_copied: int
    history_copied: int
    preferences_copied: int
    followed_categories_copied: int


class SourceMigrationPreview(BaseModel):
    total: int
    offset: int
    limit: int
    source: SourceMigrationStory
    target: SourceMigrationStory
    items: list[SourceMigrationItem]
    counts: SourceMigrationCounts
    warnings: list[str]
    can_apply: bool
    review_token: str | None
    expires_at: str | None


class SourceMigrationRecord(BaseModel):
    id: int
    revision: int
    status: Literal['applied', 'undone']
    source: SourceMigrationStory
    target: SourceMigrationStory
    mappings: list[SourceMigrationMapping]
    counts: SourceMigrationCounts
    created_at: str
    undone_at: str | None
    target_progress: ReadingRunProgressResponse | None
    can_undo: bool
    undo_blocked_reason: str | None


class SourceMigrationPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SourceMigrationRecord]


class SourceMigrationConflictDetail(BaseModel):
    code: str
    message: str


class SourceMigrationConflict(BaseModel):
    detail: SourceMigrationConflictDetail
