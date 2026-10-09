/** Household instances (G4): shared shelves and content-limited profiles. */

export type SharePermission = "view" | "collaborate";
export type ContentRating = "general" | "teen" | "mature" | "explicit";

export interface ShareTarget {
  id: number;
  username: string;
}

export interface ShelfShare {
  user_id: number;
  username: string;
  permission: SharePermission;
}

export interface ShelfShares {
  shelf_id: number;
  share_notes: boolean;
  shares: ShelfShare[];
}

export interface SharedShelfSummary {
  id: number;
  name: string;
  owner: { id: number; username: string };
  permission: SharePermission;
  share_notes: boolean;
  story_count: number;
}

/** A catalog reference on a shared shelf. Never carries the owner's library copy or its text. */
export interface SharedStoryRef {
  entry_id: number;
  metadata_id: number | null;
  title: string;
  author: string | null;
  cover_url: string | null;
  site: string | null;
  source_url: string | null;
  added_by: string | null;
  added_by_me: boolean;
  notes: string | null;
  in_my_library: boolean;
}

export interface SharedShelfDetail {
  id: number;
  name: string;
  owner: { id: number; username: string | null };
  permission: SharePermission | "owner";
  share_notes: boolean;
  stories: SharedStoryRef[];
}

export interface ContentLimits {
  max_content_rating: ContentRating | null;
  hide_unrated: boolean;
  blocked_tags: string[];
  limited: boolean;
}

export const CONTENT_RATING_LABELS: Record<ContentRating, string> = {
  general: "General",
  teen: "Teen",
  mature: "Mature",
  explicit: "Explicit",
};

/** One line such as "stories rated up to Teen; no unrated stories". */
export const describeLimits = (limits: ContentLimits): string => {
  const parts: string[] = [];
  if (limits.max_content_rating) parts.push(`stories rated up to ${CONTENT_RATING_LABELS[limits.max_content_rating]}`);
  if (limits.max_content_rating && limits.hide_unrated) parts.push("no unrated stories");
  if (limits.blocked_tags.length) parts.push(`hidden tags: ${limits.blocked_tags.join(", ")}`);
  return parts.join("; ");
};
