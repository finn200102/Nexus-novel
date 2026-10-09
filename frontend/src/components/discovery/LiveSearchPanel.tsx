import React, { useState } from "react";
import { Plus } from "lucide-react";
import { Button, Cover, FilterChip, Input, Select } from "../ui";
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
  metadata_unavailable: "story catalog offline",
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
      setError(getUserFacingError(err, "The site search failed. Try again."));
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
      <form className="live-search__form" role="search" onSubmit={submit}>
        <Input
          type="search"
          search
          label="Search the source sites"
          hideLabel
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onClear={() => setQuery("")}
          placeholder="Search Royal Road, AO3 and more"
        />
        <Button type="submit" variant="primary" disabled={loading || !query.trim() || sites.length === 0}>Search</Button>
      </form>
      <div className="discover-sites" role="group" aria-label="Sites to search">
        {SEARCH_SITES.map((option) => (
          <FilterChip key={option.value} selected={sites.includes(option.value)} onChange={() => toggleSite(option.value)}>
            {option.label}
          </FilterChip>
        ))}
      </div>
      <Select
        label="Or browse a feed"
        fieldClassName="live-search__feed"
        value={feed}
        onChange={(event) => {
          setFeed(event.target.value);
          if (event.target.value) void run(1, event.target.value);
        }}
        options={[{ value: "", label: "Choose a feed…" }, ...FEEDS.map((option) => ({ value: `${option.site}|${option.feed}`, label: option.label }))]}
      />

      {error && <p className="live-search__error" role="alert">{error}</p>}
      {response && response.errors.length > 0 && (
        <ul className="live-search__errors" aria-label="Sites that did not answer">
          {response.errors.map((item: SiteError) => (
            <li key={item.site} title={item.message}>{siteLabel(item.site)}: {ERROR_TEXT[item.code] ?? item.code}</li>
          ))}
        </ul>
      )}
      <p className="live-search__status" role="status">
        {loading ? "Asking the sites… each site is asked once, at a polite pace." : response ? `${response.results.length} results · page ${page}` : ""}
      </p>
      {!loading && response && (
        <>
          <ul className="live-search__results">
            {response.results.map((result) => (
              <li key={result.source_url}>
                <Cover src={result.img_url} title={result.title} size={48} />
                <div className="live-search__text">
                  <a href={result.source_url} target="_blank" rel="noreferrer noopener">
                    <strong>{result.title}</strong>
                    <span className="visually-hidden"> (opens in a new tab)</span>
                  </a>
                  <small>
                    {[siteLabel(result.site || result.novel_site || ""), result.author, result.chapter_count ? `${result.chapter_count} chapters` : null,
                      result.word_count ? `${result.word_count.toLocaleString()} words` : null, result.sources.includes("local") ? "in catalog" : null]
                      .filter(Boolean).join(" · ")}
                  </small>
                  {result.description && <p>{result.description}</p>}
                </div>
                <Button size="sm" icon={<Plus aria-hidden="true" />} onClick={() => void add(result)} loading={adding === result.source_url} aria-label={`Add ${result.title}`}>
                  Add
                </Button>
              </li>
            ))}
          </ul>
          <div className="live-search__pages">
            {page > 1 && <Button onClick={() => void run(page - 1)}>Previous page</Button>}
            {response.results.length > 0 && <Button onClick={() => void run(page + 1)}>Next page</Button>}
          </div>
        </>
      )}
    </section>
  );
};

export default LiveSearchPanel;
