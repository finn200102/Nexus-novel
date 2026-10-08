export type BlocklistKind = "tag" | "fandom" | "genre" | "author" | "word";

export interface BlocklistEntry {
  id: number;
  kind: BlocklistKind;
  value: string;
  created_at: string | null;
}

export interface Shelf {
  id: number;
  name: string;
  position: number;
  novel_ids: number[];
}

export interface PersonalData {
  novel_id: number;
  notes: string | null;
  rating: number | null;
  user_tags: string[];
  followed_categories?: string[];
  auto_download?: boolean;
  keep_ahead?: number;
}

export interface LibraryPersonalEntry extends PersonalData {
  has_notes: boolean;
  shelf_ids: number[];
}

/** One "why this" reason per recommended or similar story, as plain sentences. */
export type RecommendationReasons = string[];

export const BLOCKLIST_KIND_LABELS: Record<BlocklistKind, string> = {
  tag: "Tag",
  fandom: "Fandom",
  genre: "Genre",
  author: "Author",
  word: "Word in title or summary",
};
