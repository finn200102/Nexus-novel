import type { ChapterReadingSummary } from "../../services/chapterService";
export function readingPlaceLabel(summary: ChapterReadingSummary): string {
  const current = summary.current;
  if (!current) return "No saved reading place";
  return `Current place: Chapter ${current.chapter_number}${current.ordinal !== null ? ` · ${current.ordinal} of ${summary.total_chapters} in story` : " · chapter no longer in the current list"} · ${Math.round(current.percent)}%`;
}
export const completedChaptersLabel = (summary: ChapterReadingSummary) => `${summary.completed_chapters} of ${summary.total_chapters} completed chapters recorded`;
