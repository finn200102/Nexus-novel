import apiClient from "./apiClient";
import type { ActivityDay, ActivityEvent } from "../types/activity";

export interface OperationsSummary {
  library_id: number;
  followed_stories: number;
  reading_stories: number;
  unread_updates: number;
  source_failures: number;
  downloads: {
    queued: number;
    running: number;
    completed: number;
    failed: number;
    cancelled: number;
  };
  metadata_server: {
    status: "online" | "degraded" | "offline";
    detail: string | null;
    checked_at: string;
  };
  metadata_jobs: {
    queued: number;
    running: number;
    completed: number;
    failed: number;
    cancelled: number;
  };
  source_health: Record<string, number>;
  refresh_schedules: number;
  generated_at: string;
}

export interface RefreshSchedule {
  id: string;
  site: string | null;
  interval_minutes: number;
  batch_size: number;
  enabled: boolean;
  next_run_at: string;
}

export interface MetadataJob {
  id: string;
  job_type: string;
  site: string;
  status: string;
  message: string | null;
  attempt_count: number;
  max_attempts: number;
  retryable: boolean;
  error_code: string | null;
  results: Record<string, unknown>;
}

export const activityService = {
  async getFeed(libraryId: number, unreadOnly = false): Promise<ActivityEvent[]> {
    const response = await apiClient.get(`/activity/feed?library_id=${libraryId}&unread_only=${unreadOnly}`);
    return response.data;
  },
  async getCalendar(libraryId: number, startDate?: string, endDate?: string): Promise<ActivityDay[]> {
    const params = new URLSearchParams({ library_id: String(libraryId) });
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const response = await apiClient.get(`/activity/calendar?${params.toString()}`);
    return response.data;
  },
  async getOperationsSummary(libraryId: number): Promise<OperationsSummary> {
    const response = await apiClient.get(`/operations/summary?library_id=${libraryId}`);
    return response.data;
  },
  async getRefreshSchedules(): Promise<RefreshSchedule[]> {
    const response = await apiClient.get("/operations/schedules");
    return response.data;
  },
  async createRefreshSchedule(input: Pick<RefreshSchedule, "site" | "interval_minutes" | "batch_size" | "enabled">): Promise<RefreshSchedule> {
    const response = await apiClient.post("/operations/schedules", input);
    return response.data;
  },
  async updateRefreshSchedule(id: string, input: Partial<Pick<RefreshSchedule, "interval_minutes" | "batch_size" | "enabled">>): Promise<RefreshSchedule> {
    const response = await apiClient.patch(`/operations/schedules/${id}`, input);
    return response.data;
  },
  async deleteRefreshSchedule(id: string): Promise<void> {
    await apiClient.delete(`/operations/schedules/${id}`);
  },
  async getMetadataJobs(status = "failed"): Promise<MetadataJob[]> {
    const response = await apiClient.get(`/operations/metadata-jobs?status=${encodeURIComponent(status)}&limit=50`);
    return response.data.data;
  },
  async retryMetadataJob(id: string): Promise<MetadataJob> {
    const response = await apiClient.post(`/operations/metadata-jobs/${id}/retry`);
    return response.data;
  },
  async cancelMetadataJob(id: string): Promise<void> {
    await apiClient.delete(`/operations/metadata-jobs/${id}`);
  },
};
