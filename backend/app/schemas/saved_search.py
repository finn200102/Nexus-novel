"""Versioned catalog queries; unknown criteria must never broaden a search."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer


class SavedDiscoveryFilters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    tag: list[str] = Field(default_factory=list, max_length=100)
    tagMode: Literal['all', 'any'] = 'all'
    fandom: list[str] = Field(default_factory=list, max_length=100)
    genre: list[str] = Field(default_factory=list, max_length=100)
    excludeTag: list[str] = Field(default_factory=list, max_length=100)
    excludeFandom: list[str] = Field(default_factory=list, max_length=100)
    excludeGenre: list[str] = Field(default_factory=list, max_length=100)
    excludeAuthor: list[str] = Field(default_factory=list, max_length=100)
    excludeText: list[str] = Field(default_factory=list, max_length=100)
    language: list[str] = Field(default_factory=list, max_length=100)
    completeOnly: Literal['', 'true'] = ''
    crossover: Literal['', 'true', 'false'] = ''
    status: str = Field(default='', max_length=100)
    minWordCount: str = ''
    minFavorites: str = ''
    minFollows: str = ''
    minReviews: str = ''
    minChapterCount: str = ''
    maxWordCount: str = ''
    updatedSinceDays: str = ''
    label: str = Field(default='', max_length=200)
    labelOrigin: Literal['', 'source', 'ai', 'user', 'community'] = ''
    importState: Literal['', 'ready', 'in_progress'] = ''
    sortBy: Literal['updated', 'title', 'word_count', 'favorites', 'follows', 'reviews', 'views', 'chapter_count'] = 'updated'
    sortOrder: Literal['asc', 'desc'] = 'desc'

    @field_validator('tag', 'fandom', 'genre', 'excludeTag', 'excludeFandom', 'excludeGenre', 'excludeAuthor', 'excludeText', 'language')
    @classmethod
    def terms(cls, values):
        result, seen = [], set()
        for value in values:
            value = value.strip()
            if not value or len(value) > 200:
                raise ValueError('Search terms must contain 1–200 characters')
            if value.casefold() not in seen:
                seen.add(value.casefold()); result.append(value)
        return result

    @field_validator('minWordCount', 'minFavorites', 'minFollows', 'minReviews', 'minChapterCount', 'maxWordCount', 'updatedSinceDays')
    @classmethod
    def numbers(cls, value, info):
        if value == '': return value
        if not value.isascii() or not value.isdecimal() or len(value) > 10:
            raise ValueError('Use a nonnegative whole number')
        number = int(value)
        if number > 2_147_483_647 or (info.field_name == 'updatedSinceDays' and not 1 <= number <= 3650):
            raise ValueError('Search number is outside its supported range')
        return str(number)

    @model_validator(mode='after')
    def word_range(self):
        if self.minWordCount and self.maxWordCount and int(self.minWordCount) > int(self.maxWordCount):
            raise ValueError('Minimum word count exceeds maximum word count')
        return self


class SavedSearchDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    version: Literal[1, 2] = 1
    scope: Literal['catalog'] = 'catalog'
    q: str = Field(default='', max_length=500)
    site: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9_-]{0,79}$')
    similar_to: int | None = Field(default=None, gt=0, le=2_147_483_647)
    filters: SavedDiscoveryFilters = Field(default_factory=SavedDiscoveryFilters)
    canonical_include: list[str] = Field(default_factory=list, max_length=100)
    canonical_exclude: list[str] = Field(default_factory=list, max_length=100)

    @field_validator('canonical_include', 'canonical_exclude')
    @classmethod
    def canonical_keys(cls, values):
        from uuid import UUID
        result=[]
        for value in values:
            try:key=str(UUID(value))
            except (ValueError,AttributeError) as exc:raise ValueError('Choose a reviewed canonical term') from exc
            if key not in result:result.append(key)
        return result

    @model_validator(mode='after')
    def versioned_criteria(self):
        if self.version==1 and (self.canonical_include or self.canonical_exclude):
            raise ValueError('Canonical criteria require saved-search version 2')
        if set(self.canonical_include)&set(self.canonical_exclude):
            raise ValueError('A canonical term cannot be both included and excluded')
        return self

    @model_serializer(mode='wrap')
    def portable_version(self, handler):
        value=handler(self)
        if self.version==1:
            value.pop('canonical_include',None);value.pop('canonical_exclude',None)
        return value


    @field_validator('version', mode='before')
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value not in (1,2):
            raise ValueError('Unsupported saved-search version')
        return value

    @field_validator('site', mode='before')
    @classmethod
    def all_sites(cls, value):
        return None if value in ('', 'all') else value


class SavedSearchWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    definition: SavedSearchDefinition | None = None
    filters: dict = Field(default_factory=dict)
    notify_on_match: bool = False

    @model_validator(mode='after')
    def one_definition(self):
        if self.definition is not None and self.filters:
            raise ValueError('Provide a definition or legacy filters, not both')
        if len(str(self.filters)) > 100_000:
            raise ValueError('Saved search is too large')
        return self


class SavedSearchUpdate(SavedSearchWrite):
    expected_revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')


class SavedSearchResponse(BaseModel):
    id: int
    name: str
    filters: dict
    definition: SavedSearchDefinition | None
    revision: str
    needs_review: bool
    warnings: list[str]
    notify_on_match: bool
    alert_state: Literal['off', 'paused']
    created_at: str
    updated_at: str


class SavedSearchDeleted(BaseModel):
    deleted: bool
