"""Explicit private guide capabilities; legacy provider defaults stay text-only."""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator

Capability = Literal['translation', 'companion', 'guide_text', 'guide_portrait']
ImageSize = Literal['1024x1024', '1536x1024', '1024x1536']
ImageQuality = Literal['low', 'medium', 'high']


class ProviderCapabilitiesInput(BaseModel):
    capabilities: list[Capability] | None = Field(None, max_length=4)
    image_model: str | None = Field(None, min_length=1, max_length=255)
    image_price_usd: Decimal = Field(Decimal(0), ge=0, le=100, decimal_places=6)
    image_sizes: list[ImageSize] = Field(default_factory=list, max_length=3)
    image_qualities: list[ImageQuality] = Field(default_factory=list, max_length=3)

    @field_validator('capabilities', 'image_sizes', 'image_qualities')
    @classmethod
    def distinct(cls, value):
        return sorted(set(value)) if value is not None else None


class ProviderCapabilitiesUpdate(BaseModel):
    capabilities: list[Capability] | None = Field(None, max_length=4)
    image_model: str | None = Field(None, min_length=1, max_length=255)
    image_price_usd: Decimal | None = Field(None, ge=0, le=100, decimal_places=6)
    image_sizes: list[ImageSize] | None = Field(None, max_length=3)
    image_qualities: list[ImageQuality] | None = Field(None, max_length=3)


def capabilities(provider):
    declared = getattr(provider, 'capabilities', None)
    return list(declared) if declared is not None else (['translation'] if provider.kind == 'local_translation' else ['translation', 'companion'])


def validate_image_configuration(kind, values):
    declared = values.get('capabilities') or []
    if 'guide_portrait' in declared:
        if kind not in {'local', 'openai_compatible'}:
            raise ValueError('This provider protocol does not support private portrait generation')
        if not values.get('image_model') or not values.get('image_sizes') or not values.get('image_qualities'):
            raise ValueError('Declare an image model, allowed sizes and qualities before enabling portraits')
        if kind != 'local' and not values.get('image_price_microusd'):
            raise ValueError('Set a conservative per-image price ceiling before enabling paid portraits')
    if kind == 'local_translation' and any(value != 'translation' for value in declared):
        raise ValueError('Local translation providers support translation only')


class ReaderProviderResponse(BaseModel):
    id: int
    name: str
    kind: str
    base_url: str
    model: str
    has_key: bool
    enabled: bool
    supported_languages: list[str]
    capabilities: list[Capability]
    input_price: float
    output_price: float
    budget_usd: float
    used_usd: float
    reserved_usd: float
    image_model: str | None
    image_price_usd: float
    image_sizes: list[ImageSize]
    image_qualities: list[ImageQuality]


class StoryPermissionResponse(BaseModel):
    translation: bool | None
    companion: bool | None
    ao3_consent: bool
    is_ao3: bool
    local: bool
    portrait: bool
    portrait_ao3_consent: bool
    portrait_requires_review: bool = False
