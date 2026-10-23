import apiClient from "./apiClient";
import type { PreferenceValues } from "./readerPreferenceSync";

export type UserDataExport = {
  format: "nexus-user-export";
  version: number;
  exported_at: string;
  libraries: unknown[];
  saved_searches: unknown[];
  smart_shelves?: unknown[];
  reader_preferences?: PreferenceValues | null;
};

export type NovelImportStatus = "created" | "linked" | "failed" | "conflict";

export type UserDataImportNovel = {
  url: string | null;
  novel_id?: number;
  portable_link_id?: number;
  original_status?: "unavailable" | "backup_review";
  title: string | null;
  status: NovelImportStatus;
  reason: string | null;
  follow_state: "updated" | "unchanged" | null;
  progress: "applied" | "unchanged" | "kept_local" | "review_required" | null;
  reading_review_id?: number | null;
  history: { added: number; updated: number; unchanged: number; kept_local?: number };
  reading_runs?: { added: number; unchanged: number; kept_local: number; events_added: number; events_unchanged: number; inferred_events: number; current_restored: number };
  annotations: { added: number; duplicate: number; deferred: number };
  reader_preferences?: "applied" | "unchanged" | "kept_local" | null;
};

export type UserDataImportReport = {
  format: string;
  version: number;
  summary: Record<string, number>;
  libraries: { name: string; status: "created" | "existing"; novels: UserDataImportNovel[] }[];
  saved_searches: { name: string; status: "created" | "unchanged" | "conflict" }[];
  smart_shelves?: { name: string; status: "created" | "unchanged" | "conflict" | "invalid" | "limit_reached"; needs_review?: boolean }[];
  reader_preferences?: "applied" | "unchanged" | "kept_local" | null;
  discovery_preferences?: "applied" | "unchanged" | "kept_local" | null;
};

// Importing may start metadata scrapes for many novels, which can take longer
// than the default request timeout.
const IMPORT_TIMEOUT_MS = 120_000;

export const userDataService = {
  async exportData(): Promise<UserDataExport> {
    return (await apiClient.get("/me/export")).data;
  },
  async importData(document: unknown): Promise<UserDataImportReport> {
    return (await apiClient.post("/me/import", document, { timeout: IMPORT_TIMEOUT_MS })).data;
  },
  async exportFullBackup(library?:string): Promise<Blob> {
    return (await apiClient.get("/me/backup", { responseType: "blob", timeout: IMPORT_TIMEOUT_MS,params:library?{library}:undefined })).data;
  },
  async importFullBackup(file: File): Promise<UserDataImportReport> {
    return (await apiClient.post("/me/backup/import",file,{timeout:IMPORT_TIMEOUT_MS,headers:{"Content-Type":"application/zip"}})).data;
  },
};
