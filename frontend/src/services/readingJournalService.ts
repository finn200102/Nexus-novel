import apiClient from "./apiClient";
import type { ReadingJournalEventResponse, ReadingJournalPageResponse, ReadingRunDrop, ReadingRunProgressResponse, ReadingRunResponse, ReadingRunStateResponse } from "../generated/api";
export type ReadingRunProgress = ReadingRunProgressResponse;
export type ReadingRun = ReadingRunResponse;
export type ReadingRunsPage = ReadingRunStateResponse;
export type ReadingJournalEntry = ReadingJournalEventResponse;
export type ReadingJournalPage = ReadingJournalPageResponse;
export type ReadingRunAction = "start" | "finish" | "drop";
export type ReadingRunChange = ReadingRunDrop;
/** Operation identity also works on household HTTP origins without crypto.randomUUID. */
export const readingJournalOperationId = () => {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
export const readingJournalService = {
  runs: async (novelId: number, offset = 0, limit = 20): Promise<ReadingRunsPage> =>
    (await apiClient.get(`/reading/stories/${novelId}/runs`, { params: { offset, limit } })).data,
  journal: async (novelId: number, offset = 0, limit = 20): Promise<ReadingJournalPage> =>
    (await apiClient.get("/reading/journal", { params: { novel_id: novelId, offset, limit } })).data,
  change: async (novelId: number, action: ReadingRunAction, value: ReadingRunChange): Promise<ReadingRunsPage> =>
    (await apiClient.post(`/reading/stories/${novelId}/runs/${action}`, value)).data,
};
