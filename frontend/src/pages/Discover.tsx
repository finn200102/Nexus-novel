import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BookOpen, Plus, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { discoveryService } from "../services/discoveryService";
import { useLibraryContext } from "../context/LibraryContext";
import { useToast } from "../context/ToastContext";
import { DiscoveredNovel, DiscoveryFilters, FandomInfo } from "../types/discovery";
import { Novel } from "../types/novel";
import NovelCard from "../components/novel/NovelCard";
import { NovelCardSkeleton } from "../components/common/Skeleton";
import { cancelPendingRequests, getUserFacingError, isRequestCancelled } from "../services/apiClient";
import { RequestCoordinator, useAdaptivePolling } from "../services/requestResilience";
import { SavedSearch, savedSearchService } from "../services/savedSearchService";
import CreateNovelForm from "../components/novel/CreateNovelForm";
import defaultCoverImage from "../assets/cover.png";
import "../styles/library.css";
import "../styles/novel-list.css";

const SITE_OPTIONS = [
  { value: "all", label: "All Sites" },
  { value: "royalroad", label: "Royal Road" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "fanfiction", label: "FanFiction" },
  { value: "archive", label: "AO3" },
  { value: "webnovel", label: "WebNovel" },
];

const ITEMS_PER_PAGE = 20;

const EMPTY_FILTERS: DiscoveryFilters = {
  tag: "",
  fandom: "",
  genre: "",
  status: "",
  minWordCount: "",
  minFavorites: "",
  minFollows: "",
  minReviews: "",
  minChapterCount: "",
  maxWordCount: "",
  updatedSinceDays: "",
  label: "",
  labelOrigin: "",
  importState: "",
  sortBy: "updated",
  sortOrder: "desc",
};

