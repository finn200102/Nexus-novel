import apiClient from "./apiClient";
import type { ActivityDay, ActivityEvent } from "../types/activity";

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
};
