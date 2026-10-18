from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Typography(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["app", "paper", "sepia", "night", "black"] | None = None
    font: Literal["literata", "source-serif", "atkinson", "opendyslexic", "system"] | None = None
    fontSize: int | None = Field(None, ge=14, le=28)
    lineHeight: Literal[1.4, 1.6, 1.9] | None = None
    width: Literal["narrow", "medium", "wide"] | None = None
    letterSpacing: Literal[0, 0.05, 0.1] | None = None
    wordSpacing: Literal[0, 0.1, 0.2] | None = None
    paragraphStyle: Literal["spaced", "indented"] | None = None
    justify: bool | None = None
    hyphenate: bool | None = None


class PreferenceValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    typography: Typography | None = None
    layout: Literal["scroll", "paged"] | None = None
    authorNotes: Literal["collapsed", "shown", "hidden"] | None = None
    shortcuts: bool | None = None


class PreferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    values: PreferenceValues




class TypographyResponse(Typography):
    model_config=ConfigDict(extra='allow')


class ReaderPreferenceValuesResponse(PreferenceValues):
    model_config=ConfigDict(extra='allow')
    typography:TypographyResponse|None=None


class ReaderPreferenceResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    scope:str
    revision:int
    values:ReaderPreferenceValuesResponse
