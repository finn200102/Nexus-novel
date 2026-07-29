import apiClient from "./apiClient";

export interface CatalogQuery {
  version?: number; intent?: string; mode: string; media: string; fandom_a: string; fandom_a_id?: number | null; fandom_b: string; crossover: boolean;
  include_genres: string[]; exclude_genres: string[]; rating_min: string; rating_max: string;
  language: string; status: string; min_words: number | null; max_words: number | null;
  min_reviews: number; min_favorites: number; min_follows: number; time_field: string;
  time_range: string; sort: string; limit: number; max_pages: number; custom_urls?: string[]; search_text?: string;
  include_tags?: string[]; exclude_tags?: string[]; content_warnings?: string[]; source_options?: Record<string, unknown>;
}
export interface CatalogCandidate { id?: number; site?: string; title?: string; author?: string; source_url: string; source_key?: string; status?: string; word_count?: number; reviews?: number; favorites?: number; follows?: number; updated?: string; matched?: boolean; skip_reason?: string; candidate_status?: string; import_job_id?: string; listing_metadata?: Record<string, any>; request_snapshot?: Record<string, unknown>; }
export interface CatalogSourceCapability { site: string; name: string; adapter_version: number; modes: string[]; filters: string[]; remote_filters: string[]; local_filters: string[]; media?: { value: string; label: string }[]; rate_limit: string; policy?: string; }
export interface CatalogCapabilities { sources: CatalogSourceCapability[]; default_site: string; version: number; }
export interface CatalogPreview { query: CatalogQuery; source_url: string; capabilities: CatalogSourceCapability; filter_provenance?: { remote: string[]; local: string[] }; adapter_version?: number; estimated_pages: number; preview: CatalogCandidate[]; matched_count: number; warnings: string[]; }
export interface CatalogDefinition { id: number; name: string; site: string; query: CatalogQuery; enabled: boolean; schedule_interval_minutes?: number | null; next_run_at?: string | null; last_run_at?: string | null; last_job_id?: string | null; checkpoint?: Record<string, unknown>; adapter_version?: number; capability_snapshot?: CatalogSourceCapability; }
export interface CatalogJob { id: string; job_type: string; site: string; status: string; progress: number; message?: string; results: Record<string, number>; attempt_count: number; retryable: boolean; error_code?: string; retry_cycle?: number; }
export interface TaxonomyValue { display_value: string; source_value: string; story_count?: number | null; observed_at: string; }

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
  async create(input: { name: string; site: string; query: CatalogQuery; schedule_interval_minutes?: number | null; enabled: boolean }) { return (await apiClient.post("/catalog-scrapes", input)).data as { definition: CatalogDefinition; job: CatalogJob }; },
  async definitions(): Promise<CatalogDefinition[]> { return (await apiClient.get("/catalog-scrapes")).data; },
  async update(id: number, input: Partial<Pick<CatalogDefinition, "name" | "query" | "enabled" | "schedule_interval_minutes">>) {
    return (await apiClient.patch(`/catalog-scrapes/${id}`, input)).data as CatalogDefinition;
  },
  async run(id: number): Promise<CatalogJob> { return (await apiClient.post(`/catalog-scrapes/${id}/run`)).data; },
  async pause(id: number) { return (await apiClient.post(`/catalog-scrapes/${id}/pause`)).data as CatalogDefinition; },
  async resume(id: number) { return (await apiClient.post(`/catalog-scrapes/${id}/resume`)).data as CatalogDefinition; },
  async remove(id: number) { return (await apiClient.delete(`/catalog-scrapes/${id}`)).data; },
  async job(id: string): Promise<CatalogJob> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}`)).data; },
  async candidates(id: string): Promise<CatalogCandidate[]> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}/candidates?limit=100`)).data; },
  async retry(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/retry`)).data; },
  async cancel(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/cancel`)).data; },
  async ignoreCandidate(jobId: string, candidateId: number) {
    return (await apiClient.patch(`/catalog-scrapes/jobs/${jobId}/candidates/${candidateId}`, { candidate_status: "ignored" })).data as CatalogCandidate;
  },
};
