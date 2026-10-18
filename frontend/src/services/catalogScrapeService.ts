import apiClient from "./apiClient";
import type {CatalogCandidateResponse,CatalogCapabilityResponse,CatalogCapabilitiesResponse,CatalogPreviewResponse,CatalogDefinitionResponse,CatalogJobResponse,CatalogTaxonomyResponse,CreateCatalogRequest,UpdateCatalogRequest,CatalogDeleteResponse,CatalogControlRequest,CatalogCreateResponse,CatalogActiveJobsResponse} from "../generated/api";

export interface CatalogQuery {
  version?: number; intent?: string; mode: string; media: string; fandom_a: string; fandom_a_id?: number | null; fandom_b: string; crossover: boolean;
  include_genres: string[]; exclude_genres: string[]; rating_min: string; rating_max: string;
  language: string; status: string; min_words: number | null; max_words: number | null;
  min_reviews: number; min_favorites: number; min_follows: number; time_field: string;
  time_range: string; sort: string; limit: number; max_pages: number; custom_urls?: string[]; search_text?: string;
  include_tags?: string[]; exclude_tags?: string[]; content_warnings?: string[]; source_options?: Record<string, unknown>;
  run_mode?: "scheduled_check" | "backfill"; daily_request_budget?: number | null;
  max_pages_per_run?: number | null; top_n?: number | null;
}
export type CatalogCandidate = CatalogCandidateResponse;
export type CatalogSourceCapability = CatalogCapabilityResponse;
export type CatalogCapabilities = CatalogCapabilitiesResponse;
// CatalogQuery is the validated legacy editor model, separate from freeform
// adapter wire metadata. Pick retains known fields despite the wire extras.
export type CatalogPreview = Pick<CatalogPreviewResponse,"source_url"|"capabilities"|"filter_provenance"|"adapter_version"|"estimated_pages"|"preview"|"matched_count"|"warnings"|"review_token"> & {query:CatalogQuery};
export type CatalogDefinition = Pick<CatalogDefinitionResponse,"id"|"name"|"site"|"enabled"|"schedule_interval_minutes"|"schedule"|"progress"|"next_run_at"|"last_run_at"|"last_job_id"|"checkpoint"|"adapter_version"|"capability_snapshot"|"definition_revision"|"plugin_state"|"plugin_reason"|"control_state"|"control_reason"> & {query:CatalogQuery};
export type CatalogJob = CatalogJobResponse;
export type TaxonomyValue = CatalogTaxonomyResponse;

export const catalogScrapeService = {
  async capabilities(): Promise<CatalogCapabilities> { return (await apiClient.get("/catalog-scrapes/capabilities")).data; },
  async sourceCapabilities(site: string): Promise<CatalogSourceCapability> { return (await apiClient.get(`/catalog-scrapes/capabilities/${site}`)).data; },
  async taxonomies(site: string, type: string, query?: string, offset = 0): Promise<TaxonomyValue[]> {
    return (await apiClient.get(`/catalog-scrapes/taxonomies/${site}/${type}`, { params: { query, limit: 50, offset } })).data;
  },
  // A preview is an interactive, disposable request.  The server gives its
  // source request a 12 second budget, so never let the browser wait behind a
  // longer general API timeout or an automatic retry cycle.
  async preview(site: string, query: CatalogQuery): Promise<CatalogPreview> {
    return (await apiClient.post("/catalog-scrapes/preview", { site, query }, { timeout: 13_500 })).data;
  },
  async create(input: Omit<CreateCatalogRequest,"query"> & {query:CatalogQuery}) { return (await apiClient.post("/catalog-scrapes", input)).data as { definition: CatalogDefinition; job: CatalogCreateResponse["job"] }; },
  async definitions(): Promise<CatalogDefinition[]> { return (await apiClient.get("/catalog-scrapes")).data; },
  async update(id: number, input: Omit<UpdateCatalogRequest,"query"> & {query?:CatalogQuery}) {
    return (await apiClient.patch(`/catalog-scrapes/${id}`, input)).data as CatalogDefinition;
  },
  async definition(id:number):Promise<CatalogDefinition> { return (await apiClient.get(`/catalog-scrapes/${id}`)).data; },
  async activeJobs(id:number,offset=0,limit=50):Promise<CatalogActiveJobsResponse> { return (await apiClient.get(`/catalog-scrapes/${id}/active-jobs`,{params:{offset,limit}})).data; },
  async run(id: number, control?:CatalogControlRequest): Promise<CatalogJob> { return (await apiClient.post(`/catalog-scrapes/${id}/run`,control)).data; },
  async pause(id: number,control?:CatalogControlRequest) { return (await apiClient.post(`/catalog-scrapes/${id}/pause`,control)).data as CatalogDefinition; },
  async resume(id: number,control?:CatalogControlRequest) { return (await apiClient.post(`/catalog-scrapes/${id}/resume`,control)).data as CatalogDefinition; },
  async remove(id: number,control?:CatalogControlRequest):Promise<CatalogDeleteResponse> { return (await apiClient.delete(`/catalog-scrapes/${id}`,control?{data:control}:undefined)).data; },
  async job(id: string): Promise<CatalogJob> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}`)).data; },
  async candidates(id: string,offset=0,limit=100): Promise<CatalogCandidate[]> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}/candidates?limit=${limit}&offset=${offset}`)).data; },
  async retry(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/retry`)).data; },
  async cancel(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/cancel`)).data; },
  async ignoreCandidate(jobId: string, candidateId: number) {
    return (await apiClient.patch(`/catalog-scrapes/jobs/${jobId}/candidates/${candidateId}`, { candidate_status: "ignored" })).data as CatalogCandidate;
  },
};
