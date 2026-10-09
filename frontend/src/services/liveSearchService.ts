import apiClient from "./apiClient";

export interface LiveResult {
  id: number | null;
  metadata_id: number | null;
  title: string;
  author: string | null;
  url?: string;
  source_url: string;
  site?: string | null;
  novel_site?: string | null;
  description: string | null;
  img_url: string | null;
  word_count: number | null;
  chapter_count: number | null;
  status: string | null;
  sources: Array<"live" | "local">;
}

export interface SiteError {
  site: string;
  code: string;
  message: string;
}

export interface LiveResponse {
  page: number;
  results: LiveResult[];
  errors: SiteError[];
}

export type ImportItemStatus = "queued" | "running" | "linked" | "duplicate" | "unsupported" | "failed" | "restricted";

export interface ImportJob {
  id: number;
  library_id: number;
  source: string;
  status: string;
  total_items: number;
  counts: Partial<Record<ImportItemStatus, number>>;
  error: string | null;
  created_at: string;
  items?: Array<{ position: number; url: string | null; label: string | null; title: string | null; status: ImportItemStatus; reason: string | null }>;
}

// FastAPI expects repeated sites=a&sites=b rather than axios' sites[]=a.
const repeated = (params: Record<string, string | number | string[]>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item));
  }
  return search.toString();
};

const fileToBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export const liveSearchService = {
  async search(q: string, sites: string[], page = 1): Promise<LiveResponse> {
    const response = await apiClient.get<LiveResponse>(`/discovery/live?${repeated({ q, sites, page })}`, { timeout: 60000 });
    return response.data;
  },

  async browse(site: string, feed: string, page = 1): Promise<LiveResponse> {
    const response = await apiClient.get<LiveResponse>(`/discovery/live/browse?${repeated({ site, feed, page })}`, { timeout: 60000 });
    return response.data;
  },

  async importUrls(libraryId: number, text: string, source: "url_list" | "rr_list"): Promise<ImportJob> {
    return (await apiClient.post<ImportJob>("/imports/urls", { library_id: libraryId, text, source })).data;
  },

  async importEpubs(libraryId: number, files: File[]): Promise<ImportJob> {
    const encoded = await Promise.all(files.map(async (file) => ({ name: file.name, data_base64: await fileToBase64(file) })));
    return (await apiClient.post<ImportJob>("/imports/epub", { library_id: libraryId, files: encoded }, { timeout: 120000 })).data;
  },

  async importList(libraryId: number, source: "ao3_bookmarks" | "ffn_favorites", user: string): Promise<ImportJob> {
    return (await apiClient.post<ImportJob>("/imports/list", { library_id: libraryId, source, user })).data;
  },

  async jobs(): Promise<ImportJob[]> {
    return (await apiClient.get<ImportJob[]>("/imports")).data;
  },

  async job(id: number): Promise<ImportJob> {
    return (await apiClient.get<ImportJob>(`/imports/${id}`)).data;
  },

  async cancel(id: number): Promise<ImportJob> {
    return (await apiClient.post<ImportJob>(`/imports/${id}/cancel`)).data;
  },
};
