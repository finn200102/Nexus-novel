import { accountStorage } from "../../services/accountStorage";
// Reader preferences: global defaults plus optional per-story overrides.
// Version 2 (WP-D6) stores typography as one JSON record and migrates the 1.0 keys
// (font scale, line height, pixel width, Night/Dusk/Paper) without losing the user's choices.

export type ReaderThemeChoice = "app" | "paper" | "sepia" | "night" | "black";
export type ReaderThemeName = Exclude<ReaderThemeChoice, "app">;
export type ReaderFont = "literata" | "source-serif" | "atkinson" | "opendyslexic" | "system";
export type ReaderWidth = "narrow" | "medium" | "wide";
export type ParagraphStyle = "spaced" | "indented";
export type AuthorNotesMode = "collapsed" | "shown" | "hidden";
export type ReaderLayout = "scroll" | "paged";

export interface ReaderTypography {
  theme: ReaderThemeChoice;
  font: ReaderFont;
  /** Body size in CSS px (14–28). Rendered in rem so browser text zoom still applies. */
  fontSize: number;
  lineHeight: number;
  width: ReaderWidth;
  letterSpacing: number;
  wordSpacing: number;
  paragraphStyle: ParagraphStyle;
  justify: boolean;
  hyphenate: boolean;
}

export const READER_DEFAULTS: ReaderTypography = {
  theme: "app",
  font: "literata",
  fontSize: 19,
  lineHeight: 1.6,
  width: "medium",
  letterSpacing: 0,
  wordSpacing: 0,
  paragraphStyle: "spaced",
  justify: false,
  hyphenate: false,
};

export const FONT_SIZE_MIN = 14;
export const FONT_SIZE_MAX = 28;
export const LINE_HEIGHTS = [
  { value: 1.4, label: "Compact" },
  { value: 1.6, label: "Comfortable" },
  { value: 1.9, label: "Loose" },
] as const;
export const LETTER_SPACINGS = [0, 0.05, 0.1] as const;
export const WORD_SPACINGS = [0, 0.1, 0.2] as const;
export const MEASURE_CH: Record<ReaderWidth, number> = { narrow: 56, medium: 66, wide: 76 };

export const THEME_CHOICES: ReaderThemeChoice[] = ["app", "paper", "sepia", "night", "black"];
export const FONTS: { value: ReaderFont; label: string; family: string }[] = [
  { value: "literata", label: "Literata", family: "var(--font-read-literata)" },
  { value: "source-serif", label: "Source Serif 4", family: "var(--font-read-source-serif)" },
  { value: "atkinson", label: "Atkinson Hyperlegible", family: "var(--font-read-atkinson)" },
  { value: "opendyslexic", label: "OpenDyslexic", family: "var(--font-read-opendyslexic)" },
  { value: "system", label: "System sans", family: "var(--font-read-system)" },
];

const WIDTHS: ReaderWidth[] = ["narrow", "medium", "wide"];
const FONT_VALUES = FONTS.map((font) => font.value);
const AUTHOR_NOTES_MODES: AuthorNotesMode[] = ["collapsed", "shown", "hidden"];
const LAYOUTS: ReaderLayout[] = ["scroll", "paged"];

export const GLOBAL_KEY = "nexus-reader-typography";
const LEGACY_KEYS = {
  fontScale: "nexus-reader-font-scale",
  lineHeight: "nexus-reader-line-height",
  contentWidth: "nexus-reader-content-width",
  theme: "nexus-reader-theme",
} as const;
const SHORTCUTS_KEY = "nexus-reader-shortcuts";

export const novelSettingsKey = (novelId: number) => `nexus-reader-novel-${novelId}`;

const safeGet = (key: string): string | null => {
  try {
    return accountStorage.getItem(key);
  } catch {
    return null;
  }
};

const safeSet = (key: string, value: string) => {
  try {
    accountStorage.setItem(key, value);
  } catch {
    // Storage can be blocked (private mode); the reader still works in memory.
  }
};

