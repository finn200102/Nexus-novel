/** Hosts Nexus reads with a site-specific scraper; mirrors SUPPORTED_HOSTS in the backend. */
const KNOWN_HOSTS = new Set([
  "www.royalroad.com",
  "forums.spacebattles.com",
  "www.fanfiction.net",
  "archiveofourown.org",
  "www.webnovel.com",
  "webnovel.com",
  "forums.sufficientvelocity.com",
  "forum.questionablequesting.com",
  "www.scribblehub.com",
]);

/** True when the link points at a site with its own support, not a generic web serial. */
export const isKnownSiteUrl = (url: string): boolean => {
  try {
    return KNOWN_HOSTS.has(new URL(url.trim()).hostname.toLowerCase());
  } catch {
    return false;
  }
};
