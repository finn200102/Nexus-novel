/** Number of fallback hues (`--cover-1` … `--cover-8` in styles/tokens.css). */
export const COVER_HUES = 8;

/** Stable 32-bit FNV-1a hash of a string. */
export function hashString(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** 1-based hue index for a title; the same title always gets the same colour. */
export function coverHueIndex(title: string): number {
  return (hashString(title.trim().toLowerCase()) % COVER_HUES) + 1;
}

/** CSS colour for a title's fallback cover. */
export function coverHue(title: string): string {
  return `var(--cover-${coverHueIndex(title)})`;
}
