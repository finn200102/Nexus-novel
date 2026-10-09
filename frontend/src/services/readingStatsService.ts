import apiClient from "./apiClient";

export type StatsRange = "week" | "month" | "year" | "all";

export interface DailyStat {
  date: string;
  seconds: number;
  words: number;
  chapters_finished: number;
}

export interface StatsSummary {
  range: StatsRange;
  start: string | null;
  end: string;
  totals: { seconds: number; words: number; chapters_finished: number; stories_finished: number };
  daily: DailyStat[];
  streak: { current: number; longest: number; min_seconds: number };
  top_stories: { novel_id: number; title: string; seconds: number; words: number }[];
  by_site: { site: string; seconds: number }[];
  by_tag: { tag: string; seconds: number }[];
}

export const readingStatsService = {
  async recordReadingTime(novelId: number, chapterId: number, seconds: number, wordsReadEstimate: number) {
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
