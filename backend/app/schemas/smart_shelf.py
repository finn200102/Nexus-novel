from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.library_views import OwnedLibraryDefinition, LibraryStoryPage


class SmartShelfWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    definition: OwnedLibraryDefinition

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Choose a name for this smart shelf')
        return value


class SmartShelfUpdate(SmartShelfWrite):
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class SmartShelfResponse(BaseModel):
    id: int
    name: str
    definition: OwnedLibraryDefinition | None
    revision: str
    needs_review: bool
    warnings: list[str]
    created_at: datetime
    updated_at: datetime


class SmartShelfPageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(50, ge=1, le=100, strict=True)


class SmartShelfResults(LibraryStoryPage):
    definition_revision: str


class SmartShelfDeleted(BaseModel):
    deleted: bool
