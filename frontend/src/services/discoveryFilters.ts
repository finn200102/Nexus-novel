import { DiscoveryFilters } from "../types/discovery";

export const EMPTY_DISCOVERY_FILTERS: DiscoveryFilters = {
  canonicalInclude: [],
  canonicalExclude: [],
  tag: [],
  tagMode: "all",
  fandom: [],
  genre: [],
  excludeTag: [],
  excludeFandom: [],
  excludeGenre: [],
  excludeAuthor: [],
  excludeText: [],
  language: [],
  completeOnly: "",
  crossover: "",
  status: "",
  minWordCount: "",
  minFavorites: "",
  minFollows: "",
  minReviews: "",
  minChapterCount: "",
  maxWordCount: "",
  updatedSinceDays: "",
  label: "",
  labelOrigin: "",
  importState: "",
  sortBy: "updated",
  sortOrder: "desc",
};

type ListFilterKey = {
  [K in keyof DiscoveryFilters]: NonNullable<DiscoveryFilters[K]> extends string[] ? K : never;
}[keyof DiscoveryFilters] & keyof DiscoveryFilters;

// Each list maps to a repeatable query parameter on the server.
export const LIST_FILTER_PARAMS: [ListFilterKey, string][] = [
  ["canonicalInclude", "canonical_include"],
  ["canonicalExclude", "canonical_exclude"],
  ["tag", "tag"],
  ["fandom", "fandom"],
  ["genre", "genre"],
  ["excludeTag", "exclude_tag"],
  ["excludeFandom", "exclude_fandom"],
  ["excludeGenre", "exclude_genre"],
  ["excludeAuthor", "exclude_author"],
  ["excludeText", "exclude_text"],
  ["language", "language"],
];

const SCALAR_FILTER_PARAMS: [keyof DiscoveryFilters, string][] = [
  ["status", "status"],
  ["minWordCount", "min_word_count"],
  ["minFavorites", "min_favorites"],
  ["minFollows", "min_follows"],
  ["minReviews", "min_reviews"],
  ["minChapterCount", "min_chapter_count"],
  ["maxWordCount", "max_word_count"],
  ["updatedSinceDays", "updated_since_days"],
  ["label", "label"],
  ["labelOrigin", "label_origin"],
  ["importState", "import_state"],
  ["sortBy", "sort_by"],
  ["sortOrder", "sort_order"],
];

/** Trims, drops blanks and case-insensitive repeats. */
export const cleanList = (value: unknown): string[] => {
  const items = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    if (typeof item !== "string") continue;
    const text = item.trim();
    if (!text || seen.has(text.toLowerCase())) continue;
    seen.add(text.toLowerCase());
    result.push(text);
  }
  return result;
};

/**
 * Accepts filters from the URL or a saved search. Older saved searches stored
 * tag, fandom and genre as single strings, which become one-item lists.
 */
export const normalizeDiscoveryFilters = (raw: unknown): DiscoveryFilters => {
  const source: Record<string, unknown> = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const result: Record<string, unknown> = { ...EMPTY_DISCOVERY_FILTERS };
  for (const key of Object.keys(EMPTY_DISCOVERY_FILTERS) as (keyof DiscoveryFilters)[]) {
    const fallback = EMPTY_DISCOVERY_FILTERS[key];
    const value = source[key];
    if (Array.isArray(fallback)) {
      result[key] = cleanList(value);
    } else if (key === "tagMode") {
      result[key] = value === "any" ? "any" : "all";
    } else if (key === "completeOnly") {
      result[key] = value === true || value === "true" ? "true" : "";
    } else if (key === "crossover") {
      result[key] = value === true || value === "true" ? "true" : value === false || value === "false" ? "false" : "";
    } else if (typeof value === "string" || typeof value === "number") {
      result[key] = String(value);
    }
  }
  return result as unknown as DiscoveryFilters;
};

