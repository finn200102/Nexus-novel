from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ReaderProviderModelSnapshot(BaseModel):
    kind: str
    base_url: str
    model: str
    input_price: str | None
    output_price: str | None
    capabilities: list[str] | None = None
    image_model: str | None = None
    image_price_microusd: int = 0
    image_sizes: list[str] = Field(default_factory=list)
    image_qualities: list[str] = Field(default_factory=list)


class ReaderProviderAccountingResponse(BaseModel):
    budget_microusd: int
    used_microusd: int
    reserved_microusd: int


class ReaderProviderRequestResponse(BaseModel):
    request_key: str
    provider_id: int
    status: Literal['pending', 'unknown', 'completed', 'reconciled', 'legacy_unknown']
    revision: int
    reserved_microusd: int
    actual_microusd: int | None
    input_tokens: int | None
    output_tokens: int | None
    model_snapshot: ReaderProviderModelSnapshot
    created_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
    can_reconcile: bool
    translation_job_id: int | None
    translation_block_index: int | None
    purpose: Literal['guide_extract', 'guide_synthesize', 'guide_portrait'] | None = None
    job_key: str | None = None
    item_key: str | None = None
    retry_generation: int | None = None


class ReaderProviderRequestsPage(BaseModel):
    items: list[ReaderProviderRequestResponse]
    total: int
    offset: int
    limit: int
    accounting: ReaderProviderAccountingResponse


class ReaderProviderReconcileInput(BaseModel):
    expected_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=128)
    actual_microusd: int = Field(ge=0, le=100_000_000_000, strict=True)


class ReaderProviderReconcileResponse(BaseModel):
    item: ReaderProviderRequestResponse
    accounting: ReaderProviderAccountingResponse


class ReaderProviderUsageConflict(BaseModel):
    code: Literal['request_changed', 'request_inflight', 'request_resolved', 'operation_id_reused']
    message: str
    current: ReaderProviderRequestResponse


class ReaderProviderUsageConflictResponse(BaseModel):
    detail: ReaderProviderUsageConflict
