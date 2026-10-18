"""One-page discovery responses; source identities never redefine story sites."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit


class LiveSearchResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: int | None = Field(gt=0, strict=True)
    metadata_id: int | None = Field(gt=0, strict=True)
    title: str
    source_url: str
    url: str | None = None
    author: str | None = None
    description: str | None = None
    img_url: str | None = None
    site: str | None = None
    novel_site: str | None = None
    source_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    fandoms: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    content_rating: str | None = None
    word_count: int | None = None
    chapter_count: int | None = None
    status: str | None = None
    sources: list[Literal['local', 'live']]

    @field_validator('source_url', 'url')
    @classmethod
    def web_link(cls, value):
        if value is None:
            return value
        parts = urlsplit(value)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
            raise ValueError('A source URL must be a web address without credentials')
        return value

    @model_validator(mode='after')
    def same_identity(self):
        if self.id != self.metadata_id:
            raise ValueError('Catalog identity is inconsistent')
        if self.url is not None and self.url != self.source_url:
            raise ValueError('Source URL identity is inconsistent')
        return self


class LiveSearchError(BaseModel):
    site: str
    code: str
    message: str
    retryable: bool | None = None


class LiveSearchPage(BaseModel):
    page: int
    results: list[LiveSearchResult] = Field(max_length=1000)
    errors: list[LiveSearchError]
    has_more: bool | None


class LiveSourcePage(LiveSearchPage):
    source_id: str
    site: str | None = None
    feed: str | None = None


class LiveSourceCapability(BaseModel):
    source_id: str = Field(max_length=80)
    site: str
    name: str
    kind: Literal['builtin', 'plugin']
    search: bool
    browse_feeds: list[str] = Field(max_length=100)
    user_lists: list[str] = Field(max_length=100)
    plugin_id: str | None
    version: str | None
    digest: str | None
    limitations: list[str] = Field(max_length=20)


class LiveCapabilitiesResponse(BaseModel):
    sources_limited: bool
    search: list[str] = Field(max_length=100)
    browse: dict[str, list[str]]
    user_lists: dict[str, list[str]]
    sources: list[LiveSourceCapability] = Field(max_length=100)
