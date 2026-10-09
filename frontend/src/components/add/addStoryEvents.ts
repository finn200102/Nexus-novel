/** App-wide Add story sheet: opened from the top bar, Home, Discover and Library (WP-D14). */
export const OPEN_ADD_STORY = "nexus:add-story";
/** Fired after stories were added, so pages showing that library can refresh. */
export const STORY_ADDED = "nexus:story-added";

export interface OpenAddStoryDetail {
  /** Prefill the link field. */
  url?: string;
  /** Library to add to; defaults to the active library. */
  libraryId?: number;
  /** Open on the Import tab. */
  tab?: "link" | "import";
}

export function openAddStory(detail: OpenAddStoryDetail = {}) {
  window.dispatchEvent(new CustomEvent<OpenAddStoryDetail>(OPEN_ADD_STORY, { detail }));
}

export function notifyStoryAdded(libraryId: number) {
  window.dispatchEvent(new CustomEvent<{ libraryId: number }>(STORY_ADDED, { detail: { libraryId } }));
}

/** Split pasted text into links: one per line, also tolerating commas and spaces. */
export function parseLinks(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,]+/).map((part) => part.trim()).filter(Boolean)));
}
