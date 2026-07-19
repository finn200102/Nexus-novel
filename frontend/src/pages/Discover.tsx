import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { discoveryService } from "../services/discoveryService";
import { useLibraryContext } from "../context/LibraryContext";
import { useToast } from "../context/ToastContext";
import { DiscoveredNovel, DiscoveryFilters } from "../types/discovery";
import { Novel } from "../types/novel";
import NovelCard from "../components/novel/NovelCard";
import { NovelCardSkeleton } from "../components/common/Skeleton";
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
  genre: "",
  status: "",
  minWordCount: "",
  minFavorites: "",
  minFollows: "",
  minReviews: "",
  minChapterCount: "",
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
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<DiscoveryFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<DiscoveryFilters>(EMPTY_FILTERS);
  const searchFromUrl = new URLSearchParams(window.location.search).get("q") || "";

  const currentSite = site || "royalroad";

  useEffect(() => {
    setNovels([]);
    setCurrentPage(1);
    setHasMore(true);
    setSearch(searchFromUrl);
    fetchNovels(currentSite, 1, searchFromUrl, appliedFilters);
  }, [currentSite, searchFromUrl]);

  const fetchNovels = async (
    siteValue: string,
    page: number,
    title = search,
    activeFilters = appliedFilters
  ) => {
    try {
      if (page === 1) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);

      const cursor = page > 1 ? (page - 1) * ITEMS_PER_PAGE : null;
      const response = await discoveryService.getNovelsBySite(
        siteValue === "all" ? null : siteValue,
        ITEMS_PER_PAGE,
        cursor,
        title,
        activeFilters
      );

      console.log("Fetched novels:", response.data.slice(0, 3).map(n => ({ id: n.id, title: n.title?.slice(0, 30), img_url: n.img_url })));

      if (page === 1) {
        setNovels(response.data);
      } else {
        setNovels((prev) => [...prev, ...response.data]);
      }
      setHasMore(response.has_more);
    } catch (err) {
      console.error("Failed to fetch novels:", err);
      setError("Failed to load novels. Please try again.");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  const handleSiteChange = (newSite: string) => {
    navigate(`/discover/${newSite}`);
  };

  const handleLoadMore = () => {
    const nextPage = currentPage + 1;
    setCurrentPage(nextPage);
    fetchNovels(currentSite, nextPage);
  };

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    navigate(`/discover/${currentSite}${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ""}`);
  };

  const applyFilters = () => {
    setAppliedFilters(filters);
    setCurrentPage(1);
    setHasMore(true);
    fetchNovels(currentSite, 1, searchFromUrl, filters);
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setCurrentPage(1);
    setHasMore(true);
    fetchNovels(currentSite, 1, searchFromUrl, EMPTY_FILTERS);
  };

  const updateFilter = (key: keyof DiscoveryFilters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const hasActiveFilters = Object.values(appliedFilters).some(Boolean);

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
      addToast("Failed to add novel to library", "error");
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
          {loadingMore ? "Loading..." : `Load More (Page ${currentPage + 1})`}
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
      </header>

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
        </div>
        {filtersOpen && (
          <section id="discover-filters" className="discover-filters" aria-label="Discover filters">
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
          <p>No novels found on {getSiteDisplayName(currentSite)}.</p>
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
    </div>
  );
};

export default Discover;
