import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import defaultCoverImage from "../assets/cover.png";
import { discoveryService } from "../services/discoveryService";
import { useLibraryContext } from "../context/useLibraryContext";
import { useToast } from "../context/useToast";
import { DiscoveredNovel } from "../types/discovery";
import NovelDetails from "../components/novel/NovelDetails";
import { NovelDetailHeroSkeleton } from "../components/common/Skeleton";
import { insightService, CanonicalWork, InsightSignal, SimilarNovel, StoryGuide } from "../services/insightService";
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
  const [canonicalWork, setCanonicalWork] = useState<CanonicalWork | null>(null);
  const [analysisState, setAnalysisState] = useState<string>("not_started");
  const [enriching, setEnriching] = useState(false);
  const [storyGuide, setStoryGuide] = useState<StoryGuide | null>(null);

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
    Promise.all([
      insightService.analysis(Number(novelId)).catch(() => ({ state: "not_started" as const, signals: [] })),
      insightService.similar(Number(novelId)).catch(() => ({ results: [] })),
      insightService.editions(Number(novelId)).catch(() => null),
      // Discovery has no user-specific reading position. Keep the optional
      // guide empty until the work is opened from a library and a safe cutoff
      // can be supplied.
      insightService.storyGuide(Number(novelId), 0).catch(() => null),
    ]).then(([analysis, matches, work, guide]) => {
      if (!active) return;
      setSignals(analysis.signals || []);
      setSimilar(matches.results || []);
      setCanonicalWork(work);
      setStoryGuide(guide);
      setAnalysisState(analysis.state || "not_started");
    });
    return () => { active = false; };
  }, [novelId]);

  const handleEnrich = async () => {
    if (!novelId) return;
    setEnriching(true);
    try {
      const result = await insightService.enqueue(Number(novelId));
      setAnalysisState(result.queued ? "queued" : "completed");
      addToast(result.queued ? "Nexus insights queued in the low-priority local worker." : "Nexus insights are already up to date.", "success");
    } catch {
      addToast("Could not queue local insights. You can try again safely.", "error");
    } finally {
      setEnriching(false);
    }
  };

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
      sufficientvelocity: "Sufficient Velocity",
      questionablequesting: "Questionable Questing",
      scribblehub: "ScribbleHub",
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
      <section className="novel-insights">
        <div className="novel-insights__panel"><p className="novel-insights__eyebrow">Nexus insights</p><h2>Text signals</h2><p className="novel-insights__notice">Local classifier output. Source genres and tags remain separate.</p>{signals.length > 0 ? <div className="novel-insights__chips">{signals.map((signal) => <span key={`${signal.family}:${signal.value}`} title={`${signal.model_version} · ${(signal.confidence || 0) * 100}% confidence`}>{signal.family.replace(/_/g, " ")}: <strong>{signal.value}</strong></span>)}</div> : <div className="novel-insights__empty"><span>{analysisState === "queued" || analysisState === "running" ? "Analysis is running in the low-priority local worker." : "No local text signals yet."}</span><button type="button" className="novel-insights__browse" disabled={enriching || analysisState === "queued" || analysisState === "running"} onClick={() => void handleEnrich()}>{enriching ? "Queueing…" : analysisState === "queued" || analysisState === "running" ? "Analysis queued" : "Generate insights"}</button></div>}</div>
        {similar.length > 0 && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">More to explore</p><h2>Similar stories</h2><div className="novel-insights__similar">{similar.map((match) => <button type="button" key={match.novel_id} onClick={() => navigate(`/discover/all/${match.novel_id}`)}><strong>{match.title}</strong><small>{match.author || "Unknown author"} · {match.explanation}</small></button>)}</div><button type="button" className="novel-insights__browse" onClick={() => navigate(`/discover/all?similar_to=${novel.id}`)}>Browse all similar stories</button></div>}
        {storyGuide && !storyGuide.unavailable && <div className="novel-insights__panel novel-insights__guide"><p className="novel-insights__eyebrow">Story guide</p><h2>Private chapter knowledge</h2>{storyGuide.chapters_analyzed ? <><p className="novel-insights__notice">Built through chapter {storyGuide.through_chapter}; future chapters are excluded.</p><div className="novel-insights__guide-grid"><div><h3>Characters</h3>{storyGuide.characters.slice(0, 6).map((character) => <article key={character.name}><strong>{character.name}</strong><small>{character.roles.join(" · ")} · ch. {character.first_seen_chapter}–{character.last_seen_chapter}</small><p>{character.descriptions[0] || "Mentioned in the analyzed chapters."}</p></article>)}</div><div><h3>Latest recap</h3>{storyGuide.chapters.slice(-2).reverse().map((chapter) => <article key={chapter.chapter}><strong>Chapter {chapter.chapter}: {chapter.title}</strong><p>{chapter.chapter_summary}</p><small>{chapter.point_of_view}{chapter.setting ? ` · ${chapter.setting}` : ""}</small></article>)}</div></div></> : <p className="novel-insights__notice">A Story Guide appears after a public chapter is downloaded and analyzed.</p>}</div>}
        {canonicalWork && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">Editions</p><h2>{canonicalWork.editions.length} linked edition{canonicalWork.editions.length === 1 ? "" : "s"}</h2><p className="novel-insights__notice">Source records and reader state are kept separate. Uncertain chapter mappings remain visible for review.</p><div className="novel-insights__chips">{canonicalWork.editions.map((edition) => <span key={edition.id}>{edition.edition_kind}{edition.language ? ` · ${edition.language}` : ""}</span>)}</div></div>}
      </section>
    </div>
  );
};

export default DiscoverNovelDetail;
