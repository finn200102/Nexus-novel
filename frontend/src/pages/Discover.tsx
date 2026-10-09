import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { discoveryService } from "../services/discoveryService";
import { organizationService } from "../services/organizationService";
import { useLibraryContext } from "../context/useLibraryContext";
import { useToast } from "../context/useToast";
import { DiscoveredNovel, DiscoveryFilters, FandomInfo } from "../types/discovery";
import {
  EMPTY_DISCOVERY_FILTERS,
  describeDiscoveryFilters,
  isDiscoveryFilterActive,
  normalizeDiscoveryFilters,
  removeDiscoveryFilterChip,
  DiscoveryFilterChip,
} from "../services/discoveryFilters";
import { Banner, Button, EmptyState, InputChip, PageHeader, Tabs } from "../components/ui";
import { usePageTitle } from "../hooks/usePageTitle";
import { cancelPendingRequests, getUserFacingError, isRequestCancelled } from "../services/apiClient";
import { RequestCoordinator, useAdaptivePolling } from "../services/requestResilience";
import { SavedSearch, savedSearchService } from "../services/savedSearchService";
import { openAddStory } from "../components/add/addStoryEvents";
import { LiveSearchPanel } from "../components/discovery/LiveSearchPanel";
import { DiscoverSearchBar } from "../components/discovery/DiscoverSearchBar";
import { SiteChips } from "../components/discovery/SiteChips";
import { FilterBar } from "../components/discovery/FilterBar";
import { MoreFiltersSheet } from "../components/discovery/MoreFiltersSheet";
import { ResultsGrid } from "../components/discovery/ResultsGrid";
import { discoverSiteLabel } from "../components/discovery/sites";
import { LiveResult } from "../services/liveSearchService";
import { LimitedProfileNotice } from "../components/household/LimitedProfileNotice";
import "../styles/live-search.css";
import "../styles/discover.css";

const ITEMS_PER_PAGE = 20;

const EMPTY_FILTERS = EMPTY_DISCOVERY_FILTERS;

const parseDiscoverUrl = (locationSearch: string) => {
  const queryParams = new URLSearchParams(locationSearch);
  const searchFromUrl = queryParams.get("q") || "";
  const similarToFromUrl = Number(queryParams.get("similar_to")) || null;
  const filtersFromUrl = (() => {
    try { return normalizeDiscoveryFilters(JSON.parse(queryParams.get("filters") || "{}")); }
    catch { return EMPTY_FILTERS; }
  })();
  return { searchFromUrl, similarToFromUrl, filtersFromUrl };
};

