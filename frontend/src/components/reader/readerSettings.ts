// Reader preferences: global defaults plus optional per-story overrides.
// Global keys keep their historical names so existing settings survive.

export type ReaderTheme = "night" | "dusk" | "paper";
export type AuthorNotesMode = "collapsed" | "shown" | "hidden";
export type ReaderLayout = "scroll" | "paged";

export interface ReaderTypography {
  fontScale: number;
  lineHeight: number;
  contentWidth: number;
  theme: ReaderTheme;
}

export const READER_DEFAULTS: ReaderTypography = {
  fontScale: 1,
  lineHeight: 1.8,
  contentWidth: 760,
  theme: "night",
};

const THEMES: ReaderTheme[] = ["night", "dusk", "paper"];
const AUTHOR_NOTES_MODES: AuthorNotesMode[] = ["collapsed", "shown", "hidden"];
const LAYOUTS: ReaderLayout[] = ["scroll", "paged"];

const GLOBAL_KEYS = {
  fontScale: "nexus-reader-font-scale",
  lineHeight: "nexus-reader-line-height",
  contentWidth: "nexus-reader-content-width",
  theme: "nexus-reader-theme",
} as const;

export const novelSettingsKey = (novelId: number) => `nexus-reader-novel-${novelId}`;

const safeGet = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

const safeSet = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage can be blocked (private mode); the reader still works in memory.
  }
};

const safeRemove = (key: string) => {
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
};

const numberOr = (raw: string | null, fallback: number): number => {
  const value = Number(raw);
  return raw && Number.isFinite(value) && value > 0 ? value : fallback;
};

const oneOf = <T extends string>(raw: string | null, allowed: T[], fallback: T): T =>
  (allowed as string[]).includes(raw ?? "") ? (raw as T) : fallback;

export function readGlobalTypography(): ReaderTypography {
  return {
    fontScale: numberOr(safeGet(GLOBAL_KEYS.fontScale), READER_DEFAULTS.fontScale),
    lineHeight: numberOr(safeGet(GLOBAL_KEYS.lineHeight), READER_DEFAULTS.lineHeight),
    contentWidth: numberOr(safeGet(GLOBAL_KEYS.contentWidth), READER_DEFAULTS.contentWidth),
    theme: oneOf(safeGet(GLOBAL_KEYS.theme), THEMES, READER_DEFAULTS.theme),
  };
}

export function writeGlobalTypography(value: ReaderTypography) {
  safeSet(GLOBAL_KEYS.fontScale, String(value.fontScale));
  safeSet(GLOBAL_KEYS.lineHeight, String(value.lineHeight));
  safeSet(GLOBAL_KEYS.contentWidth, String(value.contentWidth));
  safeSet(GLOBAL_KEYS.theme, value.theme);
}

/** Returns the story override, or null when the story follows the global settings. */
export function readStoryOverride(novelId: number): Partial<ReaderTypography> | null {
  const raw = safeGet(novelSettingsKey(novelId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const override: Partial<ReaderTypography> = {};
    if (typeof parsed.fontScale === "number" && parsed.fontScale > 0) override.fontScale = parsed.fontScale;
    if (typeof parsed.lineHeight === "number" && parsed.lineHeight > 0) override.lineHeight = parsed.lineHeight;
    if (typeof parsed.contentWidth === "number" && parsed.contentWidth > 0) override.contentWidth = parsed.contentWidth;
    if (typeof parsed.theme === "string" && (THEMES as string[]).includes(parsed.theme)) override.theme = parsed.theme as ReaderTheme;
    return Object.keys(override).length ? override : null;
  } catch {
    return null;
  }
}

export function writeStoryOverride(novelId: number, override: Partial<ReaderTypography> | null) {
  if (!override) safeRemove(novelSettingsKey(novelId));
  else safeSet(novelSettingsKey(novelId), JSON.stringify(override));
}

export const resolveTypography = (
  global: ReaderTypography,
  override: Partial<ReaderTypography> | null,
): ReaderTypography => ({ ...global, ...(override ?? {}) });

export function readAuthorNotesMode(): AuthorNotesMode {
  return oneOf(safeGet("nexus-reader-author-notes"), AUTHOR_NOTES_MODES, "collapsed");
}

export function writeAuthorNotesMode(mode: AuthorNotesMode) {
  safeSet("nexus-reader-author-notes", mode);
}

export function readLayout(): ReaderLayout {
  return oneOf(safeGet("nexus-reader-layout"), LAYOUTS, "scroll");
}

export function writeLayout(layout: ReaderLayout) {
  safeSet("nexus-reader-layout", layout);
}
