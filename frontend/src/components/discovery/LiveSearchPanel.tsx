import React, { useState } from "react";
import { Plus, Search } from "lucide-react";
import { getUserFacingError } from "../../services/apiClient";
import { LiveResult, LiveResponse, SiteError, liveSearchService } from "../../services/liveSearchService";

const SEARCH_SITES: Array<{ value: string; label: string }> = [
  { value: "royalroad", label: "Royal Road" },
  { value: "fanfiction", label: "FanFiction.net" },
  { value: "archive", label: "AO3" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "sufficientvelocity", label: "Sufficient Velocity" },
  { value: "questionablequesting", label: "Questionable Questing" },
  { value: "webnovel", label: "WebNovel" },
];

const FEEDS: Array<{ site: string; feed: string; label: string }> = [
  { site: "royalroad", feed: "rising-stars", label: "Royal Road · Rising stars" },
  { site: "royalroad", feed: "best-rated", label: "Royal Road · Best rated" },
  { site: "royalroad", feed: "trending", label: "Royal Road · Trending" },
  { site: "royalroad", feed: "latest-updates", label: "Royal Road · Latest updates" },
  { site: "spacebattles", feed: "latest-threadmarks", label: "SpaceBattles · Latest threadmarks" },
  { site: "sufficientvelocity", feed: "latest-threadmarks", label: "Sufficient Velocity · Latest threadmarks" },
  { site: "questionablequesting", feed: "latest-threadmarks", label: "Questionable Questing · Latest threadmarks" },
];

const ERROR_TEXT: Record<string, string> = {
  rate_limited: "rate limited, try again later",
  circuit_open: "paused after repeated failures",
  source_blocked: "blocked by the site",
  timeout: "timed out",
  unsupported: "not supported",
  metadata_unavailable: "metadata server unavailable",
};

const siteLabel = (site: string) => SEARCH_SITES.find((option) => option.value === site)?.label ?? site;

interface Props {
  onAdd: (result: LiveResult) => Promise<void>;
}

export const LiveSearchPanel: React.FC<Props> = ({ onAdd }) => {
  const [query, setQuery] = useState("");
  const [sites, setSites] = useState<string[]>(["royalroad", "fanfiction", "archive"]);
  const [feed, setFeed] = useState("");
  const [response, setResponse] = useState<LiveResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);

  const run = async (nextPage: number, browse = feed) => {
    setLoading(true);
    setError(null);
    try {
      const [site, feedName] = browse.split("|");
      const data = browse
        ? await liveSearchService.browse(site, feedName, nextPage)
        : await liveSearchService.search(query.trim(), sites, nextPage);
      setResponse(data);
      setPage(nextPage);
    } catch (err) {
      setError(getUserFacingError(err, "Live search failed"));
    } finally {
      setLoading(false);
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim() || sites.length === 0) return;
    setFeed("");
    void run(1, "");
  };

  const toggleSite = (site: string) =>
    setSites((current) => (current.includes(site) ? current.filter((value) => value !== site) : [...current, site]));

  const add = async (result: LiveResult) => {
    setAdding(result.source_url);
    try {
      await onAdd(result);
    } finally {
      setAdding(null);
    }
  };

  return (
    <section className="live-search" aria-label="Search the sites">
      <form className="discover-toolbar__search" onSubmit={submit}>
        <Search size={16} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the source sites" aria-label="Search the source sites" />
        <button type="submit" disabled={loading || !query.trim() || sites.length === 0}>Search</button>
      </form>
      <div className="discover-source-tabs" role="group" aria-label="Sites to search">
        {SEARCH_SITES.map((option) => (
          <button key={option.value} type="button" aria-pressed={sites.includes(option.value)}
            className={sites.includes(option.value) ? "is-active" : ""} onClick={() => toggleSite(option.value)}>
            {option.label}
          </button>
        ))}
      </div>
      <label className="live-search__feed">
        <span>Or browse a feed</span>
        <select value={feed} onChange={(event) => { setFeed(event.target.value); if (event.target.value) void run(1, event.target.value); }}>
          <option value="">Choose a feed…</option>
          {FEEDS.map((option) => <option key={`${option.site}|${option.feed}`} value={`${option.site}|${option.feed}`}>{option.label}</option>)}
        </select>
      </label>

      {error && <div className="discover-error"><p>{error}</p></div>}
      {response && response.errors.length > 0 && (
        <ul className="live-search__errors" aria-label="Sites that did not answer">
          {response.errors.map((item: SiteError) => (
            <li key={item.site} title={item.message}>{siteLabel(item.site)}: {ERROR_TEXT[item.code] ?? item.code}</li>
          ))}
        </ul>
      )}
      {loading && <p className="discover-result-count">Asking the sites… each site is queried once and paced.</p>}
      {!loading && response && (
        <>
          <p className="discover-result-count">{response.results.length} results · page {page}</p>
          <ul className="live-search__results">
            {response.results.map((result) => (
              <li key={result.source_url}>
                {result.img_url ? <img src={result.img_url} alt="" loading="lazy" /> : <span className="live-search__cover" aria-hidden="true" />}
                <div>
                  <a href={result.source_url} target="_blank" rel="noreferrer noopener"><strong>{result.title}</strong></a>
                  <small>
                    {[siteLabel(result.site || result.novel_site || ""), result.author, result.chapter_count ? `${result.chapter_count} ch` : null,
                      result.word_count ? `${result.word_count.toLocaleString()} words` : null, result.sources.includes("local") ? "in catalog" : null]
                      .filter(Boolean).join(" · ")}
                  </small>
                  {result.description && <p>{result.description}</p>}
                </div>
                <button type="button" className="discover-secondary-btn" onClick={() => void add(result)} disabled={adding === result.source_url}>
                  <Plus size={14} aria-hidden="true" /> Add
                </button>
              </li>
            ))}
          </ul>
          <div className="discover-pagination">
            {page > 1 && <button type="button" className="discover-load-more" onClick={() => void run(page - 1)}>Previous page</button>}
            {response.results.length > 0 && <button type="button" className="discover-load-more" onClick={() => void run(page + 1)}>Next page</button>}
          </div>
        </>
      )}
    </section>
  );
};

export default LiveSearchPanel;
