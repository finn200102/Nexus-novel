/** Author support links as the API returns them: one entry per platform page. */
export interface SupportLink {
  kind: string;
  url: string;
}

export const SUPPORT_KIND_LABELS: Record<string, string> = {
  patreon: "Patreon",
  kofi: "Ko-fi",
  subscribestar: "SubscribeStar",
  buymeacoffee: "Buy Me a Coffee",
  liberapay: "Liberapay",
};

const KNOWN_HOSTS = ["patreon.com", "ko-fi.com", "subscribestar.com", "subscribestar.adult", "buymeacoffee.com", "liberapay.com"];

/** Defense in depth: keep only https links on the known platforms with a known kind. */
export function safeSupportLinks(raw: unknown): SupportLink[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const links: SupportLink[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const { kind, url } = item as Record<string, unknown>;
    if (typeof kind !== "string" || typeof url !== "string" || !(kind in SUPPORT_KIND_LABELS)) continue;
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      continue;
    }
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const known = KNOWN_HOSTS.some((domain) => host === domain || host.endsWith(`.${domain}`));
    if (parsed.protocol !== "https:" || !known || parsed.username || parsed.password || seen.has(url)) continue;
    seen.add(url);
    links.push({ kind, url });
  }
  return links;
}
