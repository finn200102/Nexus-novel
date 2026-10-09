import type { DiscoveredNovel } from "../../types/discovery";
import type { Novel } from "../../types/novel";
import { displayTitle } from "../../utils/displayTitle";

/**
 * What the story page shows, merged from the catalog record and (when the story is in a
 * library) the library copy. Missing values stay null so the page can omit them.
 */
export interface StoryView {
  title: string;
  author: string | null;
  site: string | null;
  sourceUrl: string | null;
  cover: string | null;
  description: string | null;
  status: string | null;
  chapterCount: number | null;
  wordCount: number | null;
  views: number | null;
  favorites: number | null;
  follows: number | null;
  reviews: number | null;
  rating: number | null;
  published: string | null;
  updated: string | null;
  tags: string[];
  genres: string[];
  fandoms: string[];
  metadataId: number | null;
  siteStoryId: number | null;
}

const SITE_LABELS: Record<string, string> = {
  royalroad: "Royal Road",
  fanfiction: "FanFiction.Net",
  spacebattles: "SpaceBattles",
  archive: "Archive of Our Own",
  ao3: "Archive of Our Own",
  webnovel: "WebNovel",
  sufficientvelocity: "Sufficient Velocity",
  webserial: "Web serial",
  questionablequesting: "Questionable Questing",
  scribblehub: "Scribble Hub",
};

/** Sites whose support is still experimental; the page labels them. */
export const EXPERIMENTAL_SITES = new Set(["scribblehub"]);

export const siteLabel = (site: string | null | undefined): string | null => {
  if (!site) return null;
  return SITE_LABELS[site.toLowerCase()] ?? site;
};

export const isExperimentalSite = (site: string | null | undefined) => !!site && EXPERIMENTAL_SITES.has(site.toLowerCase());

const pick = <T,>(...values: (T | null | undefined)[]): T | null => {
  for (const value of values) if (value !== null && value !== undefined && value !== "") return value;
  return null;
};

export const termNames = (terms: Array<string | { name: string }> | undefined | null): string[] =>
  (terms ?? []).map((term) => (typeof term === "string" ? term : term?.name)).filter((name): name is string => !!name);

export function toStoryView(catalog: DiscoveredNovel | null, novel: Novel | null): StoryView {
  const title = displayTitle({
    title: pick(novel?.title, catalog?.title),
    url: pick(novel?.source_url, novel?.url, catalog?.source_url),
  });
  return {
    title,
    author: pick(novel?.author, catalog?.author),
    site: pick(novel?.novel_site, catalog?.novel_site),
    sourceUrl: pick(novel?.source_url, novel?.url, catalog?.source_url),
    cover: pick(novel?.img_url, novel?.cover_image, catalog?.img_url),
    description: pick(novel?.description, catalog?.description),
    status: pick(novel?.status, catalog?.status),
    chapterCount: pick(novel?.chapter_count, catalog?.chapter_count),
    wordCount: pick(novel?.word_count, catalog?.word_count),
    views: pick(novel?.views, catalog?.views),
    favorites: pick(novel?.favorites, catalog?.favorites),
    follows: pick(novel?.follows, catalog?.follows),
    reviews: pick(novel?.reviews, catalog?.reviews),
    rating: pick(novel?.rating, catalog?.rating),
    published: pick(novel?.publish_date),
    updated: pick(novel?.updated_date, catalog?.updated_at),
    tags: termNames(catalog?.tags),
    genres: termNames(catalog?.genres),
    fandoms: termNames(catalog?.fandoms),
    metadataId: pick(novel?.metadata_id, catalog?.id),
    siteStoryId: pick(novel?.story_id),
  };
}

/** 412k, 1.2M; plain below 1000. */
export const compactNumber = (value: number) => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
};

export const formatDate = (iso: string | null | undefined) => {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
};

/** "2 h ago", "3 days ago", or a date after a month. */
export const relativeTime = (iso: string | null | undefined, now = new Date()) => {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const minutes = Math.round((now.getTime() - date.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatDate(iso);
};

/** "Complete", or "Ongoing" when updated within a year; otherwise the source's own word. */
export const statusLabel = (view: Pick<StoryView, "status" | "updated">, now = new Date()) => {
  const raw = view.status?.trim();
  if (raw && /^complete/i.test(raw)) return "Complete";
  if (view.updated) {
    const updated = new Date(view.updated);
    const yearAgo = new Date(now);
    yearAgo.setFullYear(yearAgo.getFullYear() - 1);
    if (!Number.isNaN(updated.getTime()) && updated > yearAgo) return "Ongoing";
  }
  return raw || null;
};

/** "Ongoing · 98 chapters · 412k words · updated 2 h ago"; missing values are left out. */
export const storyFacts = (view: StoryView, now = new Date()): string[] => {
  const facts: string[] = [];
  const status = statusLabel(view, now);
  if (status) facts.push(status);
  if (view.chapterCount) facts.push(`${view.chapterCount.toLocaleString("en-US")} chapter${view.chapterCount === 1 ? "" : "s"}`);
  if (view.wordCount) facts.push(`${compactNumber(view.wordCount)} words`);
  const updated = relativeTime(view.updated, now);
  if (updated) facts.push(`updated ${updated}`);
  return facts;
};

export type FollowState = Novel["follow_state"];

export const FOLLOW_STATE_LABELS: Record<FollowState, string> = {
  reading: "Reading",
  plan_to_read: "Plan to read",
  on_hold: "On hold",
  completed: "Completed",
  dropped: "Dropped",
  ignored: "Not following",
};

/** The reading statuses offered in the Status menu ("ignored" is the Follow toggle's off state). */
export const STATUS_OPTIONS: FollowState[] = ["reading", "plan_to_read", "on_hold", "completed", "dropped"];

export const NOTIFY_LABELS = {
  immediate: "Immediately",
  daily_digest: "Daily digest",
  weekly_digest: "Weekly digest",
  after_n: "After a number of chapters",
} as const;

/** Find stories with a tag in Discover. */
export const discoverTagLink = (kind: "tag" | "genre" | "fandom", value: string) =>
  `/discover/all?${new URLSearchParams({ filters: JSON.stringify({ [kind]: [value] }) }).toString()}`;

/** "Side story", "Index" … for a chapter category. */
export const categoryLabel = (category: string) =>
  category.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());

/** "Chapter 41" for story chapters; non-chapter entries (index, contents …) are labelled by their kind. */
export const entryLabel = (chapter: { chapter_number: number; category?: string }) =>
  !chapter.category || chapter.category === "story" ? `Chapter ${chapter.chapter_number}` : categoryLabel(chapter.category);

/** Jump-to-chapter search: number prefix or title substring. */
export const matchesChapter = (chapter: { chapter_number: number; title: string }, query: string) => {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return String(chapter.chapter_number).startsWith(q) || (chapter.title || "").toLowerCase().includes(q);
};
