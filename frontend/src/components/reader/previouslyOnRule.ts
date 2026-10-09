// Rule for the "Previously on…" recap: show it when a story is reopened after a break,
// at most once per return, and only when the reader has not turned recaps off.

export const RECAP_DAY_CHOICES = [0, 3, 7, 14] as const;
export type RecapDays = (typeof RECAP_DAY_CHOICES)[number];
export const DEFAULT_RECAP_DAYS: RecapDays = 7;
export const RECAP_DAYS_KEY = "nexus-reader-recap-days";
const shownKey = (novelId: number) => `nexus-reader-recap-shown-${novelId}`;

export function readRecapDays(): RecapDays {
  try {
    const stored = window.localStorage.getItem(RECAP_DAYS_KEY);
    if (stored === null) return DEFAULT_RECAP_DAYS;
    const raw = Number(stored);
    return (RECAP_DAY_CHOICES as readonly number[]).includes(raw) ? (raw as RecapDays) : DEFAULT_RECAP_DAYS;
  } catch {
    return DEFAULT_RECAP_DAYS;
  }
}

export function writeRecapDays(days: RecapDays) {
  try {
    window.localStorage.setItem(RECAP_DAYS_KEY, String(days));
  } catch {
    /* storage unavailable: the setting simply does not persist */
  }
}

/** Whole days between the last read and now; never negative. */
export function daysSince(lastReadAt: string, now: Date): number {
  const then = new Date(lastReadAt).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.max(0, Math.floor((now.getTime() - then) / 86_400_000));
}

/** The break is identified by the last-read timestamp, so each return is shown once. */
export function recapAlreadyShown(novelId: number, lastReadAt: string): boolean {
  try {
    return window.localStorage.getItem(shownKey(novelId)) === lastReadAt;
  } catch {
    return false;
  }
}

export function markRecapShown(novelId: number, lastReadAt: string) {
  try {
    window.localStorage.setItem(shownKey(novelId), lastReadAt);
  } catch {
    /* ignore */
  }
}

export function shouldShowRecap(input: {
  lastReadAt: string | null;
  novelId: number;
  thresholdDays: RecapDays;
  now: Date;
}): boolean {
  const { lastReadAt, novelId, thresholdDays, now } = input;
  if (!lastReadAt || thresholdDays === 0) return false;
  if (daysSince(lastReadAt, now) < thresholdDays) return false;
  return !recapAlreadyShown(novelId, lastReadAt);
}

/** The paragraphs around the saved scroll percent, i.e. the last thing the reader saw. */
export function lastReadParagraphs(content: string, percent: number, count = 2): string[] {
  const paragraphs = content.split("\n").map((line) => line.trim()).filter(Boolean);
  if (paragraphs.length === 0) return [];
  const index = Math.min(paragraphs.length - 1, Math.max(0, Math.floor((percent / 100) * paragraphs.length)));
  return paragraphs.slice(Math.max(0, index - count + 1), index + 1);
}
