/**
 * Human title for a story. Stored titles can be URL slugs, percent-encoded
 * text, "Threadmarks for: ..." prefixes, or empty (old ingest fallbacks).
 * Never returns a `%XX` sequence or a raw slug.
 */

const PLACEHOLDER_TITLES = new Set(["scraping...", "unknown", "untitled"]);
const SMALL_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"]);
const THREADMARKS_PREFIX = /^threadmarks\s+for\s*:\s*/i;

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value.replace(/%[0-9A-Fa-f]{2}/g, " ");
  }
}

function titleCase(words: string): string {
  return words
    .split(" ")
    .filter(Boolean)
    .map((word, index) => {
      const lower = word.toLowerCase();
      if (index > 0 && SMALL_WORDS.has(lower)) return lower;
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

function fromSlug(slug: string): string {
  return titleCase(slug.replace(/[-_]+/g, " ").trim());
}

function titleFromUrl(url: string | null | undefined): string {
  if (!url) return "";
  const path = safeDecode(url.split(/[?#]/)[0]).split("/").filter(Boolean);
  const last = path[path.length - 1];
  if (!last || /^\d+$/.test(last)) return "";
  return fromSlug(last);
}

export function displayTitle(story: { title?: string | null; url?: string | null }): string {
  let title = safeDecode((story.title ?? "").trim()).replace(THREADMARKS_PREFIX, "").trim();
  if (PLACEHOLDER_TITLES.has(title.toLowerCase())) title = "";
  if (!title) return titleFromUrl(story.url) || "Untitled story";
  // Slugs are lowercase with dashes or underscores; a mixed-case title with a dash is left alone.
  if (title === title.toLowerCase() && /[-_]/.test(title)) return fromSlug(title);
  return title.replace(/\s+/g, " ");
}
