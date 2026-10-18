"""Explicit reviewed private-generation contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.reader_provider_usage import ReaderProviderModelSnapshot


class GuideInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    retry_job_id: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    provider_id: int = Field(gt=0, le=2147483647, strict=True)
    through_chapter: int | None = Field(default=None, ge=-2147483648, le=2147483647, strict=True)
    kind: Literal['guide', 'portrait'] = 'guide'
    external_consent: bool = False
    ao3_consent: bool = False
    image_size: Literal['1024x1024', '1536x1024', '1024x1536'] = '1024x1024'
    image_quality: Literal['low', 'medium', 'high'] = 'medium'
    portrait_subject: str | None = Field(default=None, min_length=1, max_length=120)


class GuideCreate(GuideInput):
    review_token: str = Field(min_length=1, max_length=4096)
    operation_id: str = Field(min_length=1, max_length=128)


class GuideAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1, strict=True)
    operation_id: str = Field(min_length=1, max_length=128)


class GuideProviderSnapshot(ReaderProviderModelSnapshot):
    id: int
    name: str
    image_size: Literal['1024x1024', '1536x1024', '1024x1536']
    image_quality: Literal['low', 'medium', 'high']


class GuideRetry(GuideAction):
    review_token: str | None = Field(default=None, min_length=1, max_length=4096)


class GuidePreview(BaseModel):
    review_token: str
    expires_at: str
    proof_fingerprint: str
    reading_run_key: str | None
    through_chapter: int | None
    chapter_count: int
    block_count: int
    steps: int
    estimated_max_microusd: int
    retry_estimated_max_microusd: int | None
    retry_blocked_reason: str | None
    reuse_job_id: int | None
    reuse_status: Literal['queued', 'processing', 'completed', 'canceled', 'needs_review', 'failed'] | None
    provider_id: int
    kind: Literal['guide', 'portrait']
    warnings: list[str]
    provider_snapshot: GuideProviderSnapshot


class GuideCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter: int = Field(ge=-2147483648, le=2147483647, strict=True)
    block_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=500)


class GuideClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    certainty: Literal['observed', 'interpretation', 'insufficient']
    citations: list[GuideCitation] = Field(min_length=1, max_length=8)


class GuideAppearance(GuideClaim):
    text: str = Field(min_length=1, max_length=1500)


class GuideCharacter(GuideClaim):
    appearance: GuideAppearance | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1500)


class GuideRelationship(GuideClaim):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1500)


class GuideLocation(GuideClaim):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1500)


class GuideGlossary(GuideClaim):
    term: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=1500)


class GuideRecap(GuideClaim):
    text: str = Field(min_length=1, max_length=3000)


class GuideResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    characters: list[GuideCharacter] = Field(max_length=30)
    relationships: list[GuideRelationship] = Field(max_length=30)
    locations: list[GuideLocation] = Field(max_length=30)
    glossary: list[GuideGlossary] = Field(max_length=30)
    recap: GuideRecap | None
    citations: list[GuideCitation] = Field(min_length=1, max_length=8)


class GuidePortraitContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: str = Field(min_length=1, max_length=120)


class GuideCitationResponse(GuideCitation):
    """Server-issued identity; this schema is never a provider output contract."""
    chapter_key: str = Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
    source_version: str = Field(pattern=r'^[a-f0-9]{64}$')


class GuideAppearanceResponse(GuideAppearance):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideCharacterResponse(GuideCharacter):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)
    appearance: GuideAppearanceResponse | None = None


class GuideRelationshipResponse(GuideRelationship):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideLocationResponse(GuideLocation):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideGlossaryResponse(GuideGlossary):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideRecapResponse(GuideRecap):
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideResultResponse(GuideResult):
    characters: list[GuideCharacterResponse] = Field(max_length=30)
    relationships: list[GuideRelationshipResponse] = Field(max_length=30)
    locations: list[GuideLocationResponse] = Field(max_length=30)
    glossary: list[GuideGlossaryResponse] = Field(max_length=30)
    recap: GuideRecapResponse | None
    citations: list[GuideCitationResponse] = Field(min_length=1, max_length=8)


class GuideArtifact(BaseModel):
    id: int
    kind: Literal['guide', 'portrait']
    content: GuideResultResponse | GuidePortraitContent
    citations: list[GuideCitationResponse]
    created_at: str | None
    media_url: str | None


class GuideJob(BaseModel):
    identity_review_required: bool = False
    retry_input: GuideInput
    id: int
    revision: int
    status: Literal['queued', 'processing', 'completed', 'canceled', 'needs_review', 'failed']
    kind: Literal['guide', 'portrait']
    provider_id: int
    reading_run_key: str
    through_chapter: int | None
    completed_steps: int
    total_steps: int
    error_code: str | None
    error: str | None
    charged_microusd: int
    reserved_microusd: int
    created_at: str | None
    updated_at: str | None
    artifacts: list[GuideArtifact]


class GuideState(BaseModel):
    portrait_bytes: int
    total: int
    offset: int
    limit: int
    jobs: list[GuideJob]
    artifacts: list[GuideArtifact]
    through_chapter: int | None
    reading_run_key: str | None
