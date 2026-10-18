from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.schemas.translation_identity import SelectedTranslationChapterIdentity


class TranslationBatchSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter_identities: list[SelectedTranslationChapterIdentity] | None = Field(None,max_length=200)
    chapter_ids: list[StrictInt] = Field(min_length=1, max_length=200)
    provider_id: StrictInt = Field(gt=0)
    language: str = Field(pattern=r'^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$', max_length=20)
    external_consent: bool = False
    ao3_consent: bool = False

    @model_validator(mode='after')
    def complete_capture(self):
        if self.chapter_identities is not None:
            ids=[item.chapter_id for item in self.chapter_identities]
            if len(ids)!=len(set(ids)) or set(ids)!=set(self.chapter_ids):
                raise ValueError('Capture exactly one original identity for every selected chapter ID')
            if any(any(getattr(item,name) is None for name in ('expected_chapter_key','expected_manifest_epoch','expected_manifest_revision','expected_content_version')) for item in self.chapter_identities):
                raise ValueError('Capture all four original chapter identity fields')
        return self

    @field_validator('chapter_ids')
    @classmethod
    def distinct_positive(cls, values):
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError('Select distinct positive chapter IDs')
        return values


class TranslationBatchSubmission(TranslationBatchSelection):
    review_token: str = Field(min_length=1, max_length=2000)


class TranslationPermissionPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    translation: bool
    ao3_consent: bool = False
