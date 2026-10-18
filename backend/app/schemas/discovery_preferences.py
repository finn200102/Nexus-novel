from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiscoveryPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(default_factory=list, max_length=20)
    fandoms: list[str] = Field(default_factory=list, max_length=20)
    genres: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=10)
    exclude_tags: list[str] = Field(default_factory=list, max_length=20)
    exclude_fandoms: list[str] = Field(default_factory=list, max_length=20)
    exclude_genres: list[str] = Field(default_factory=list, max_length=20)
    exclude_authors: list[str] = Field(default_factory=list, max_length=20)
    exclude_words: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("*", mode="after")
    @classmethod
    def clean(cls, values):
        result, seen = [], set()
        for value in values:
            value = " ".join(value.split())
            if not value or len(value) > 100:
                raise ValueError("Each preference needs 1–100 characters")
            if value.casefold() not in seen:
                result.append(value); seen.add(value.casefold())
        return result


class DiscoveryPreferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=128)
    values: DiscoveryPreferences
