"""An explicit review transfers addresses, never invents source completeness."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .chapter_identity import ChapterKey, ManifestRevision, ChapterIdentityResponse


class ManifestStateItem(ChapterIdentityResponse):
    id: int
    chapter_number: int
    title: str | None
    source_version: str | None
    archived: bool = False


class ManifestStatePage(BaseModel):
    novel_id: int
    manifest_epoch: ChapterKey
    manifest_revision: ManifestRevision
    identity_required: bool
    total: int
    items: list[ManifestStateItem]
    next_cursor: str | None
    has_more: bool


class ChapterManifestMapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chapter_key: ChapterKey
    metadata_chapter_key: ChapterKey
    confirm_inferred_anchors: bool = False


class ManifestPreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_manifest_epoch: ChapterKey
    expected_manifest_revision: ManifestRevision
    archive_chapter_keys: list[ChapterKey] = Field(default_factory=list,max_length=200_000)
    mappings: list[ChapterManifestMapping] = Field(default_factory=list,max_length=200_000)
    resolve_current_chapter_key: ChapterKey | None = None
    resolve_furthest_chapter_key: ChapterKey | None = None


class ManifestApplyInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    review_token: str = Field(min_length=1,max_length=4096)
    operation_id: str = Field(min_length=1,max_length=128)


class ManifestUndoInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1,strict=True)
    expected_manifest_epoch: ChapterKey
    expected_manifest_revision: ManifestRevision
    operation_id: str = Field(min_length=1,max_length=128)


class ManifestSourceNamespace(BaseModel):
    site: str | None
    story_id: int | None
    source_url: str | None


class ManifestRemoteState(BaseModel):
    source_capture_id: ChapterKey | None = None
    source_authority_kind: Literal['adapter_stable','reviewed_mapping'] | None = None
    source_review_id: ChapterKey | None = None
    source_lineage_fingerprint: str | None = Field(default=None,pattern="^[0-9a-f]{64}$")
    source: ManifestSourceNamespace
    manifest_key: ChapterKey
    revision: str
    fingerprint: str
    total: int
    identity_kind: Literal['stable_source_id','positional','unknown']
    complete: bool
    source_complete: bool
    deletion_authoritative: bool


class ManifestRemoteChoice(BaseModel):
    metadata_chapter_key: ChapterKey
    chapter_number: int
    title: str | None
    identity_kind: Literal['stable_source_id','positional','unknown']


class ManifestReviewItem(BaseModel):
    can_archive: bool = False
    archive_blocked_reason: str | None = None
    archived: bool = False
    chapter_key: ChapterKey | None
    metadata_chapter_key: ChapterKey | None
    title: str | None
    from_number: int | None
    to_number: int | None
    decision: Literal['bound','stable_source_id','explicit','new','needs_mapping','unlisted','archive']
    requires_content_review: bool
    inferred_anchor_count: int
    candidates: list[ManifestRemoteChoice] = Field(default_factory=list,max_length=20)
    candidates_truncated: bool = False


class ManifestReviewItemPage(BaseModel):
    review_id: int
    items: list[ManifestReviewItem]
    total: int
    offset: int
    limit: int
    has_more: bool


class ManifestRemoteChoicePage(BaseModel):
    review_id: int
    items: list[ManifestRemoteChoice]
    total: int
    offset: int
    limit: int
    has_more: bool


class ManifestReviewCounts(BaseModel):
    newly_archived_chapters: int = 0
    archived_chapters: int = 0
    restored_chapters: int = 0
    source_chapters: int
    local_chapters: int
    mapped: int
    new: int
    renumbered: int
    unmapped: int
    inferred_anchors: int


class ManifestBlocker(BaseModel):
    code: str
    message: str
    count: int = 1


class ManifestAnchor(BaseModel):
    relocated: bool = False
    previous_chapter_key: ChapterKey | None = None
    previous_chapter_number: int | None = None
    previous_percent: float | None = None
    kind: Literal['current','furthest']
    chapter_key: ChapterKey | None
    chapter_number: int | None
    percent: float
    identity_inferred: bool
    resolved: bool
    content_version: str | None


class ManifestReviewView(BaseModel):
    review_id: int
    revision: int
    review_token: str
    status: Literal['preview','applied','undone']
    novel_id: int
    manifest_epoch: ChapterKey
    manifest_revision: ManifestRevision
    reviewed_manifest_epoch: ChapterKey
    reviewed_manifest_revision: ManifestRevision
    anchors: list[ManifestAnchor] = Field(max_length=2)
    expires_at: str
    remote: ManifestRemoteState
    counts: ManifestReviewCounts
    items: ManifestReviewItemPage
    unmapped: ManifestReviewItemPage
    blocked_reasons: list[ManifestBlocker]
    can_apply: bool
    can_undo: bool
    undo_blocked_reason: str | None


class ManifestReviewPage(BaseModel):
    items: list[ManifestReviewView]
    total: int
    offset: int
    limit: int
    has_more: bool


class ManifestOperationResponse(BaseModel):
    review_id: int
    revision: int
    status: Literal['applied','undone']
    novel_id: int
    manifest_epoch: ChapterKey
    manifest_revision: ManifestRevision
