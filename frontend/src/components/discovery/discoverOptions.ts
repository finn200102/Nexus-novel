import type { DiscoveredNovel, DiscoveryFilters } from "../../types/discovery";
import { siteLabel } from "../story/storyModel";

/** Length presets map onto min/max word counts. */
export const LENGTHS = [
  { value: "", label: "Any length", min: "", max: "" },
  { value: "short", label: "Short (under 50k words)", min: "", max: "50000" },
  { value: "medium", label: "Medium (50k–200k)", min: "50000", max: "200000" },
  { value: "long", label: "Long (200k–500k)", min: "200000", max: "500000" },
  { value: "epic", label: "Epic (over 500k)", min: "500000", max: "" },
];

export const COMMON_GENRES = ["Action", "Adventure", "Comedy", "Drama", "Fantasy", "Horror", "LitRPG", "Mystery", "Romance", "Sci-fi", "Slice of life", "Thriller"];

export const lengthValue = (filters: DiscoveryFilters) =>
  LENGTHS.find((length) => length.min === filters.minWordCount && length.max === filters.maxWordCount)?.value ?? "custom";

const formatWords = (words: number | null) => {
  if (!words) return null;
  if (words >= 1_000_000) return `${(words / 1_000_000).toFixed(1).replace(/\.0$/, "")}M words`;
  if (words >= 1000) return `${Math.round(words / 1000)}k words`;
  return `${words} words`;
};

/** "Royal Road · 312k words · Ongoing" (missing values are left out). */
export const metaLine = (novel: DiscoveredNovel) =>
  [siteLabel(novel.novel_site), formatWords(novel.word_count), novel.status].filter(Boolean).join(" · ");

