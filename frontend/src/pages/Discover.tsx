import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { discoveryService } from "../services/discoveryService";
import { useLibraryContext } from "../context/LibraryContext";
import { useToast } from "../context/ToastContext";
import { DiscoveredNovel } from "../types/discovery";
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

  const currentSite = site || "royalroad";

  useEffect(() => {
    setNovels([]);
    setCurrentPage(1);
    setHasMore(true);
    fetchNovels(currentSite, 1);
  }, [currentSite]);

  const fetchNovels = async (siteValue: string, page: number) => {
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
        cursor
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
      <header className="library-workspace__header">
        <div>
          <p className="library-workspace__eyebrow">Discover</p>
          <h1>Browse Novels</h1>
          <p className="library-workspace__summary">
            Explore novels from various sources and add them to your library.
          </p>
        </div>
      </header>

      <div className="library-controls">
        <div className="library-select-group">
          <label>
            Source
            <select
              value={currentSite}
              onChange={(e) => handleSiteChange(e.target.value)}
            >
              {SITE_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

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
