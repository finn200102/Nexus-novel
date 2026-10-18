"""Browser administrator inputs; source definitions are validated by metadata."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    site: str = Field(default='fanfiction', min_length=1, max_length=80, pattern=r'^[a-z][a-z0-9_-]*$')
    query: dict

class CreateCatalogRequest(CatalogRequest):
    name: str = Field(min_length=1, max_length=255)
    schedule: dict | None = None
    schedule_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    enabled: bool = True
    review_token: str | None = Field(None, max_length=4096)
    operation_id: str | None = Field(None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

class UpdateCatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=255)
    query: dict | None = None
    schedule: dict | None = None
    schedule_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    enabled: bool | None = None
    expected_revision: str | None = Field(None, pattern=r'^[0-9a-f]{64}$')
    review_token: str | None = Field(None, max_length=4096)
    operation_id: str | None = Field(None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

class CatalogControlRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: str | None = Field(None, pattern=r'^[0-9a-f]{64}$')
    operation_id: str | None = Field(None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

class CatalogRebindRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: dict
    review_token: str = Field(min_length=1, max_length=4096)
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    operation_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

class CatalogCandidateUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_status: Literal['ignored','matched']

# Response DTOs describe the wire envelope. Extra metadata from independently
# upgraded source adapters is retained, and exclude_unset avoids inventing
# values for optional fields in older metadata responses.
class CatalogWireResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

class CatalogMediaResponse(CatalogWireResponse):
    value: str
    label: str

class CatalogCapabilityResponse(CatalogWireResponse):
    site: str
    name: str
    adapter_version: int
    modes: list[str]
    filters: list[str]
    remote_filters: list[str]
    local_filters: list[str]
    media: list[CatalogMediaResponse] | None = None
    rate_limit: str | None = None
    policy: str | None = None
    source_id: str | None = None
    persisted_site: str | None = None
    plugin_id: str | None = None
    plugin_digest: str | None = None
    plugin_version: str | None = None
    pagination_by_mode: dict[str, bool] | None = None
    on_demand_only: bool | None = None
    limitations: list[str] | None = None

class CatalogCapabilitiesResponse(CatalogWireResponse):
    sources: list[CatalogCapabilityResponse]
    default_site: str
    version: int
    sources_limited: bool | None = None

class CatalogListingMetadataResponse(CatalogWireResponse):
    title: str | None = None

class CatalogCandidateResponse(CatalogWireResponse):
    source_url: str
    id: int | None = None
    site: str | None = None
    title: str | None = None
    author: str | None = None
    source_key: str | None = None
    status: str | None = None
    word_count: int | None = None
    reviews: int | None = None
    favorites: int | None = None
    follows: int | None = None
    updated: str | None = None
    matched: bool | None = None
    skip_reason: str | None = None
    candidate_status: str | None = None
    import_job_id: str | None = None
    listing_metadata: CatalogListingMetadataResponse | None = None
    request_snapshot: dict[str, object] | None = None

class CatalogFilterProvenanceResponse(CatalogWireResponse):
    remote: list[str]
    local: list[str]

class CatalogPreviewResponse(CatalogWireResponse):
    query: dict[str, object]
    source_url: str
    capabilities: CatalogCapabilityResponse
    estimated_pages: int
    preview: list[CatalogCandidateResponse]
    matched_count: int
    warnings: list[str]
    filter_provenance: CatalogFilterProvenanceResponse | None = None
    adapter_version: int | None = None
    review_token: str | None = None

class CatalogProgressResponse(CatalogWireResponse):
    pages_done: int
    next_page: int
    requests_today: int
    items_found: int
    items_added: int
    daily_request_budget: int | None = None
    max_pages_per_run: int | None = None
    estimated_total_pages: int | None = None
    percent: float | None = None
    eta_seconds: int | None = None

class CatalogDefinitionResponse(CatalogWireResponse):
    id: int
    name: str
    site: str
    query: dict[str, object]
    enabled: bool
    schedule_interval_minutes: int | None = None
    schedule: dict[str, object] | None = None
    progress: CatalogProgressResponse | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_job_id: str | None = None
    checkpoint: dict[str, object] | None = None
    adapter_version: int | None = None
    capability_snapshot: dict[str, object] | None = None
    definition_revision: str | None = None
    plugin_state: Literal['ready','review_required','unavailable'] | None = None
    plugin_reason: str | None = None
    control_state: Literal['ready','review_required'] | None = None
    control_reason: str | None = None

class CatalogJobResponse(CatalogWireResponse):
    id: str
    job_type: str
    site: str
    status: str
    progress: float
    results: dict[str, object]
    attempt_count: int
    retryable: bool
    message: str | None = None
    error_code: str | None = None
    retry_cycle: int | None = None

class CatalogCreateResponse(CatalogWireResponse):
    definition: CatalogDefinitionResponse
    job: CatalogJobResponse | None

class CatalogDeleteResponse(CatalogWireResponse):
    deleted: bool
    id: int

class CatalogTaxonomyResponse(CatalogWireResponse):
    display_value: str
    source_value: str
    story_count: int | None = None
    observed_at: str

class CatalogTemplateResponse(CatalogWireResponse):
    id: str
    name: str
    description: str
    site: str
    needs: list[str]
    schedule: dict[str, object] | None
    query: dict[str, object]

class CatalogActiveJobsResponse(CatalogWireResponse):
    items: list[CatalogJobResponse]
    total: int
    offset: int
    limit: int