const Discover: React.FC = () => {
  usePageTitle("Discover");
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
  const [fandomDraft, setFandomDraft] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<DiscoveryFilters>(EMPTY_FILTERS);
  const [mode, setMode] = useState<"catalog" | "live">("catalog");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<"unknown" | "online" | "offline">("unknown");
  const coordinatorRef = React.useRef(new RequestCoordinator());
  const hasSnapshotRef = React.useRef(false);
  const locationSearch = window.location.search;
  const { searchFromUrl, similarToFromUrl } = parseDiscoverUrl(locationSearch);

  const currentSite = site || "all";

  useEffect(() => {
    if (!filtersOpen) return;
    const timer = window.setTimeout(() => {
      void discoveryService.getFandoms(currentSite, fandomDraft).then((rows) => setFandomOptions(Array.isArray(rows) ? rows : [])).catch(() => setFandomOptions([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [currentSite, fandomDraft, filtersOpen]);

  useEffect(() => {
    void savedSearchService.list().then(setSavedSearches).catch(() => setSavedSearches([]));
  }, []);

  const fetchNovels = async (
    siteValue: string,
    page: number,
    title = search,
    activeFilters = appliedFilters,
    similarTo = similarToFromUrl,
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
          activeFilters,
          similarTo,
        ));

      if (page === 1) {
        setNovels(response.data);
        hasSnapshotRef.current = true;
      } else {
        setNovels((prev) => [...prev, ...response.data]);
      }
      setHasMore(response.has_more);
      setNextCursor(response.next_cursor);
      setCatalogStatus("online");
    } catch (err) {
      if (isRequestCancelled(err)) return;
      console.error("Failed to fetch novels:", err);
      setError(getUserFacingError(err, "We couldn't load stories. Try again."));
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
    void fetchNovels(currentSite, 1, searchFromUrl, appliedFilters, similarToFromUrl).finally(() => {
      setIsRefreshing(false);
    });
  };


  const handleSiteChange = (newSite: string) => {
    navigate(`/discover/${newSite}`);
  };

  const handleLoadMore = () => {
    if (nextCursor !== null) {
    void fetchNovels(currentSite, 2, search, appliedFilters, similarToFromUrl);
    }
  };

  // The URL effect below must run only when the site or query string changes.
  // It reads the latest fetchNovels through a ref so it does not re-run on
  // every search/filter edit.
  const fetchNovelsRef = React.useRef(fetchNovels);
  fetchNovelsRef.current = fetchNovels;

  useEffect(() => {
    const fromUrl = parseDiscoverUrl(locationSearch);
    setNovels([]);
    hasSnapshotRef.current = false;
    setNextCursor(null);
    setHasMore(true);
    setSearch(fromUrl.searchFromUrl);
    setFilters(fromUrl.filtersFromUrl);
    setAppliedFilters(fromUrl.filtersFromUrl);
    void fetchNovelsRef.current(currentSite, 1, fromUrl.searchFromUrl, fromUrl.filtersFromUrl, fromUrl.similarToFromUrl);
    return () => cancelPendingRequests("/discovery/novels/");
  }, [currentSite, locationSearch]);

  useAdaptivePolling(() => fetchNovels(currentSite, 1, searchFromUrl, appliedFilters, similarToFromUrl), true, {
    // Discover has no active job to monitor; refreshing it aggressively only
    // creates avoidable load while a source worker is busy elsewhere.
    activeMs: 15000,
    visibleIdleMs: 30000,
    hiddenMs: 30000,
  });

  const applyFilters = (next: DiscoveryFilters = filters) => {
    setAppliedFilters(next);
    setNextCursor(null);
    setHasMore(true);
    const params = new URLSearchParams();
    if (searchFromUrl) params.set("q", searchFromUrl);
    params.set("filters", JSON.stringify(next));
    navigate(`/discover/${currentSite}?${params.toString()}`);
  };

  const removeChip = (chip: DiscoveryFilterChip) => {
    const next = removeDiscoveryFilterChip(appliedFilters, chip);
    setFilters(next);
    applyFilters(next);
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
      addToast(`Saved search “${name.trim()}”.`, "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not save this search."), "error");
    }
  };

  const hasActiveFilters = isDiscoveryFilterActive(appliedFilters);
  const activeChips = describeDiscoveryFilters(appliedFilters);
  const fandomSuggestions = Array.from(new Set(fandomOptions.map((fandom) => fandom.display_name)));

  const handleAddToLibrary = async (novel: DiscoveredNovel) => {
    if (!activeLibraryId) {
      addToast("Create a library first.", "warning");
      return;
    }

    try {
      await discoveryService.addToLibrary(activeLibraryId, novel.source_url);
      addToast(`Added “${novel.title}” to your library.`, "success");
    } catch (err) {
      console.error("Failed to add novel:", err);
      addToast(getUserFacingError(err, "Could not add the story to your library."), "error");
    }
  };

  const handleAddLiveResult = async (result: LiveResult) => {
    if (!activeLibraryId) {
      addToast("Create a library first.", "warning");
      return;
    }
    try {
      await discoveryService.addToLibrary(activeLibraryId, result.source_url);
      addToast(`Added “${result.title}” to your library.`, "success");
    } catch (err) {
      addToast(getUserFacingError(err, "Could not add the story to your library."), "error");
    }
  };

  const hideAuthor = async (novel: DiscoveredNovel) => {
    if (!novel.author) return;
    const author = novel.author;
    try {
      const entry = await organizationService.addBlocklistEntry("author", author);
      setNovels((current) => current.filter((item) => item.author !== author));
      addToast(`Hidden author “${author}”.`, "success", undefined, {
        action: {
          label: "Undo",
          onClick: () => void organizationService.removeBlocklistEntry(entry.id).then(handleRefresh).catch(() => addToast("Could not undo. Check Settings › Hidden.", "error")),
        },
      });
    } catch (err) {
      addToast(getUserFacingError(err, "Could not hide this author."), "error");
    }
  };

  const patchFilters = (patch: Partial<DiscoveryFilters>) => {
    const next = { ...appliedFilters, ...patch };
    setFilters(next);
    applyFilters(next);
  };

  const countText = loading || error
    ? null
    : novels.length === 0
      ? null
      : `${novels.length}${hasMore ? "+" : ""} ${novels.length === 1 ? "story" : "stories"}${currentSite === "all" ? "" : ` from ${discoverSiteLabel(currentSite).replace(" (experimental)", "")}`}`;

  const emptyState = searchFromUrl || hasActiveFilters ? (
    <EmptyState
      title="No matching stories"
      description="Try a broader search or clear your filters."
      action={<Button onClick={clearFilters}>Clear filters</Button>}
    />
  ) : (
    <EmptyState
      title="No stories here yet"
      description="The catalog has no stories for this site yet. Add a story by link, or check again later."
      action={
        <>
          <Button variant="primary" icon={<Plus aria-hidden="true" />} onClick={() => openAddStory()}>Add story</Button>
          <Button onClick={handleRefresh} loading={isRefreshing}>Check again</Button>
        </>
      }
    />
  );

  return (
    <div className="discover-page">
      <PageHeader title="Discover" description="Search and browse stories on supported sites." />
      <LimitedProfileNotice />

      <Tabs<"catalog" | "live">
        label="Where to search"
        value={mode}
        onChange={setMode}
        items={[
          { value: "catalog", label: "Catalog" },
          { value: "live", label: "Search the sites" },
        ]}
      />

      {mode === "live" && <LiveSearchPanel onAdd={handleAddLiveResult} />}

      {mode === "catalog" && (
        <>
          {catalogStatus === "offline" && <Banner tone="warning">Can't reach the story catalog. Retrying.</Banner>}
          <div className="discover-controls">
            <DiscoverSearchBar
              value={search}
              onChange={setSearch}
              onSubmit={() => navigate(`/discover/${currentSite}${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ""}`)}
              onClear={() => {
                setSearch("");
                if (searchFromUrl) navigate(`/discover/${currentSite}`);
              }}
            />
            <SiteChips value={currentSite} onChange={handleSiteChange} />
            <FilterBar
              filters={appliedFilters}
              onChange={patchFilters}
              onMoreFilters={() => {
                setFilters(appliedFilters);
                setFiltersOpen(true);
              }}
              moreOpen={filtersOpen}
              chips={activeChips}
              onRemoveChip={removeChip}
              onClearAll={clearFilters}
              onSaveSearch={hasActiveFilters || searchFromUrl ? () => void saveSearch() : undefined}
            />
          </div>

          <MoreFiltersSheet
            open={filtersOpen}
            onClose={() => setFiltersOpen(false)}
            filters={filters}
            onChange={setFilters}
            onApply={() => {
              applyFilters();
              setFiltersOpen(false);
            }}
            onReset={() => setFilters(EMPTY_FILTERS)}
            fandomSuggestions={fandomSuggestions}
            onFandomDraftChange={setFandomDraft}
          />

          {savedSearches.length > 0 && (
            <section className="discover-saved" aria-labelledby="discover-saved-heading">
              <h2 id="discover-saved-heading" className="discover-saved__heading">Saved searches</h2>
              <ul className="discover-saved__list">
                {savedSearches.map((saved) => (
                  <li key={saved.id}>
                    <InputChip
                      onRemove={() =>
                        void savedSearchService
                          .remove(saved.id)
                          .then(() => setSavedSearches((items) => items.filter((item) => item.id !== saved.id)))
                          .catch((err) => addToast(getUserFacingError(err, "Could not remove the saved search."), "error"))
                      }
                      removeLabel={`Delete saved search ${saved.name}`}
                    >
                      {saved.name + (saved.notify_on_match ? " · alerts" : "")}
                    </InputChip>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/discover/all?${new URLSearchParams({ filters: JSON.stringify(saved.filters) }).toString()}`)}
                    >
                      Open<span className="visually-hidden"> {saved.name}</span>
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ResultsGrid
            novels={novels}
            loading={loading}
            loadingMore={loadingMore}
            hasMore={hasMore && nextCursor !== null}
            error={error}
            countText={countText}
            onRetry={() => void fetchNovels(currentSite, 1)}
            onLoadMore={handleLoadMore}
            onAdd={(novel) => void handleAddToLibrary(novel)}
            onHideAuthor={(novel) => void hideAuthor(novel)}
            empty={emptyState}
          />
        </>
      )}
    </div>
  );
};

export default Discover;
