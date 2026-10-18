"""Stable chapter address and optimistic topology contracts."""
from typing import Annotated
from pydantic import BaseModel, Field

ChapterKey = Annotated[str, Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')]
ManifestRevision = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,18})$')]


class ChapterWriteIdentity(BaseModel):
    expected_chapter_key: ChapterKey | None = None
    expected_manifest_epoch: ChapterKey | None = None
    expected_manifest_revision: ManifestRevision | None = None
    expected_content_version: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class ChapterIdentityResponse(BaseModel):
    chapter_key: ChapterKey
    manifest_epoch: ChapterKey
    manifest_revision: ManifestRevision


class ChapterSelectionIdentity(ChapterWriteIdentity):
    chapter_number: int = Field(ge=-2147483648, le=2147483647, strict=True)