const Discover: React.FC = () => {
  const { site } = useParams<{ site?: string }>();
  const navigate = useNavigate();
  const { activeLibraryId } = useLibraryContext();
  const { addToast } = useToast();

  const [novels, setNovels] = useState<DiscoveredNovel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<DiscoveryFilters>(EMPTY_FILTERS);
  const [fandomOptions, setFandomOptions] = useState<FandomInfo[]>([]);
  const [appliedFilters, setAppliedFilters] = useState<DiscoveryFilters>(EMPTY_FILTERS);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);
  const [catalogStatus, setCatalogStatus] = useState<"unknown" | "online" | "offline">("unknown");
  const coordinatorRef = React.useRef(new RequestCoordinator());
  const hasSnapshotRef = React.useRef(false);
  const locationSearch = window.location.search;
  const queryParams = new URLSearchParams(locationSearch);
  const searchFromUrl = queryParams.get("q") || "";
  const filtersFromUrl = (() => {
    try { return { ...EMPTY_FILTERS, ...JSON.parse(queryParams.get("filters") || "{}") } as DiscoveryFilters; }
    catch { return EMPTY_FILTERS; }
  })();

  const currentSite = site || "all";

  useEffect(() => {
    if (!filtersOpen) return;
    const timer = window.setTimeout(() => {
      void discoveryService.getFandoms(currentSite, filters.fandom).then(setFandomOptions).catch(() => setFandomOptions([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [currentSite, filters.fandom, filtersOpen]);

  useEffect(() => {
    setNovels([]);
    hasSnapshotRef.current = false;
    setNextCursor(null);
    setHasMore(true);
    setSearch(searchFromUrl);
    setFilters(filtersFromUrl);
    setAppliedFilters(filtersFromUrl);
    void fetchNovels(currentSite, 1, searchFromUrl, filtersFromUrl);
    return () => cancelPendingRequests("/discovery/novels/");
  }, [currentSite, locationSearch]);

  useEffect(() => {
    void savedSearchService.list().then(setSavedSearches).catch(() => setSavedSearches([]));
  }, []);

  const fetchNovels = async (
    siteValue: string,
    page: number,
    title = search,
    activeFilters = appliedFilters
  ) => {
    const cursor = page > 1 ? nextCursor : null;
    const key = `discover:${siteValue}:${page}:${title}:${cursor}:${JSON.stringify(activeFilters)}`;
    const hasSnapshot = hasSnapshotRef.current;
    try {
      if (page === 1 && !hasSnapshot) {
        setLoading(true);
      } else if (page > 1) {
        setLoadingMore(true);
      }
      setError(null);

      const response = await coordinatorRef.current.run(key, () => discoveryService.getNovelsBySite(
          siteValue === "all" ? null : siteValue,
          ITEMS_PER_PAGE,
          cursor,
          title,
          activeFilters
        ));

      console.log("Fetched novels:", response.data.slice(0, 3).map(n => ({ id: n.id, title: n.title?.slice(0, 30), img_url: n.img_url })));

      if (page === 1) {
        setNovels(response.data);
        hasSnapshotRef.current = true;
      } else {
        setNovels((prev) => [...prev, ...response.data]);
      }
      setHasMore(response.has_more);
      setNextCursor(response.next_cursor);
      setCatalogStatus("online");
      if (page === 1) {
        setLastRefreshAt(new Date());
      }
    } catch (err) {
      if (isRequestCancelled(err)) return;
      console.error("Failed to fetch novels:", err);
      setError(getUserFacingError(err, "Failed to load novels. Please try again."));
      setCatalogStatus("offline");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  const handleRefresh = () => {
    setNextCursor(null);
    setHasMore(true);
    setIsRefreshing(true);
    void fetchNovels(currentSite, 1, searchFromUrl, appliedFilters).finally(() => {
      setIsRefreshing(false);
    });
  };

  const handleImportSuccess = () => {
    setIsImportOpen(false);
    handleRefresh();
  };

  const handleSiteChange = (newSite: string) => {
    navigate(`/discover/${newSite}`);
  };

  const handleLoadMore = () => {
    if (nextCursor !== null) {
      void fetchNovels(currentSite, 2);
    }
  };

  useAdaptivePolling(() => fetchNovels(currentSite, 1, searchFromUrl, appliedFilters), true, {
    // Discover has no active job to monitor; refreshing it aggressively only
    // creates avoidable load while a source worker is busy elsewhere.
    activeMs: 15000,
    visibleIdleMs: 30000,
    hiddenMs: 30000,
  });

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    navigate(`/discover/${currentSite}${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ""}`);
  };

  const applyFilters = () => {
    setAppliedFilters(filters);
    setNextCursor(null);
    setHasMore(true);
    const params = new URLSearchParams();
    if (searchFromUrl) params.set("q", searchFromUrl);
    params.set("filters", JSON.stringify(filters));
    navigate(`/discover/${currentSite}?${params.toString()}`);
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setNextCursor(null);
    setHasMore(true);
    navigate(`/discover/${currentSite}${searchFromUrl ? `?q=${encodeURIComponent(searchFromUrl)}` : ""}`);
  };

  const saveSearch = async () => {
    const name = window.prompt("Name this saved search");
    if (!name?.trim()) return;
    try {
      await savedSearchService.create(name.trim(), appliedFilters, window.confirm("Notify when future imports match this search?"));
      setSavedSearches(await savedSearchService.list());
      addToast(`Saved search “${name.trim()}”`, "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not save this search"), "error");
    }
  };

  const updateFilter = (key: keyof DiscoveryFilters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const hasActiveFilters = Object.entries(appliedFilters).some(
    ([key, value]) => !["sortBy", "sortOrder"].includes(key) && Boolean(value)
  );

  const handleAddToLibrary = async (novel: DiscoveredNovel) => {
    if (!activeLibraryId) {
      addToast("Please select a library first", "warning");
      return;
    }

    try {
      await discoveryService.addToLibrary(activeLibraryId, novel.source_url);
      addToast(`"${novel.title}" added to your library!`, "success");
    } catch (err) {
      console.error("Failed to add novel:", err);
      addToast(getUserFacingError(err, "Failed to add novel to library"), "error");
    }
  };

  const handleNovelClick = (novel: DiscoveredNovel) => {
    navigate(`/discover/${currentSite}/${novel.id}`);
  };

  const getSiteDisplayName = (siteValue: string) => {
    const option = SITE_OPTIONS.find((s) => s.value === siteValue);
    return option?.label || siteValue;
  };

  const convertToNovel = (discovered: DiscoveredNovel): Novel => {
    return {
      id: discovered.id,
      title: discovered.title,
      url: discovered.source_url,
      description: discovered.description,
      cover_image: discovered.img_url || defaultCoverImage,
      library_id: 0,
      metadata_id: discovered.id,
      author: discovered.author,
      author_site_id: discovered.author_id,
      author_id: discovered.author_id,
      source_url: discovered.source_url,
      story_id: null,
      novel_site: discovered.novel_site,
      img_url: discovered.img_url || defaultCoverImage,
      word_count: discovered.word_count,
      reviews: discovered.reviews,
      favorites: discovered.favorites,
      follows: discovered.follows,
      status: discovered.status,
      views: discovered.views,
      rating: discovered.rating,
      publish_date: null,
      updated_date: discovered.updated_at,
      chapter_count: discovered.chapter_count,
      analyzed_at: null,
      analysis_type: null,
      analyzed_chapter_count: null,
      parsed_at: null,
      created_at: discovered.created_at,
      updated_at: discovered.updated_at,
      scrape_status: "completed",
      scrape_error: null,
      follow_state: "plan_to_read",
      followed_at: null,
    };
  };

  const renderPagination = () => {
    if (!hasMore || loadingMore) return null;

    return (
      <div className="discover-pagination">
        <button
          type="button"
          className="discover-load-more"
          onClick={handleLoadMore}
          disabled={loadingMore}
        >
          {loadingMore ? "Loading..." : "Load More"}
        </button>
      </div>
    );
  };

  return (
    <div className="library-workspace">
      <header className="discover-hero">
        <div>
          <p className="discover-hero__eyebrow">Metadata catalog</p>
          <h1>Find your next story</h1>
          <p>
            Search the Nexus metadata server, compare sources, and bring the stories you want into your library.
          </p>
        </div>
        <div className="discover-hero__actions">
          <button type="button" className="discover-secondary-btn" onClick={handleRefresh} disabled={loading || isRefreshing}>
            <RefreshCw size={16} className={isRefreshing ? "is-spinning" : ""} aria-hidden="true" />
            {isRefreshing ? "Refreshing" : "Refresh catalog"}
          </button>
          <button
            type="button"
            className="discover-primary-btn"
            onClick={() => setIsImportOpen(true)}
            disabled={!activeLibraryId}
            title={activeLibraryId ? "Import a novel by URL" : "Select a library before importing"}
          >
            <Plus size={17} aria-hidden="true" /> Import novel
          </button>
        </div>
      </header>

      <div className={`discover-catalog-status discover-catalog-status--${catalogStatus}`} role="status">
        <span className="discover-catalog-status__dot" aria-hidden="true" />
        <span>
          {catalogStatus === "offline" ? "Metadata catalog unavailable" : "Metadata catalog online"}
          {lastRefreshAt && catalogStatus === "online" && (
            <small> · checked {lastRefreshAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small>
          )}
        </span>
      </div>

      <div className="discover-toolbar">
        <form className="discover-toolbar__search" onSubmit={submitSearch}>
          <Search size={19} aria-hidden="true" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by title" />
        </form>
        <div className="discover-filter-actions">
          <button
            type="button"
            className={`discover-filter-toggle ${filtersOpen ? "is-active" : ""}`}
            onClick={() => setFiltersOpen((open) => !open)}
            title="Show filters"
            aria-expanded={filtersOpen}
            aria-controls="discover-filters"
          >
            <SlidersHorizontal size={16} aria-hidden="true" />
            Filters{hasActiveFilters ? " active" : ""}
          </button>
          {hasActiveFilters && (
            <button
              type="button"
              className="discover-clear-filters"
              onClick={clearFilters}
              title="Clear filters"
            >
              <X size={16} aria-hidden="true" />
            </button>
          )}
          {(hasActiveFilters || searchFromUrl) && (
            <button type="button" className="discover-filter-toggle" onClick={saveSearch} title="Save current search">
              Save search
            </button>
          )}
        </div>
        {filtersOpen && (
          <section id="discover-filters" className="discover-filters" aria-label="Discover filters">
            <label>
              Fandom / series
              <input list="discover-fandoms" value={filters.fandom} onChange={(event) => updateFilter("fandom", event.target.value)} placeholder="Search imported source fandoms" />
              <datalist id="discover-fandoms">
                {fandomOptions.map((fandom) => <option key={fandom.id} value={fandom.display_name}>{fandom.media_type}{fandom.story_count ? ` · ${fandom.story_count.toLocaleString()} stories` : ""}</option>)}
              </datalist>
            </label>
            <label>
              Tag
              <input value={filters.tag} onChange={(event) => updateFilter("tag", event.target.value)} placeholder="e.g. time loop" />
            </label>
            <label>
              Genre
              <input value={filters.genre} onChange={(event) => updateFilter("genre", event.target.value)} placeholder="e.g. fantasy" />
            </label>
            <label>
              Status
              <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
                <option value="">Any status</option>
                <option value="Complete">Complete</option>
                <option value="In-Progress">In progress</option>
                <option value="Ongoing">Ongoing</option>
              </select>
            </label>
            <label>
              Min words
              <input type="number" min="0" value={filters.minWordCount} onChange={(event) => updateFilter("minWordCount", event.target.value)} placeholder="0" />
            </label>
            <label>
              Max words
              <input type="number" min="0" value={filters.maxWordCount} onChange={(event) => updateFilter("maxWordCount", event.target.value)} placeholder="No maximum" />
            </label>
            <label>
              Updated within
              <select value={filters.updatedSinceDays} onChange={(event) => updateFilter("updatedSinceDays", event.target.value)}>
                <option value="">Any time</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option>
              </select>
            </label>
            <label>
              Min favorites
              <input type="number" min="0" value={filters.minFavorites} onChange={(event) => updateFilter("minFavorites", event.target.value)} placeholder="0" />
            </label>
            <label>
              Min follows
              <input type="number" min="0" value={filters.minFollows} onChange={(event) => updateFilter("minFollows", event.target.value)} placeholder="0" />
            </label>
            <label>
              Min reviews
              <input type="number" min="0" value={filters.minReviews} onChange={(event) => updateFilter("minReviews", event.target.value)} placeholder="0" />
            </label>
            <label>
              Min chapters
              <input type="number" min="0" value={filters.minChapterCount} onChange={(event) => updateFilter("minChapterCount", event.target.value)} placeholder="0" />
            </label>
            <label>
              Label
              <input value={filters.label} onChange={(event) => updateFilter("label", event.target.value)} placeholder="e.g. cozy" />
            </label>
            <label>
              Label origin
              <select value={filters.labelOrigin} onChange={(event) => updateFilter("labelOrigin", event.target.value)}>
                <option value="">Any signal</option><option value="ai">Nexus insight</option><option value="source">Source fact</option>
              </select>
            </label>
            <label>
              Import state
              <select value={filters.importState} onChange={(event) => updateFilter("importState", event.target.value)}><option value="">Ready only</option><option value="in_progress">Imports in progress</option></select>
            </label>
            <label>
              Sort by
              <select value={filters.sortBy} onChange={(event) => updateFilter("sortBy", event.target.value)}>
                <option value="updated">Last updated</option>
                <option value="favorites">Favorites</option>
                <option value="follows">Follows</option>
                <option value="views">Views</option>
                <option value="reviews">Reviews</option>
                <option value="word_count">Word count</option>
                <option value="chapter_count">Chapters</option>
                <option value="title">Title</option>
              </select>
            </label>
            <label>
              Direction
              <select value={filters.sortOrder} onChange={(event) => updateFilter("sortOrder", event.target.value)}>
                <option value="desc">Highest first</option>
                <option value="asc">Lowest first</option>
              </select>
            </label>
            <div className="discover-filters__commands">
              <button type="button" className="discover-filter-reset" onClick={() => setFilters(EMPTY_FILTERS)}>Reset</button>
              <button type="button" className="discover-filter-apply" onClick={applyFilters}>Apply filters</button>
            </div>
          </section>
        )}
        <div className="discover-source-tabs" role="tablist" aria-label="Novel source">
          {SITE_OPTIONS.map((option) => (
            <button key={option.value} type="button" role="tab" aria-selected={option.value === currentSite}
              className={option.value === currentSite ? "is-active" : ""} onClick={() => handleSiteChange(option.value)}>
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {savedSearches.length > 0 && (
        <section className="discover-saved-searches" aria-label="Saved searches">
          <div><strong>Saved searches</strong><small>Auto-updating filters you can reopen at any time.</small></div>
          <div>{savedSearches.map((saved) => <span key={saved.id}><button type="button" onClick={() => {
            const params = new URLSearchParams({ filters: JSON.stringify(saved.filters) });
            navigate(`/discover/all?${params.toString()}`);
          }}>{saved.name}{saved.notify_on_match ? " · alerts" : ""}</button><button type="button" aria-label={`Delete saved search ${saved.name}`} onClick={() => void savedSearchService.remove(saved.id).then(() => setSavedSearches((items) => items.filter((item) => item.id !== saved.id))).catch((err) => addToast(getUserFacingError(err, "Could not remove saved search"), "error"))}>×</button></span>)}</div>
        </section>
      )}

      {!loading && !error && <p className="discover-result-count">{novels.length}{hasMore ? "+" : ""} results from {getSiteDisplayName(currentSite)}</p>}

      {error && (
        <div className="discover-error">
          <p>{error}</p>
          <button onClick={() => fetchNovels(currentSite, 1)}>Retry</button>
        </div>
      )}

      {loading && (
        <div className="novel-list novel-list--grid">
          <div className="novel-list__grid">
            {Array.from({ length: 8 }).map((_, i) => (
              <NovelCardSkeleton key={`skeleton-${i}`} />
            ))}
          </div>
        </div>
      )}

      {!loading && novels.length === 0 && !error && (
        <div className="discover-empty">
          <BookOpen size={32} aria-hidden="true" />
          {searchFromUrl || hasActiveFilters ? (
            <>
              <h2>No matching novels</h2>
              <p>Try a broader search or clear your filters to see more of the Nexus catalog.</p>
              <button type="button" onClick={clearFilters}>Clear filters</button>
            </>
          ) : (
            <>
              <h2>Your catalog is ready for its first story</h2>
              <p>
                The metadata server is connected, but it has no imported novels yet. Import a story URL or load a catalog export to start discovering.
              </p>
              <div className="discover-empty__actions">
                <button type="button" onClick={() => setIsImportOpen(true)} disabled={!activeLibraryId}>
                  <Plus size={16} aria-hidden="true" /> Import novel by URL
                </button>
                <button type="button" className="is-secondary" onClick={handleRefresh} disabled={isRefreshing}>
                  <RefreshCw size={16} className={isRefreshing ? "is-spinning" : ""} aria-hidden="true" /> Check again
                </button>
              </div>
              {!activeLibraryId && <small>Select or create a library before importing.</small>}
            </>
          )}
        </div>
      )}

      {!loading && novels.length > 0 && (
        <>
          <div className="novel-list novel-list--grid">
            <div className="novel-list__grid">
              {novels.map((novel) => (
                <div key={novel.id} className="novel-card-wrapper">
                  <div className="discover-card-actions">
                    <button
                      type="button"
                      className="discover-add-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleAddToLibrary(novel);
                      }}
                      title="Add to library"
                    >
                      +
                    </button>
                  </div>
                  <NovelCard
                    novel={convertToNovel(novel)}
                    onClick={() => handleNovelClick(novel)}
                  />
                </div>
              ))}
            </div>
          </div>
          {renderPagination()}
        </>
      )}

      {activeLibraryId && (
        <CreateNovelForm
          library_id={activeLibraryId}
          isOpen={isImportOpen}
          onClose={() => setIsImportOpen(false)}
          onSuccess={handleImportSuccess}
        />
      )}
    </div>
  );
};

export default Discover;
