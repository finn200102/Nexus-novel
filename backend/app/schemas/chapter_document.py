"""Lossless wire contracts for current and legacy saved chapter documents.

Optional fields describe sparse legacy documents without injecting new keys;
unknown source, asset and provenance fields remain available to clients.
"""
from pydantic import BaseModel, ConfigDict


class ChapterImageAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int | None = None
    ready: int | None = None
    missing: int | None = None
    limited: int | None = None
    bytes: int | None = None
    failures: dict[str, int] | None = None


class ChapterBlockResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    kind: str | None = None
    html: str | None = None
    text: str | None = None
    role: str | None = None
    role_provenance: str | None = None


class ChapterDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: int | None = None
    content_version: str | None = None
    source_format: str | None = None
    blocks: list[ChapterBlockResponse] | None = None
    plain_text: str | None = None
    image_assets: ChapterImageAssetsResponse | None = None
