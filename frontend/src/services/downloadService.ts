import apiClient from "./apiClient";
import type { DownloadJob } from "../types/activity";

export const downloadService = {
  async listJobs(libraryId?: number): Promise<DownloadJob[]> {
    const query = libraryId ? `?library_id=${libraryId}` : "";
    const response = await apiClient.get(`/downloads/jobs${query}`);
    return response.data;
  },
  async queue(libraryId: number, novelId: number, count: number): Promise<DownloadJob[]> {
    const response = await apiClient.post("/downloads/jobs", { library_id: libraryId, novel_id: novelId, count });
    return response.data;
  },
  async retry(jobId: number): Promise<DownloadJob> {
    const response = await apiClient.post(`/downloads/jobs/${jobId}/retry`);
    return response.data;
  },
  async cancel(jobId: number, reason = "Cancelled by user"): Promise<DownloadJob> {
    const response = await apiClient.post(`/downloads/jobs/${jobId}/cancel`, { reason });
    return response.data;
  },
};
