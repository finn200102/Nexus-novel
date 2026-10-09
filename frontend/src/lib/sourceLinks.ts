import { siteLabel } from "../components/story/storyModel";

export interface SourceLink {
  label: string;
  href: string;
}

export interface SourceLinks {
  /** Display name of the source site, e.g. "Archive of Our Own". */
  siteName: string;
  open: SourceLink | null;
  comments: SourceLink | null;
  kudos: SourceLink | null;
}

const withoutFragment = (url: string) => url.split("#")[0];

/** FanFiction.net story id: explicit id first, otherwise parsed from the /s/<id>/ story URL. */
function fanfictionStoryId(url: string | null, storyId: string | number | null | undefined): string | null {
  const explicit = storyId === null || storyId === undefined ? "" : String(storyId).trim();
  if (/^\d+$/.test(explicit)) return explicit;
  const match = url?.match(/fanfiction\.net\/s\/(\d+)/i);
  return match ? match[1] : null;
}

/**
 * Links back to the original source for a story. `url` is the story's source URL,
 * `storyId` is the site's own id (used for FanFiction.net reviews).
 * Returns null for unknown or missing sites.
 */
export function buildSourceLinks({
  site,
  url,
  storyId,
}: {
  site: string | null | undefined;
  url?: string | null;
  storyId?: string | number | null;
}): SourceLinks | null {
  const siteName = siteLabel(site);
  if (!site || !siteName) return null;
  const key = site.trim().toLowerCase();
  const base = url && url.trim() ? withoutFragment(url.trim()) : null;

  const open = base ? { label: `Open on ${siteName}`, href: base } : null;
  const comments = (href: string | null): SourceLink | null =>
    href ? { label: `Comments on ${siteName}`, href } : null;

  let commentsHref: string | null = null;
  let kudos: SourceLink | null = null;

  switch (key) {
    case "ao3":
    case "archive":
      commentsHref = base ? `${base}#comments` : null;
      kudos = base ? { label: "Leave kudos on AO3", href: base } : null;
      break;
    case "royalroad":
      // Royal Road keeps reviews on the fiction page itself.
      commentsHref = base ? `${base}#comments` : null;
      break;
    case "fanfiction": {
      const id = fanfictionStoryId(url ?? null, storyId);
      commentsHref = id ? `https://www.fanfiction.net/r/${id}/` : null;
      break;
    }
    case "spacebattles":
    case "sufficientvelocity":
    case "questionablequesting":
    case "webnovel":
    case "scribblehub":
      // Forum threads and book pages hold the discussion on the page itself.
      commentsHref = base;
      break;
    default:
      commentsHref = null;
  }

  return { siteName, open, comments: comments(commentsHref), kudos };
}

/** Label for the end-of-chapter link, e.g. "Read this chapter on Royal Road". */
export function chapterSourceLabel(site: string | null | undefined): string | null {
  const name = siteLabel(site);
  return name ? `Read this chapter on ${name}` : null;
}
