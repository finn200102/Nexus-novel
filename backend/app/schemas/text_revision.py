"""Explicit local-only, ephemeral chapter editing requests."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from app.schemas.translation_identity import TranslationChapterIdentity
from app.schemas.chapter_identity import ChapterIdentityResponse

TextRevisionMode = Literal["proofreading", "reformat", "rewrite", "translation_polish"]


class RevisionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_version: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=160)
    text_offset: StrictInt = Field(ge=0)
    text_length: StrictInt = Field(gt=0, le=6000)
    quote: str = Field(min_length=1, max_length=3000)


class StoryTextStyleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)
    style_guide: str = Field(default="", max_length=2000)


class TextRevisionInput(TranslationChapterIdentity):
    model_config = ConfigDict(extra="forbid")
    provider_id: StrictInt = Field(gt=0)
    mode: TextRevisionMode
    selection: RevisionSelection | None = None
    translation_job_id: StrictInt | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def translation_selection(self):
        if (self.mode == "translation_polish") != (self.translation_job_id is not None):
            raise ValueError("Select a saved translation only for translation_polish")
        if self.mode == "translation_polish" and self.selection is not None:
            raise ValueError("Translation polishing previews use the whole saved translation")
        return self


class StoryTextStyleResponse(BaseModel):
    revision: int = Field(ge=0)
    style_guide: str = Field(max_length=2000)


class LocalTextModelDefaultsResponse(BaseModel):
    base_url: str
    model: str


class TextRevisionPreviewResponse(ChapterIdentityResponse):
    source_version: str
    mode: TextRevisionMode
    provider_id: int = Field(gt=0)
    translation_job_id: int | None
    style_revision: int = Field(ge=0)
    selection: RevisionSelection | None
    original: str
    draft: str
    preview: str
    saved: Literal[False]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    charged_usd: float = Field(ge=0)
