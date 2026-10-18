import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PronunciationRule(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    spoken: str = Field(min_length=1, max_length=160)
    model_config = ConfigDict(extra="forbid")

    @field_validator("source", "spoken")
    @classmethod
    def plain_literal(cls, value):
        value = value.strip()
        if not value or any(unicodedata.category(char) in {"Cc", "Cs", "Cf"} or char in "<>" for char in value):
            raise ValueError("Use nonempty plain text without markup or control characters")
        return value


class PronunciationWrite(BaseModel):
    expected_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=128)
    rules: list[PronunciationRule] = Field(default_factory=list, max_length=64)
    inherit_account: bool = True
    model_config = ConfigDict(extra="forbid")

    @field_validator("rules")
    @classmethod
    def unique_sources(cls, values):
        if len({rule.source for rule in values}) != len(values):
            raise ValueError("Each exact source term may appear only once")
        return values