const safeRemove = (key: string) => {
  try {
    accountStorage.removeItem(key);
  } catch {
    // ignore
  }
};

const oneOf = <T extends string>(raw: unknown, allowed: readonly T[], fallback: T): T =>
  typeof raw === "string" && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const nearest = (value: number, stops: readonly number[]) =>
  stops.reduce((best, stop) => (Math.abs(stop - value) < Math.abs(best - value) ? stop : best), stops[0]);

/* ---------- Migration from the 1.0 settings ---------- */

/** Night/Dusk/Paper → Night/Sepia/Paper. */
export const migrateTheme = (raw: unknown): ReaderThemeChoice | undefined => {
  if (raw === "dusk") return "sepia";
  return typeof raw === "string" && (THEME_CHOICES as string[]).includes(raw) ? (raw as ReaderThemeChoice) : undefined;
};

/** 1.0 font scale (0.85–1.3 of the old base) → px, keeping the relative choice around the new 19 px default. */
export const migrateFontScale = (scale: number) => clamp(Math.round(READER_DEFAULTS.fontSize * scale), FONT_SIZE_MIN, FONT_SIZE_MAX);

/** 1.0 line heights (Compact 1.5 / Comfortable 1.8 / Relaxed 2.1) → the new named stops. */
export const migrateLineHeight = (value: number) => (value <= 1.6 ? 1.4 : value < 2 ? 1.6 : 1.9);

/** 1.0 pixel widths (Narrow 620 / Balanced 760 / Wide 920) → measures. */
export const migrateWidth = (px: number): ReaderWidth => (px <= 680 ? "narrow" : px <= 840 ? "medium" : "wide");

const positive = (raw: unknown): number | undefined => {
  const value = typeof raw === "string" ? Number(raw) : raw;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
};

/** Validates a v2 record (or a partial one); unknown or invalid fields are dropped. */
export function sanitizeTypography(raw: Record<string, unknown>): Partial<ReaderTypography> {
  const out: Partial<ReaderTypography> = {};
  const theme = migrateTheme(raw.theme);
  if (theme) out.theme = theme;
  if (typeof raw.font === "string" && (FONT_VALUES as string[]).includes(raw.font)) out.font = raw.font as ReaderFont;
  const size = positive(raw.fontSize);
  if (size !== undefined) out.fontSize = clamp(Math.round(size), FONT_SIZE_MIN, FONT_SIZE_MAX);
  const lineHeight = positive(raw.lineHeight);
  if (lineHeight !== undefined) out.lineHeight = nearest(lineHeight, LINE_HEIGHTS.map((stop) => stop.value));
  if (typeof raw.width === "string" && (WIDTHS as string[]).includes(raw.width)) out.width = raw.width as ReaderWidth;
  if (typeof raw.letterSpacing === "number") out.letterSpacing = nearest(raw.letterSpacing, LETTER_SPACINGS);
  if (typeof raw.wordSpacing === "number") out.wordSpacing = nearest(raw.wordSpacing, WORD_SPACINGS);
  if (raw.paragraphStyle === "spaced" || raw.paragraphStyle === "indented") out.paragraphStyle = raw.paragraphStyle;
  if (typeof raw.justify === "boolean") out.justify = raw.justify;
  if (typeof raw.hyphenate === "boolean") out.hyphenate = raw.hyphenate;
  return out;
}

/** Converts a 1.0 record ({fontScale, lineHeight, contentWidth, theme}) to v2 fields. */
function migrateLegacy(raw: Record<string, unknown>): Partial<ReaderTypography> {
  const out: Partial<ReaderTypography> = {};
  const theme = migrateTheme(raw.theme);
  if (theme) out.theme = theme;
  const scale = positive(raw.fontScale);
  if (scale !== undefined) out.fontSize = migrateFontScale(scale);
  const lineHeight = positive(raw.lineHeight);
  if (lineHeight !== undefined) out.lineHeight = migrateLineHeight(lineHeight);
  const width = positive(raw.contentWidth);
  if (width !== undefined) out.width = migrateWidth(width);
  return out;
}

