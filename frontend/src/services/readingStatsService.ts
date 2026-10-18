import apiClient from "./apiClient";

import type { CalendarReviewMonthResponse, CalendarYearReviewResponse, DailyStatResponse, GoalWrite, ReadingGoalResponse, ReadingTimeResponse, StatsSummaryResponse } from "../generated/api";

export type StatsRange = StatsSummaryResponse["range"];
export type DailyStat = DailyStatResponse;
export type StatsSummary = StatsSummaryResponse;
export type ReadingGoal = ReadingGoalResponse;
// UI writes explicitly include the new target; the API also permits defaults.
export type ReadingGoalWrite = GoalWrite & { values: Required<GoalWrite["values"]> };
export type CalendarReviewMonth = CalendarReviewMonthResponse;
export type CalendarYearReview = CalendarYearReviewResponse;

export const readingStatsService = {
  async getCalendarReview(year: number): Promise<CalendarYearReview> { return (await apiClient.get(`/stats/review/${year}`)).data; },
  async getGoal(year: number): Promise<ReadingGoal> { return (await apiClient.get(`/stats/goals/${year}`)).data; },
  async saveGoal(year: number, value: ReadingGoalWrite): Promise<ReadingGoal> { return (await apiClient.put(`/stats/goals/${year}`, value)).data; },
  async recordReadingTime(novelId: number, chapterId: number, seconds: number, wordsReadEstimate: number): Promise<ReadingTimeResponse> {
    const response = await apiClient.post("/stats/reading-time", {
      novel_id: novelId,
      chapter_id: chapterId,
      seconds,
      words_read_estimate: wordsReadEstimate,
    });
    return response.data;
  },
  async getSummary(range: StatsRange): Promise<StatsSummary> {
    const response = await apiClient.get("/stats/summary", { params: { range } });
    return response.data;
  },
};
