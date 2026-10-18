"""Strict admin-review contracts; source labels and canonical identities differ."""

import json
import unicodedata
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["fandom", "genre", "tag", "character", "relationship"]
Action = Literal["approve", "reject", "undo"]
State = Literal["pending", "approved", "rejected", "undone"]


def key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Choose a valid immutable identity")


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fandom_term_id: str | None = None
    story_key: str | None = None

    @field_validator("fandom_term_id", "story_key")
    @classmethod
    def uuid(cls, value):
        return key(value) if value is not None else None


class TermCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    display_name: str = Field(min_length=1, max_length=200)
    scope: Scope = Field(default_factory=Scope)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        value = unicodedata.normalize("NFC", " ".join(value.split()))
        if not value:
            raise ValueError("Choose a nonempty canonical name")
        return value

    @model_validator(mode="after")
    def scoped(self):
        count = sum(
            value is not None
            for value in (self.scope.fandom_term_id, self.scope.story_key)
        )
        if self.kind in {"character", "relationship"}:
            if count != 1:
                raise ValueError(
                    "Character and relationship terms require exactly one fandom or story scope"
                )
        elif count:
            raise ValueError("This vocabulary kind uses global scope")
        return self


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)
    source_url: str | None = Field(None, max_length=2000)
    evidence: dict = Field(default_factory=dict)

    @field_validator("note")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Explain the alias evidence")
        return value.strip()

    @field_validator("evidence")
    @classmethod
    def bounded(cls, value):
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 4096:
            raise ValueError("Alias evidence exceeds 4 KiB")
        return value

    @field_validator("source_url")
    @classmethod
    def url(cls, value):
        if value is not None:
            from urllib.parse import urlsplit

            parts = urlsplit(value)
            if (
                parts.scheme not in {"https", "http"}
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                raise ValueError("Use a public evidence URL without credentials")
        return value


class AliasCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_id: str
    raw_kind: Kind
    raw_taxonomy_id: int = Field(gt=0, le=2147483647, strict=True)
    source_site: str | None = Field(None, pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    provenance: Provenance

    @field_validator("term_id")
    @classmethod
    def uuid(cls, value):
        return key(value)


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action


class DecisionInput(PreviewInput):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    review_token: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(None, max_length=2000)
    actor: str = Field(min_length=1, max_length=200)


class TermView(BaseModel):
    id: str
    kind: Kind
    display_name: str
    revision: str
    scope: Scope
    scope_label: str | None = None
    active: bool
    created_at: str
    updated_at: str


class RawView(BaseModel):
    id: int
    kind: Kind
    name: str
    normalized_name: str
    site: str | None = None
    reference_count: int
    media_type: str | None = None
    external_category_id: str | None = None
    legacy_aliases: list[str] = Field(default_factory=list)
    legacy_aliases_trusted: Literal[False] = False


class AuditView(BaseModel):
    id: int
    action: Action
    actor: str
    previous_state: State
    next_state: State
    previous_revision: str
    next_revision: str
    evidence_hash: str
    note: str | None
    created_at: str


class AliasView(BaseModel):
    id: str
    term: TermView
    raw_kind: Kind
    raw_taxonomy_id: int
    raw: RawView | None
    raw_identity_key: str
    source_site: str | None
    provenance: Provenance
    state: State
    effective: bool
    revision: str
    warnings: list[str]
    audits: list[AuditView]
    audits_limited: bool
    created_at: str
    updated_at: str


class PreviewView(BaseModel):
    alias: AliasView
    action: Action
    expected_revision: str
    review_token: str
    evidence_hash: str
    affected_count: int
    examples: list[dict]
    conflicts: list[str]
    expires_at: str


class TermPage(BaseModel):
    items: list[TermView]
    total: int
    offset: int
    limit: int
    has_more: bool


class RawPage(BaseModel):
    items: list[RawView]
    total: int
    offset: int
    limit: int
    has_more: bool


class AliasPage(BaseModel):
    items: list[AliasView]
    total: int
    offset: int
    limit: int
    has_more: bool


class StoryScopeView(BaseModel):
    story_key: str
    novel_id: int
    title: str
    site: str | None


class StoryScopePage(BaseModel):
    items: list[StoryScopeView]
    total: int
    offset: int
    limit: int
    has_more: bool
