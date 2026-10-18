from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class StoryTranslationExport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    translation_job_ids: list[StrictInt] = Field(min_length=1, max_length=200)

    @field_validator('translation_job_ids')
    @classmethod
    def unique_positive_ids(cls, values):
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError('Select distinct positive translation variant IDs')
        return values