/** True when any filter narrows results; sort and match mode alone do not. */
export const isDiscoveryFilterActive = (filters: DiscoveryFilters): boolean =>
  (Object.keys(filters) as (keyof DiscoveryFilters)[]).some((key) => {
    if (key === "sortBy" || key === "sortOrder" || key === "tagMode") return false;
    const value = filters[key];
    return Array.isArray(value) ? value.length > 0 : Boolean(value);
  });

/** Query parameters for the Discover list request. Lists repeat the key. */
export const discoveryFilterParams = (filters: Partial<DiscoveryFilters>): Record<string, string | string[]> => {
  const params: Record<string, string | string[]> = {};
  for (const [key, name] of LIST_FILTER_PARAMS) {
    const values = cleanList(filters[key]);
    if (values.length) params[name] = values;
  }
  for (const [key, name] of SCALAR_FILTER_PARAMS) {
    const value = String(filters[key] ?? "").trim();
    if (value) params[name] = value;
  }
  if (filters.tagMode === "any") params.tag_mode = "any";
  if (filters.completeOnly === "true") params.complete_only = "true";
  if (filters.crossover === "true" || filters.crossover === "false") params.crossover = filters.crossover;
  return params;
};

export interface DiscoveryFilterChip {
  /** Filter key the chip removes from. */
  key: keyof DiscoveryFilters;
  /** The list value to remove; undefined for scalar filters. */
  value?: string;
  label: string;
}

const LIST_LABELS: Partial<Record<keyof DiscoveryFilters, string>> = {
  canonicalInclude: "Reviewed term",
  canonicalExclude: "Hide reviewed term",
  tag: "Tag",
  fandom: "Fandom",
  genre: "Genre",
  language: "Language",
  excludeTag: "Hide tag",
  excludeFandom: "Hide fandom",
  excludeGenre: "Hide genre",
  excludeAuthor: "Hide author",
  excludeText: "Hide word",
};

const SCALAR_LABELS: Partial<Record<keyof DiscoveryFilters, (value: string) => string>> = {
  status: (value) => `Status: ${value}`,
  minWordCount: (value) => `Min words: ${value}`,
  maxWordCount: (value) => `Max words: ${value}`,
  updatedSinceDays: (value) => `Updated within ${value} days`,
  minFavorites: (value) => `Min favorites: ${value}`,
  minFollows: (value) => `Min follows: ${value}`,
  minReviews: (value) => `Min reviews: ${value}`,
  minChapterCount: (value) => `Min chapters: ${value}`,
  completeOnly: () => "Complete only",
  crossover: (value) => (value === "true" ? "Crossovers only" : "Single fandom only"),
  label: (value) => `Label: ${value}`,
};

/** One removable chip per active filter value, in display order. Sort options are not filters. */
export const describeDiscoveryFilters = (filters: DiscoveryFilters): DiscoveryFilterChip[] => {
  const chips: DiscoveryFilterChip[] = [];
  (Object.keys(LIST_LABELS) as (keyof DiscoveryFilters)[]).forEach((key) => {
    const prefix = LIST_LABELS[key];
    const values = filters[key];
    if (!Array.isArray(values)) return;
    values.forEach((value) => chips.push({ key, value, label: `${prefix}: ${value}` }));
  });
  (Object.keys(SCALAR_LABELS) as (keyof DiscoveryFilters)[]).forEach((key) => {
    const value = filters[key];
    if (typeof value !== "string" || !value) return;
    chips.push({ key, label: SCALAR_LABELS[key]!(value) });
  });
  return chips;
};

/** Returns a copy of the filters with one chip's value removed. */
export const removeDiscoveryFilterChip = (filters: DiscoveryFilters, chip: DiscoveryFilterChip): DiscoveryFilters => {
  const current = filters[chip.key];
  if (Array.isArray(current)) {
    return { ...filters, [chip.key]: current.filter((value) => value !== chip.value) };
  }
  return { ...filters, [chip.key]: "" };
};
