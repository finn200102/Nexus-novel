import apiClient from "./apiClient";

export interface CatalogQuery {
  mode: string; media: string; fandom_a: string; fandom_a_id?: number | null; fandom_b: string; crossover: boolean;
  include_genres: string[]; exclude_genres: string[]; rating_min: string; rating_max: string;
  language: string; status: string; min_words: number | null; max_words: number | null;
  min_reviews: number; min_favorites: number; min_follows: number; time_field: string;
  time_range: string; sort: string; limit: number; max_pages: number; custom_urls?: string[];
}
export interface CatalogCandidate { id?: number; title?: string; author?: string; source_url: string; status?: string; word_count?: number; reviews?: number; favorites?: number; follows?: number; updated?: string; matched?: boolean; skip_reason?: string; candidate_status?: string; import_job_id?: string; listing_metadata?: Record<string, any>; }
export interface CatalogPreview { query: CatalogQuery; source_url: string; capabilities: { modes: string[]; filters: string[]; remote_filters: string[]; local_filters: string[]; media?: { value: string; label: string }[]; rate_limit: string }; estimated_pages: number; preview: CatalogCandidate[]; matched_count: number; warnings: string[]; }
export interface CatalogDefinition { id: number; name: string; site: string; query: CatalogQuery; enabled: boolean; schedule_interval_minutes?: number | null; next_run_at?: string | null; last_job_id?: string | null; }
export interface CatalogJob { id: string; job_type: string; site: string; status: string; progress: number; message?: string; results: Record<string, number>; attempt_count: number; retryable: boolean; error_code?: string; retry_cycle?: number; }
export interface TaxonomyValue { display_value: string; source_value: string; story_count?: number | null; observed_at: string; }

export const catalogScrapeService = {
  async capabilities() { return (await apiClient.get("/catalog-scrapes/capabilities")).data; },
  async taxonomies(site: string, type: string): Promise<TaxonomyValue[]> { return (await apiClient.get(`/catalog-scrapes/taxonomies/${site}/${type}`)).data; },
  // A preview is an interactive, disposable request.  The server gives its
  // source request a 12 second budget, so never let the browser wait behind a
  // longer general API timeout or an automatic retry cycle.
  async preview(site: string, query: CatalogQuery): Promise<CatalogPreview> {
    return (await apiClient.post("/catalog-scrapes/preview", { site, query }, { timeout: 13_500 })).data;
  },
  async create(input: { name: string; site: string; query: CatalogQuery; schedule_interval_minutes?: number | null; enabled: boolean }) { return (await apiClient.post("/catalog-scrapes", input)).data as { definition: CatalogDefinition; job: CatalogJob }; },
  async definitions(): Promise<CatalogDefinition[]> { return (await apiClient.get("/catalog-scrapes")).data; },
  async run(id: number): Promise<CatalogJob> { return (await apiClient.post(`/catalog-scrapes/${id}/run`)).data; },
  async pause(id: number) { return (await apiClient.post(`/catalog-scrapes/${id}/pause`)).data as CatalogDefinition; },
  async resume(id: number) { return (await apiClient.post(`/catalog-scrapes/${id}/resume`)).data as CatalogDefinition; },
  async remove(id: number) { return (await apiClient.delete(`/catalog-scrapes/${id}`)).data; },
  async job(id: string): Promise<CatalogJob> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}`)).data; },
  async candidates(id: string): Promise<CatalogCandidate[]> { return (await apiClient.get(`/catalog-scrapes/jobs/${id}/candidates?limit=100`)).data; },
  async retry(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/retry`)).data; },
  async cancel(id: string) { return (await apiClient.post(`/catalog-scrapes/jobs/${id}/cancel`)).data; },
};
