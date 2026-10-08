import type { Params } from "react-router-dom";

/**
 * Every pre-redesign URL and where it lives now (proposal §2.4). Query string and hash are kept,
 * so notification links, OPDS links and bookmarks keep working.
 */
export const LEGACY_REDIRECTS: { from: string; to: (params: Params) => string }[] = [
  { from: "/discover/:site/:novelId", to: (p) => `/story/${p.novelId}` },
  { from: "/story-guide/:metadataId", to: (p) => `/story/${p.metadataId}/guide` },
  { from: "/story-guide/:metadataId/review", to: (p) => `/story/${p.metadataId}/guide/review` },
  { from: "/library/:libraryId", to: (p) => `/library?library=${p.libraryId}` },
  { from: "/activity", to: () => "/updates" },
  { from: "/downloads", to: () => "/updates/downloads" },
  { from: "/account", to: () => "/settings/account" },
  { from: "/notifications", to: () => "/settings/notifications" },
  { from: "/hidden-content", to: () => "/settings/hidden" },
  { from: "/operations", to: () => "/admin/status" },
  { from: "/scrape-jobs", to: () => "/admin/jobs" },
  { from: "/integrations", to: () => "/admin/duplicates" },
];

/** Joins a target that may carry its own query with the incoming query string. */
export const withSearch = (target: string, search: string, hash = "") => {
  const extra = search.replace(/^\?/, "");
  if (!extra) return target + hash;
  return `${target}${target.includes("?") ? "&" : "?"}${extra}${hash}`;
};
