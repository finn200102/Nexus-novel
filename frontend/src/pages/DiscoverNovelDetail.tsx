import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import defaultCoverImage from "../assets/cover.png";
import { discoveryService } from "../services/discoveryService";
import { useLibraryContext } from "../context/LibraryContext";
import { useToast } from "../context/ToastContext";
import { DiscoveredNovel } from "../types/discovery";
import NovelDetails from "../components/novel/NovelDetails";
import { NovelDetailHeroSkeleton } from "../components/common/Skeleton";
import { insightService, InsightSignal, SimilarNovel } from "../services/insightService";
import "../styles/novel-detail.css";

const DiscoverNovelDetail: React.FC = () => {
  const { site, novelId } = useParams<{ site: string; novelId: string }>();
  const navigate = useNavigate();
  const { libraries, activeLibraryId } = useLibraryContext();
  const { addToast } = useToast();

  const [novel, setNovel] = useState<DiscoveredNovel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [addingToLibrary, setAddingToLibrary] = useState<boolean>(false);
  const [signals, setSignals] = useState<InsightSignal[]>([]);
  const [similar, setSimilar] = useState<SimilarNovel[]>([]);

  const fetchNovel = useCallback(async () => {
    if (!novelId) return;
    try {
      setLoading(true);
      const id = parseInt(novelId, 10);
      const data = await discoveryService.getNovelById(id);
      setNovel(data);
    } catch (err) {
      console.error("Failed to fetch novel:", err);
      setError("Failed to load novel details");
    } finally {
      setLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    fetchNovel();
  }, [fetchNovel]);

  useEffect(() => {
    if (!novelId) return;
    let active = true;
    Promise.all([insightService.analysis(Number(novelId)), insightService.similar(Number(novelId))])
      .then(([analysis, matches]) => { if (active) { setSignals(analysis.signals || []); setSimilar(matches.results || []); } })
      .catch(() => undefined);
    return () => { active = false; };
  }, [novelId]);

  const handleAddToLibrary = async (targetLibraryId?: number) => {
    if (!novel) return;

    const libraryId = targetLibraryId || activeLibraryId;
    if (!libraryId) {
      addToast("Please select a library first", "warning");
      return;
    }

    setAddingToLibrary(true);
    try {
      const result = await discoveryService.addToLibrary(libraryId, novel.source_url);
      addToast(`"${novel.title}" added to your library!`, "success");
      navigate(`/library/${libraryId}/novels/${(result as { id: number }).id}`);
    } catch (err) {
      console.error("Failed to add novel:", err);
      addToast("Failed to add novel to library", "error");
    } finally {
      setAddingToLibrary(false);
    }
  };

  const coverImageSrc = novel?.img_url || defaultCoverImage;

  if (loading) {
    return (
      <div className="novel-detail-wrapper">
        <NovelDetailHeroSkeleton />
      </div>
    );
  }

  if (error || !novel) {
    return (
      <div className="library-workspace">
        <div className="discover-error">
          <p>{error || "Novel not found"}</p>
          <button onClick={() => navigate(`/discover/${site}`)}>
            Back to Discover
          </button>
        </div>
      </div>
    );
  }

  const getSiteDisplayName = (siteValue: string | undefined): string => {
    if (!siteValue) return "Unknown";
    const sites: Record<string, string> = {
      royalroad: "Royal Road",
      fanfiction: "FanFiction.Net",
      spacebattles: "SpaceBattles",
      archive: "Archive of Our Own",
      webnovel: "WebNovel",
    };
    return sites[siteValue.toLowerCase()] || siteValue;
  };

  const novelForDetails = {
    ...novel,
    id: novel.id,
    url: novel.source_url,
    library_id: 0,
    metadata_id: novel.id,
    author_site_id: novel.author_id,
    author_id: novel.author_id,
    story_id: null,
    novel_site: novel.novel_site,
    img_url: novel.img_url,
    word_count: novel.word_count,
    reviews: novel.reviews,
    favorites: novel.favorites,
    follows: novel.follows,
    views: novel.views,
    rating: novel.rating,
    publish_date: null,
    updated_date: novel.updated_at,
    chapter_count: novel.chapter_count,
    analyzed_at: null,
    analysis_type: null,
    analyzed_chapter_count: null,
    parsed_at: null,
    created_at: novel.created_at,
    updated_at: novel.updated_at,
    scrape_status: "completed" as const,
    scrape_error: null,
    cover_image: novel.img_url,
    follow_state: "plan_to_read" as const,
    followed_at: null,
  };

  return (
    <div className="novel-detail-wrapper">
      <div
        className="novel-hero novel-hero--enhanced"
        style={{ backgroundImage: `url(${coverImageSrc})` }}
      >
        <button
          className="novel-hero__back"
          onClick={() => navigate(`/discover/${site}`)}
        >
          ← Back to Discover
        </button>
        <div className="novel-hero__cover">
          <img
            src={coverImageSrc}
            alt={`Cover for ${novel.title}`}
            className="novel-hero__image"
            referrerPolicy="no-referrer"
            loading="lazy"
            onError={(e) => {
              (e.target as HTMLImageElement).src = defaultCoverImage;
            }}
          />
        </div>
        <div className="novel-hero__info">
          <div className="novel-hero__eyebrow">
            <span className="novel-site-badge">
              {getSiteDisplayName(novel.novel_site)}
            </span>
          </div>
          <h1 className="novel-hero__title">{novel.title}</h1>
          {novel.author && (
            <p className="novel-hero__author">by {novel.author}</p>
          )}
          {novel.description && (
            <p className="novel-hero__description">{novel.description}</p>
          )}
          <div className="novel-hero__cta-row">
            <button
              onClick={() => handleAddToLibrary()}
              disabled={addingToLibrary}
              className="action-button action-button--primary"
            >
              {addingToLibrary
                ? "Adding..."
                : activeLibraryId
                ? "Add to Library"
                : "Select Library to Add"}
            </button>
            {novel.source_url && (
              <a
                href={novel.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="action-button"
              >
                View on {getSiteDisplayName(novel.novel_site)}
              </a>
            )}
          </div>

          {libraries.length > 1 && (
            <div className="novel-hero__library-select">
              <label htmlFor="library-select">Add to:</label>
              <select
                id="library-select"
                value={activeLibraryId || ""}
                onChange={(e) => {
                  const libId = parseInt(e.target.value, 10);
                  handleAddToLibrary(libId);
                }}
                disabled={addingToLibrary}
              >
                {libraries.map((lib) => (
                  <option key={lib.id} value={lib.id}>
                    {lib.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      <div className="novel-detail-grid">
        <div className="novel-detail-info">
          <NovelDetails novel={novelForDetails} />
        </div>
      </div>
      {(signals.length > 0 || similar.length > 0) && <section className="novel-insights">
        {signals.length > 0 && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">Nexus insights</p><h2>Text signals</h2><p className="novel-insights__notice">Local classifier output. Source genres and tags remain separate.</p><div className="novel-insights__chips">{signals.map((signal) => <span key={`${signal.family}:${signal.value}`} title={`${signal.model_version} · ${(signal.confidence || 0) * 100}% confidence`}>{signal.family.replace(/_/g, " ")}: <strong>{signal.value}</strong></span>)}</div></div>}
        {similar.length > 0 && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">More to explore</p><h2>Similar stories</h2><div className="novel-insights__similar">{similar.map((match) => <button type="button" key={match.novel_id} onClick={() => navigate(`/discover/all/${match.novel_id}`)}><strong>{match.title}</strong><small>{match.author || "Unknown author"} · {match.explanation}</small></button>)}</div></div>}
      </section>}
    </div>
  );
};

export default DiscoverNovelDetail;
