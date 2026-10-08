import React, { useEffect, useState, useCallback } from "react";
import defaultCoverImage from "../assets/cover.png";
import { novelService } from "../services/novelService";
import { chapterService } from "../services/chapterService";
import ChapterList from "../components/novel/ChapterList";
import OfflineControl from "../components/novel/OfflineControl";
import NovelDetails from "../components/novel/NovelDetails";
import { Novel, NovelFollowSettings } from "../types/novel";
import { NovelDetailHeroSkeleton } from "../components/common/Skeleton";
import { useToast } from "../context/useToast";
import { Bell } from "lucide-react";
import { insightService, CanonicalWork, InsightSignal, SimilarNovel, StoryGuide } from "../services/insightService";
import { HideButton } from "../components/organization/HideButton";
import { PersonalPanel } from "../components/organization/PersonalPanel";
import AutoDownloadToggle from "../components/novel/AutoDownloadToggle";
import { ReasonList } from "../components/organization/ReasonList";
import { ShelfPicker } from "../components/organization/ShelfPicker";
import { organizationService } from "../services/organizationService";
import type { Shelf } from "../types/organization";
import "../styles/novel-detail.css";
import "../styles/organization.css";

interface NovelDetailProps {
  novelId: number;
  libraryId: number;
}

const NovelDetail: React.FC<NovelDetailProps> = ({ novelId, libraryId }) => {
  const [novel, setNovel] = useState<Novel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<boolean>(false);
  const [updatingFollow, setUpdatingFollow] = useState(false);
  const [followSettings, setFollowSettings] = useState<NovelFollowSettings | null>(null);
  const [signals, setSignals] = useState<InsightSignal[]>([]);
  const [similar, setSimilar] = useState<SimilarNovel[]>([]);
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [canonicalWork, setCanonicalWork] = useState<CanonicalWork | null>(null);
  const [analysisState, setAnalysisState] = useState<string>("not_started");
  const [enriching, setEnriching] = useState(false);

  useEffect(() => {
    let active = true;
    organizationService.listShelves().then((rows) => active && setShelves(rows)).catch(() => active && setShelves([]));
    return () => {
      active = false;
    };
  }, []);
  const [storyGuide, setStoryGuide] = useState<StoryGuide | null>(null);
  const [buildingGuide, setBuildingGuide] = useState(false);
  // Start at zero so no asynchronous guide request can reveal material before
  // the reader's saved position has loaded.
  const [guideCutoff, setGuideCutoff] = useState(0);
  const { addToast } = useToast();
  const fetchNovel = useCallback(async () => {
    try {
      setLoading(true);
      const [data, settings] = await Promise.all([
        novelService.getNovelById(libraryId, novelId),
        novelService.getFollowSettings(libraryId, novelId),
      ]);

      if (data && typeof data === "object" && "id" in data) {
        setNovel(data);
        setFollowSettings(settings);
      } else {
        console.error("Expected novel object but got:", data);
        setError("Unexpected data format");
      }
    } catch (err) {
      console.error("Failed to fetch novel:", err);
      setError("Failed to load novel details");
    } finally {
      setLoading(false);
    }
  }, [libraryId, novelId]);

  useEffect(() => {
    fetchNovel();
  }, [fetchNovel]);

  useEffect(() => {
    let active = true;
    chapterService.getReadingProgress(novelId)
      .then((progress) => { if (active) setGuideCutoff(Math.max(0, progress?.chapter_number || 0)); })
      .catch(() => { if (active) setGuideCutoff(0); });
    return () => { active = false; };
  }, [novelId]);

  useEffect(() => {
    if (!novel?.metadata_id) return;
    let active = true;
    Promise.all([
      insightService.analysis(novel.metadata_id).catch(() => ({ state: "not_started" as const, signals: [] })),
      insightService.similar(novel.metadata_id).catch(() => ({ results: [] })),
      insightService.editions(novel.metadata_id).catch(() => null),
      insightService.storyGuide(novel.metadata_id, guideCutoff).catch(() => null),
    ]).then(([analysis, matches, work, guide]) => {
      if (!active) return;
      setSignals(analysis.signals || []);
      setSimilar(matches.results || []);
      setCanonicalWork(work);
      setStoryGuide(guide);
      setAnalysisState(analysis.state || "not_started");
    });
    return () => { active = false; };
  }, [novel?.metadata_id, guideCutoff]);

  const handleEnrich = async () => {
    if (!novel?.metadata_id) return;
    setEnriching(true);
    try {
      const result = await insightService.enqueue(novel.metadata_id);
      setAnalysisState(result.queued ? "queued" : "completed");
      addToast(result.queued ? "Nexus insights queued in the low-priority local worker." : "Nexus insights are already up to date.", "success");
    } catch {
      addToast("Could not queue local insights. You can try again safely.", "error");
    } finally {
      setEnriching(false);
    }
  };

  const handleBuildStoryGuide = async () => {
    if (!novel?.metadata_id) return;
    setBuildingGuide(true);
    try {
      const result = await insightService.backfillStoryGuide(novel.metadata_id);
      if (!result.chapter_count) {
        addToast("Download at least one public chapter before building a Story Guide.", "info");
      } else if (result.queued) {
        addToast(`Queued ${result.queued} downloaded chapter${result.queued === 1 ? "" : "s"} for private analysis.`, "success");
      } else {
        addToast("Every downloaded chapter is already in the Story Guide queue or guide.", "info");
      }
    } catch {
      addToast("Could not queue Story Guide analysis. You can try again safely.", "error");
    } finally {
      setBuildingGuide(false);
    }
  };

  const handleRefreshMetadata = async () => {
    try {
      setUpdating(true);
      addToast("Refreshing metadata from server...", "info");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      addToast("Metadata refreshed successfully!", "success");
    } catch (err) {
      console.error("Failed to refresh metadata:", err);
      addToast("Failed to refresh metadata", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleRescrape = async () => {
    try {
      setUpdating(true);
      addToast("Re-scraping novel from source...", "info");

      const updatedNovel = await novelService.rescrapeNovel(libraryId, novelId);

      setNovel(updatedNovel);
      addToast("Re-scrape started! Check status for progress.", "success");
    } catch (err) {
      console.error("Failed to rescrape novel:", err);
      addToast("Failed to rescrape novel", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleCheckStatus = async () => {
    try {
      setUpdating(true);
      addToast("Checking scrape status...", "info");

      const updatedNovel = await novelService.refreshMetadata(libraryId, novelId);

      setNovel(updatedNovel);
      
      if (updatedNovel.scrape_status === "completed") {
        addToast("Scrape completed! Metadata updated.", "success");
      } else if (updatedNovel.scrape_status === "failed") {
        addToast(`Scrape failed: ${updatedNovel.scrape_error || "Unknown error"}`, "error");
      } else {
        addToast("Still scraping... Try again in a few seconds.", "warning");
      }
    } catch (err) {
      console.error("Failed to check status:", err);
      addToast("Failed to check status", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleExportEpub = async () => {
    try {
      addToast("Preparing EPUB from downloaded chapters...", "info");
      const blob = await chapterService.exportNovelEpub(novelId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${(novel?.title || "nexus-novel").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.epub`;
      link.click();
      URL.revokeObjectURL(url);
      addToast("EPUB export downloaded", "success");
    } catch {
      addToast("Download at least one chapter before exporting", "error");
    }
  };

  const updateFollowState = async (
    followState: "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored",
    settings: Partial<NovelFollowSettings> = {},
  ) => {
    try {
      setUpdatingFollow(true);
      const nextSettings: NovelFollowSettings = {
        novel_id: novelId,
        follow_state: followState,
        notification_policy: "immediate",
        notification_count: 1,
        download_policy: "none",
        download_count: 1,
        ...(followSettings || {}),
        ...settings,
      };
      const updatedNovel = await novelService.updateFollowState(libraryId, novelId, followState, nextSettings);
      setNovel(updatedNovel);
      setFollowSettings(nextSettings);
      addToast(
        followState === "reading" ? "Story marked as reading" : `Story marked as ${followState.replace(/_/g, " ")}`,
        "success"
      );
    } catch (err) {
      console.error("Failed to update follow state:", err);
      addToast("Failed to update follow state", "error");
    } finally {
      setUpdatingFollow(false);
    }
  };

  const getScrapeStatusIndicator = () => {
    if (!novel?.scrape_status || novel.scrape_status === "completed") {
      return null;
    }

    if (novel.scrape_status === "pending") {
      return (
        <span className="scrape-status scrape-status--pending" title="Scraping in progress">
          ⏳
        </span>
      );
    }

    if (novel.scrape_status === "failed") {
      return (
        <span className="scrape-status scrape-status--failed" title={novel.scrape_error || "Scrape failed"}>
          ⚠️
        </span>
      );
    }

    return null;
  };

  const coverImageSrc = novel?.img_url || novel?.cover_image || defaultCoverImage;

  return (
    <div>
      {loading && (
        <div className="novel-detail-wrapper">
          <NovelDetailHeroSkeleton />
        </div>
      )}
      {error && <p className="error-message">{error}</p>}
      {!loading && !novel && !error && <p>Novel not found</p>}

      {novel && (
        <div className="novel-detail-wrapper">
          <div 
            className="novel-hero novel-hero--enhanced" 
            style={{ backgroundImage: `url(${coverImageSrc})` }}
          >
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
                  {novel.novel_site ? novel.novel_site.toUpperCase() : "UNKNOWN"}
                </span>
                {getScrapeStatusIndicator()}
              </div>
              <h1 className="novel-hero__title">{novel.title}</h1>
              {novel.author && (
                <p className="novel-hero__author">by {novel.author} <HideButton kind="author" value={novel.author} /></p>
              )}
              {novel.description && (
                <p className="novel-hero__description">{novel.description}</p>
              )}
              <div className="novel-hero__cta-row">
                <label className="follow-state-control">
                  <Bell size={17} aria-hidden="true" />
                  <select
                    value={novel.follow_state}
                    disabled={updatingFollow}
                    onChange={(event) => updateFollowState(event.target.value as "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored")}
                    aria-label="Follow state"
                  >
                    <option value="plan_to_read">Plan to read</option>
                    <option value="reading">Reading</option>
                    <option value="on_hold">On hold</option>
                    <option value="completed">Completed</option>
                    <option value="dropped">Dropped</option>
                    <option value="ignored">Ignored</option>
                  </select>
                </label>
                <label className="follow-state-control">
                  <span>Notify</span>
                  <select
                    value={followSettings?.notification_policy || "immediate"}
                    disabled={updatingFollow}
                    onChange={(event) => updateFollowState(novel.follow_state, { ...(followSettings || { novel_id: novel.id, follow_state: novel.follow_state, download_policy: "none", download_count: 0, notification_count: 1 }), notification_policy: event.target.value as NovelFollowSettings["notification_policy"] })}
                    aria-label="Notification policy"
                  >
                    <option value="immediate">Immediately</option>
                    <option value="daily_digest">Daily digest</option>
                    <option value="weekly_digest">Weekly digest</option>
                    <option value="after_n">After chapter count</option>
                  </select>
                </label>
                {followSettings?.notification_policy === "after_n" && (
                  <label className="follow-state-control">
                    <span>Chapters</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={followSettings.notification_count}
                      disabled={updatingFollow}
                      onChange={(event) => updateFollowState(novel.follow_state, { notification_count: Math.max(1, Number(event.target.value) || 1) })}
                      aria-label="Notify after this many new chapters"
                    />
                  </label>
                )}
                <label className="follow-state-control">
                  <span>Download</span>
                  <select
                    value={followSettings?.download_policy || "none"}
                    disabled={updatingFollow}
                    onChange={(event) => updateFollowState(novel.follow_state, { ...(followSettings || { novel_id: novel.id, follow_state: novel.follow_state, notification_policy: "immediate", notification_count: 1, download_count: 0 }), download_policy: event.target.value as NovelFollowSettings["download_policy"] })}
                    aria-label="Automatic download policy"
                  >
                    <option value="none">No auto-download</option>
                    <option value="next_chapter">Next chapter</option>
                    <option value="next_n">Next N chapters</option>
                  </select>
                </label>
                {followSettings?.download_policy === "next_n" && (
                  <label className="follow-state-control">
                    <span>Batch</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={followSettings.download_count}
                      disabled={updatingFollow}
                      onChange={(event) => updateFollowState(novel.follow_state, { download_count: Math.max(1, Number(event.target.value) || 1) })}
                      aria-label="Number of chapters to auto-download"
                    />
                  </label>
                )}
                <button
                  onClick={handleRescrape}
                  disabled={updating}
                  className="action-button action-button--primary"
                >
                  {updating ? "Re-scraping..." : "Re-scrape Full"}
                </button>
                <button
                  onClick={handleRefreshMetadata}
                  disabled={updating}
                  className="action-button"
                >
                  {updating ? "Refreshing..." : "Refresh Metadata"}
                </button>
                <button onClick={() => void handleExportEpub()} className="action-button" type="button">
                  Export EPUB
                </button>
                {(novel.scrape_status === "pending" || novel.scrape_status === "failed") && (
                  <button
                    onClick={handleCheckStatus}
                    disabled={updating}
                    className="action-button action-button--ghost"
                  >
                    {updating ? "Checking..." : "Check Status"}
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="novel-detail-grid">
            <div className="novel-detail-info">
              <NovelDetails novel={novel} />
              <PersonalPanel novelId={novel.id} />
              <AutoDownloadToggle novelId={novel.id} />
              <section className="organize-panel" aria-labelledby={`shelves-${novel.id}`}>
                <h2 id={`shelves-${novel.id}`}>Shelves</h2>
                <ShelfPicker novelId={novel.id} shelves={shelves} onChanged={setShelves} />
              </section>
            </div>
            <div className="novel-detail-chapters">
              <OfflineControl libraryId={libraryId} novelId={novel.id} />
              <ChapterList novel_id={novel.id} library_id={libraryId} />
            </div>
          </div>
          {novel.metadata_id && <section className="novel-insights" aria-label="Nexus insights">
            <div className="novel-insights__panel"><p className="novel-insights__eyebrow">Nexus insights</p><h2>Text signals</h2><p className="novel-insights__notice">Local, cautious classifier signals. They never replace source facts.</p>{signals.length > 0 ? <div className="novel-insights__chips">{signals.map((signal) => <span key={`${signal.family}:${signal.value}`} title={`${signal.model_version} · ${(signal.confidence || 0) * 100}% confidence`}>{signal.family.replace(/_/g, " ")}: <strong>{signal.value}</strong></span>)}</div> : <div className="novel-insights__empty"><span>{analysisState === "queued" || analysisState === "running" ? "Analysis is running in the low-priority local worker." : "No local text signals yet."}</span><button type="button" className="novel-insights__browse" disabled={enriching || analysisState === "queued" || analysisState === "running"} onClick={() => void handleEnrich()}>{enriching ? "Queueing…" : analysisState === "queued" || analysisState === "running" ? "Analysis queued" : "Generate insights"}</button></div>}</div>
            {similar.length > 0 && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">More to explore</p><h2>Similar stories</h2><div className="novel-insights__similar">{similar.map((match) => <button type="button" key={match.novel_id} onClick={() => window.location.assign(`/discover/all/${match.novel_id}`)}><strong>{match.title}</strong><small>{match.author || "Unknown author"} · {match.explanation}</small><ReasonList reasons={match.reasons} inline /></button>)}</div><button type="button" className="novel-insights__browse" onClick={() => window.location.assign(`/discover/all?similar_to=${novel.id}`)}>Browse all similar stories</button></div>}
            {storyGuide && !storyGuide.unavailable && <div className="novel-insights__panel novel-insights__guide">
              <p className="novel-insights__eyebrow">Story guide</p>
              <h2>Private chapter knowledge</h2>
              {storyGuide.chapters_analyzed ? <>
                <p className="novel-insights__notice">Built through chapter {storyGuide.through_chapter} · {storyGuide.provider === "fixture" ? "local structured extraction" : `citation-validated ${storyGuide.model || "analysis"}`}. Future chapters are excluded.</p>
                <div className="novel-insights__guide-grid">
                  <div><h3>Characters</h3>{storyGuide.characters.slice(0, 6).map((character) => <article key={character.name}><strong>{character.name}</strong><small>{character.roles.join(" · ")} · ch. {character.first_seen_chapter}–{character.last_seen_chapter}</small><p>{character.descriptions[0] || "Mentioned in the analyzed chapters."}</p></article>)}</div>
                  <div><h3>Chapter index</h3>{storyGuide.chapters.slice(-3).reverse().map((chapter) => <article key={chapter.chapter}><strong>Chapter {chapter.chapter}: {chapter.title}</strong><p>{chapter.chapter_summary}</p><small>{chapter.point_of_view}{chapter.setting ? ` · ${chapter.setting}` : ""}</small>{chapter.tags.length > 0 && <div className="novel-insights__chips novel-insights__chapter-tags">{chapter.tags.map((tag) => <span key={`${tag.category}:${tag.label}`}>chapter tag: <strong>{tag.label}</strong></span>)}</div>}</article>)}</div>
                </div>
                <button type="button" className="novel-insights__browse" onClick={() => window.location.assign(`/story-guide/${novel.metadata_id}?through_chapter=${guideCutoff}`)}>Open full Story Guide</button>
              </> : <div className="novel-insights__empty"><span>Build a spoiler-bounded private guide with characters, POV, settings, events, recaps, and chapter tags from your downloaded chapters.</span><button type="button" className="novel-insights__browse" disabled={buildingGuide} onClick={() => void handleBuildStoryGuide()}>{buildingGuide ? "Queueing guide…" : "Analyze downloaded chapters"}</button><button type="button" className="novel-insights__browse" onClick={() => window.location.assign(`/story-guide/${novel.metadata_id}?through_chapter=${guideCutoff}`)}>Open Story Guide</button></div>}
            </div>}
            {canonicalWork && <div className="novel-insights__panel"><p className="novel-insights__eyebrow">Editions</p><h2>{canonicalWork.editions.length} linked edition{canonicalWork.editions.length === 1 ? "" : "s"}</h2><p className="novel-insights__notice">Source records and reading state stay separate; uncertain chapter mappings are never merged automatically.</p><div className="novel-insights__chips">{canonicalWork.editions.map((edition) => <span key={edition.id}>{edition.edition_kind}{edition.language ? ` · ${edition.language}` : ""}</span>)}</div></div>}
          </section>}
        </div>
      )}
    </div>
  );
};

export default NovelDetail;
