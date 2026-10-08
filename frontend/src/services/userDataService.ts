import apiClient from "./apiClient";

export type UserDataExport = {
  format: "nexus-user-export";
  version: number;
  exported_at: string;
  libraries: unknown[];
  saved_searches: unknown[];
};

export type NovelImportStatus = "created" | "linked" | "failed";

export type UserDataImportNovel = {
  url: string;
  title: string | null;
  status: NovelImportStatus;
  reason: string | null;
  follow_state: "updated" | "unchanged" | null;
  progress: "applied" | "unchanged" | null;
  history: { added: number; updated: number; unchanged: number };
  annotations: { added: number; duplicate: number; deferred: number };
};

export type UserDataImportReport = {
  format: string;
  version: number;
  summary: Record<string, number>;
  libraries: { name: string; status: "created" | "existing"; novels: UserDataImportNovel[] }[];
  saved_searches: { name: string; status: "created" | "unchanged" | "conflict" }[];
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
};