const parse = (raw: string | null): Record<string, unknown> | null => {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
};

/* ---------- Global settings ---------- */

export function readGlobalTypography(): ReaderTypography {
  const stored = parse(safeGet(GLOBAL_KEY));
  if (stored) return { ...READER_DEFAULTS, ...sanitizeTypography(stored) };
  // First run after the update: carry the 1.0 keys over once.
  const legacy = migrateLegacy({
    fontScale: safeGet(LEGACY_KEYS.fontScale),
    lineHeight: safeGet(LEGACY_KEYS.lineHeight),
    contentWidth: safeGet(LEGACY_KEYS.contentWidth),
    theme: safeGet(LEGACY_KEYS.theme),
  });
  return { ...READER_DEFAULTS, ...legacy };
}

export function writeGlobalTypography(value: ReaderTypography) {
  safeSet(GLOBAL_KEY, JSON.stringify({ v: 2, ...value }));
  Object.values(LEGACY_KEYS).forEach(safeRemove);
}

/* ---------- Per-story override ---------- */

/** Returns the story override, or null when the story follows the global settings. */
export function readStoryOverride(novelId: number): Partial<ReaderTypography> | null {
  const parsed = parse(safeGet(novelSettingsKey(novelId)));
  if (!parsed) return null;
  const override = parsed.v === 2 ? sanitizeTypography(parsed) : migrateLegacy(parsed);
  return Object.keys(override).length ? override : null;
}

export function writeStoryOverride(novelId: number, override: Partial<ReaderTypography> | null) {
  if (!override) safeRemove(novelSettingsKey(novelId));
  else safeSet(novelSettingsKey(novelId), JSON.stringify({ v: 2, ...override }));
}

export const resolveTypography = (
  global: ReaderTypography,
  override: Partial<ReaderTypography> | null,
): ReaderTypography => ({ ...global, ...(override ?? {}) });

/** "app" follows the resolved app theme: light → Paper, dark → Night. */
export const resolveReaderTheme = (choice: ReaderThemeChoice, appTheme: "light" | "dark"): ReaderThemeName =>
  choice === "app" ? (appTheme === "dark" ? "night" : "paper") : choice;

/* ---------- Reader-wide preferences (not per story) ---------- */

export function readAuthorNotesMode(): AuthorNotesMode {
  return oneOf(safeGet("nexus-reader-author-notes"), AUTHOR_NOTES_MODES, "collapsed");
}

const patchAccountPreference = (patch: Record<string, unknown>) => {
  window.dispatchEvent(new CustomEvent("nexus-reader-preference-local-patch", { detail: { patch } }));
};

export function writeAuthorNotesMode(mode: AuthorNotesMode, sync = true) {
  safeSet("nexus-reader-author-notes", mode);
  if (sync) patchAccountPreference({ authorNotes: mode });
}

export function readLayout(): ReaderLayout {
  return oneOf(safeGet("nexus-reader-layout"), LAYOUTS, "scroll");
}

export function writeLayout(layout: ReaderLayout, sync = true) {
  safeSet("nexus-reader-layout", layout);
  if (sync) patchAccountPreference({ layout });
}

/** Single-key shortcuts (WCAG 2.1.4): on by default, can be switched off. */
export function readShortcutsEnabled(): boolean {
  return safeGet(SHORTCUTS_KEY) !== "off";
}

export function writeShortcutsEnabled(enabled: boolean, sync = true) {
  safeSet(SHORTCUTS_KEY, enabled ? "on" : "off");
  if (sync) patchAccountPreference({ shortcuts: enabled });
  try {
    window.dispatchEvent(new CustomEvent("nexus-reader-shortcuts", { detail: enabled }));
  } catch {
    // ignore (non-browser environments)
  }
}
