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
};
