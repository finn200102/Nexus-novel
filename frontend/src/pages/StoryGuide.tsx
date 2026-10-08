import React, { useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  StoryCitation,
  GuideChapterArticle,
  GuideChapterDossier,
  GuideEntityArticle,
  GuideEntityProfileArticle,
  GuideProjection,
  GuideChanges,
  GuideRelationshipTimeline,
  StoryGuide as StoryGuideData,
  insightService,
} from "../services/insightService";
import { useToast } from "../context/useToast";
import "../styles/novel-detail.css";
import "../styles/story-guide.css";

type GuideTab = "overview" | "characters" | "relationships" | "world" | "timeline" | "chapters";

const GUIDE_TABS: Array<{ id: GuideTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "characters", label: "Characters" },
  { id: "relationships", label: "Relationships" },
  { id: "world", label: "World" },
  { id: "timeline", label: "Timeline" },
  { id: "chapters", label: "Chapters" },
];

const processingStates = new Set(["building", "queued", "running"]);
type ReaderAnchorContextValue = { library_id: number; novel_id: number } | null;
const ReaderAnchorContext = React.createContext<ReaderAnchorContextValue>(null);

const Citations = ({ items, label = "Chapter evidence" }: { items?: StoryCitation[]; label?: string }) => {
  const readerContext = useContext(ReaderAnchorContext);
  if (!items?.length) return <span className="story-guide-page__no-evidence">No cited evidence yet</span>;
  return (
    <details className="story-guide-page__citations">
      <summary>{label} · {items.length}</summary>
      <div className="story-guide-page__evidence-list">
        {items.map((citation, index) => (
          <blockquote key={`${citation.chapter}:${citation.quote}:${index}`}>
            <strong>Chapter {citation.chapter}</strong>
            <span>“{citation.quote}”</span>
            {readerContext ? <Link className="story-guide-page__reader-anchor" to={`/library/${readerContext.library_id}/novels/${readerContext.novel_id}/${citation.chapter}${citation.start_offset !== undefined ? `?offset=${citation.start_offset}` : ""}`}>{citation.anchor_state === "ambiguous" ? "Open cited chapter (repeated passage)" : citation.start_offset !== undefined ? "Open cited passage" : "Open cited chapter"}</Link> : citation.start_offset !== undefined && <small>Reader anchor · character {citation.start_offset + 1}</small>}
            {citation.anchor_state === "ambiguous" && <small>Repeated wording: this citation stays chapter-linked to avoid an incorrect jump.</small>}
            {citation.note && <small>{citation.note}</small>}
          </blockquote>
        ))}
      </div>
    </details>
  );
};

const EvidenceBadge = ({ count }: { count: number }) => (
  <span className={`story-guide-page__evidence-badge${count ? " story-guide-page__evidence-badge--verified" : ""}`}>
    {count ? `${count} cited source${count === 1 ? "" : "s"}` : "Needs evidence"}
  </span>
);

const DossierQuality = ({ chapter }: { chapter: GuideChapterDossier }) => {
  const quality = chapter.dossier?.quality;
  const status = chapter.dossier?.status || quality?.status;
  if (!quality && !status) return null;
  const label = status === "ready" ? "Evidence checked" : status === "partial" ? "Partial evidence" : "Needs stronger evidence";
  const anchors = quality?.exact_anchor_count || quality?.ambiguous_anchor_count
    ? `${quality?.exact_anchor_count || 0} passage anchors${quality?.ambiguous_anchor_count ? ` · ${quality.ambiguous_anchor_count} chapter-linked` : ""}`
    : "No stable passage anchors";
  return <div className="story-guide-page__dossier-quality"><span className={`story-guide-page__dossier-status story-guide-page__dossier-status--${status || "partial"}`}>{label}</span><small>{quality?.assertion_count || 0} facts · {quality?.citation_count || 0} citations · {anchors}</small></div>;
};

const ClaimStatus = ({ reviewState }: { reviewState?: "machine_suggested" | "approved" | "hidden" | "superseded" }) => {
  if (!reviewState || reviewState === "approved") return reviewState === "approved" ? <span className="story-guide-page__claim-status story-guide-page__claim-status--reviewed">Reviewed</span> : null;
  return <span className="story-guide-page__claim-status story-guide-page__claim-status--suggested">Nexus suggestion</span>;
};

const FactCard = ({ title, eyebrow, description, citations, meta, reviewState, qualifiers, children }: { title: string; eyebrow?: string; description?: string; citations?: StoryCitation[]; meta?: string; reviewState?: "machine_suggested" | "approved" | "hidden" | "superseded"; qualifiers?: Record<string, string>; children?: React.ReactNode }) => (
  <article className="story-guide-page__evidence-card">
    <div className="story-guide-page__card-heading">
      <div>
        {eyebrow && <small className="story-guide-page__fact-kind">{eyebrow}</small>}
        <h3>{title}</h3>
      </div>
      <div className="story-guide-page__card-badges"><ClaimStatus reviewState={reviewState} /><EvidenceBadge count={citations?.length || 0} /></div>
    </div>
    {meta && <small className="story-guide-page__fact-meta">{meta}</small>}
    {description && <p>{description}</p>}
    {qualifiers && Object.keys(qualifiers).length > 0 ? <div className="story-guide-page__qualifiers">{Object.entries(qualifiers).map(([name, value]) => <span key={`${name}:${value}`}>{name.replace(/_/g, " ")}: <strong>{value}</strong></span>)}</div> : null}
    {children && <div className="story-guide-page__card-content">{children}</div>}
    <Citations items={citations} />
  </article>
);

const EmptyState = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="story-guide-page__empty-state">
    <span className="story-guide-page__empty-icon">◇</span>
    <div><strong>{title}</strong><p>{children}</p></div>
  </div>
);

/** A source-cited, spoiler-bounded encyclopedia derived exclusively from downloaded chapters. */
const StoryGuide: React.FC = () => {
  const { metadataId } = useParams<{ metadataId: string }>();
  const [searchParams] = useSearchParams();
  const [guide, setGuide] = useState<StoryGuideData | null>(null);
  const [projection, setProjection] = useState<GuideProjection | null>(null);
  const [projectionError, setProjectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [activeTab, setActiveTab] = useState<GuideTab>("overview");
  const [query, setQuery] = useState("");
  const [entityArticle, setEntityArticle] = useState<GuideEntityArticle | null>(null);
  const [entityProfile, setEntityProfile] = useState<GuideEntityProfileArticle | null>(null);
  const [entityArticleLoading, setEntityArticleLoading] = useState(false);
  const [chapterArticle, setChapterArticle] = useState<GuideChapterArticle | null>(null);
  const [chapterArticleLoading, setChapterArticleLoading] = useState(false);
  const [recentChanges, setRecentChanges] = useState<GuideChanges | null>(null);
  const [relationshipTimeline, setRelationshipTimeline] = useState<GuideRelationshipTimeline | null>(null);
  const { addToast } = useToast();
  const id = Number(metadataId);
  const requestedCutoff = useMemo((): number | undefined => {
    const raw = searchParams.get("through_chapter");
    // The backend derives the safe default from the authenticated reader's
    // progress. A URL may only ask for a *lower* cutoff; it is never trusted
    // to reveal a later chapter.
    if (raw === null) return undefined;
    const parsed = Number(raw);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined;
  }, [searchParams]);

  const load = useCallback(async (quiet = false) => {
    if (!Number.isInteger(id) || id < 1) return;
    if (!quiet) setLoading(true);
    try {
      // The V2 projection is the reader-facing contract. The older snapshot is
      // loaded only for queue/rebuild status while it remains API-compatible;
      // it must never replace verified ledger content in the guide.
      const [projectionResult, snapshotResult] = await Promise.allSettled([
        insightService.storyGuideProjection(id, requestedCutoff),
        insightService.storyGuide(id, requestedCutoff),
      ]);
      if (projectionResult.status === "fulfilled" && !projectionResult.value?.unavailable) {
        setProjection(projectionResult.value);
        setProjectionError(null);
      } else {
        setProjection(null);
        setProjectionError("The cited knowledge projection is temporarily unavailable. Your reading and downloaded chapters are unaffected.");
      }
      setGuide(snapshotResult.status === "fulfilled" ? snapshotResult.value : null);
    } catch {
      setGuide(null);
      setProjection(null);
      setProjectionError("The cited knowledge projection is temporarily unavailable. Your reading and downloaded chapters are unaffected.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [id, requestedCutoff]);

  useEffect(() => { void load(); }, [load]);
  const safeThroughChapter = projection?.safe_through_chapter;
  useEffect(() => {
    if (safeThroughChapter === undefined || safeThroughChapter < 1) { setRecentChanges(null); return; }
    // Keep the guide usable with an older Novel API (and lightweight test
    // doubles) while the optional change-feed endpoint rolls out.
    if (typeof insightService.storyGuideChanges !== "function") { setRecentChanges(null); return; }
    let cancelled = false;
    void insightService.storyGuideChanges(id, Math.max(0, safeThroughChapter - 1), safeThroughChapter)
      .then((result) => { if (!cancelled) setRecentChanges(result); })
      .catch(() => { if (!cancelled) setRecentChanges(null); });
    return () => { cancelled = true; };
  }, [id, safeThroughChapter]);
  useEffect(() => {
    if (safeThroughChapter === undefined || safeThroughChapter < 1 || typeof insightService.storyGuideRelationshipTimeline !== "function") { setRelationshipTimeline(null); return; }
    let cancelled = false;
    void insightService.storyGuideRelationshipTimeline(id, safeThroughChapter)
      .then((result) => { if (!cancelled) setRelationshipTimeline(result); })
      .catch(() => { if (!cancelled) setRelationshipTimeline(null); });
    return () => { cancelled = true; };
  }, [id, safeThroughChapter]);
  useEffect(() => {
    if (!processingStates.has(guide?.guide_status || "") && projection?.coverage.state !== "analyzing") return undefined;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [guide?.guide_status, projection?.coverage.state, load]);

  const build = async () => {
    setBuilding(true);
    try {
      const result = await insightService.backfillStoryGuide(id);
      addToast(result.queued ? `Queued ${result.queued} downloaded chapter${result.queued === 1 ? "" : "s"} for analysis.` : "Downloaded chapters are already analyzed or queued.", "success");
      window.setTimeout(() => void load(true), 700);
    } catch {
      addToast("Could not queue the Story Guide. You can try again safely.", "error");
    } finally {
      setBuilding(false);
    }
  };

  const regenerate = async () => {
    setBuilding(true);
    try {
      await insightService.regenerateStoryGuide(id, requestedCutoff);
      addToast("Queued a cited guide rebuild from the downloaded chapters already analyzed.", "success");
      window.setTimeout(() => void load(true), 700);
    } catch {
      addToast("Could not rebuild the cited guide yet. Your chapter evidence is preserved.", "error");
    } finally {
      setBuilding(false);
    }
  };

  const openEntityArticle = async (entityId: string) => {
    setEntityArticleLoading(true);
    try {
      const [articleResult, profileResult] = await Promise.allSettled([
        insightService.storyGuideEntityArticle(id, entityId, requestedCutoff),
        typeof insightService.storyGuideEntityProfile === "function"
          ? insightService.storyGuideEntityProfile(id, entityId, requestedCutoff)
          : Promise.resolve(null),
      ]);
      setEntityArticle(articleResult.status === "fulfilled" ? articleResult.value : null);
      setEntityProfile(profileResult.status === "fulfilled" ? profileResult.value : null);
      if (articleResult.status !== "fulfilled" && profileResult.status !== "fulfilled") throw new Error("guide entity unavailable");
    } catch {
      addToast("This cited article is not available at your current reading position.", "error");
    } finally {
      setEntityArticleLoading(false);
    }
  };

  const openChapterArticle = async (chapter: number) => {
    setChapterArticleLoading(true);
    try {
      const result = await insightService.storyGuideChapterDossier(id, chapter, requestedCutoff);
      setChapterArticle(result);
    } catch {
      addToast("This chapter dossier is not available at your current reading position.", "error");
    } finally {
      setChapterArticleLoading(false);
    }
  };

  const articleCitations = (items: Array<{ chapter: number; preview: string; start_offset?: number; end_offset?: number; anchor_state?: StoryCitation["anchor_state"] }>): StoryCitation[] => items.map((item) => ({ chapter: item.chapter, quote: item.preview, start_offset: item.start_offset, end_offset: item.end_offset, anchor_state: item.anchor_state }));

  const projectedCharacters = useMemo(() => (projection?.characters || []).filter((entity) => `${entity.name} ${entity.aliases.join(" ")}`.toLowerCase().includes(query.trim().toLowerCase())), [projection, query]);
  const projectedWorld = useMemo(() => projection?.world || [], [projection]);
  const projectedDossiers = useMemo(() => (projection?.chapter_dossiers || []).filter((chapter) => `${chapter.chapter} ${chapter.summary.map((item) => item.object).join(" ")} ${chapter.point_of_view.map((item) => item.object).join(" ")} ${chapter.setting.map((item) => item.object).join(" ")}`.toLowerCase().includes(query.trim().toLowerCase())), [projection, query]);
  const projectedTimeline = projection?.timeline || [];
  const evidenceCount = projection?.coverage.citations || 0;
  const coveragePercent = projection?.coverage.analyzed_chapter_count && projection.safe_through_chapter ? Math.min(100, Math.round((projection.coverage.analyzed_chapter_count / projection.safe_through_chapter) * 100)) : 0;

  if (loading) return <div className="novel-insights story-guide-page"><div className="story-guide-page__loading"><span className="story-guide-page__loading-orb">◇</span><strong>Loading your Story Guide</strong><p>Preparing the latest cited knowledge snapshot…</p></div></div>;
  if (!projection) return <div className="novel-insights story-guide-page"><div className="novel-insights__panel story-guide-page__state-panel"><p className="novel-insights__eyebrow">Story encyclopedia</p><h1>Guide temporarily unavailable</h1><p className="novel-insights__notice">{projectionError || "The optional analysis service did not respond. Your reading, downloads, and chapter evidence remain safe."}</p><button className="novel-insights__browse" type="button" onClick={() => void load()}>Try again</button></div></div>;

  return (
    <ReaderAnchorContext.Provider value={projection?.reader_context || null}>
    <div className="novel-insights story-guide-page">
      <header className="novel-insights__panel novel-insights__guide story-guide-page__hero">
        <div className="story-guide-page__hero-copy">
          <p className="novel-insights__eyebrow">Nexus story encyclopedia</p>
          <h1>Story Guide</h1>
          <p className="novel-insights__notice">Verified chapter-cited knowledge through chapter <strong>{projection.safe_through_chapter}</strong>. This private reference stays bounded to your saved reading position.</p>
        </div>
        <div className="story-guide-page__hero-actions">
          <button className="novel-insights__browse" type="button" disabled={building} onClick={() => void build()}>{building ? "Queueing…" : "Analyze downloaded chapters"}</button>
          {projection.coverage.analyzed_chapter_count ? <button className="novel-insights__browse" type="button" disabled={building} onClick={() => void regenerate()}>{building ? "Queueing…" : "Rebuild cited guide"}</button> : null}
          <button className="novel-insights__browse" type="button" onClick={() => void load()}>Refresh</button>
          <Link className="novel-insights__browse" to={`/story-guide/${id}/review`}>Review claims</Link>
          <Link className="novel-insights__browse" to="/discover">Back to Discover</Link>
        </div>
        <div className="story-guide-page__coverage" aria-label="Story Guide coverage">
          <div><span>Evidence snapshot</span><strong>{projection.coverage.state === "degraded" ? "Needs attention" : projection.coverage.state === "analyzing" || processingStates.has(guide?.guide_status || "") ? "Updating" : projection.coverage.state === "ready" ? "Verified snapshot" : "Partial snapshot"}</strong></div>
          <div><span>Chapter dossiers</span><strong>{projection.coverage.validated_dossier_count || 0} of {projection.safe_through_chapter}</strong></div>
          <div><span>Guide evidence</span><strong>{evidenceCount} cited items</strong></div>
          <div><span>Evidence anchors</span><strong>{projection.coverage.ambiguous_anchor_count ? `${projection.coverage.ambiguous_anchor_count} chapter-linked` : coveragePercent ? `${coveragePercent}% covered` : "Awaiting chapters"}</strong></div>
        </div>
      </header>

      {!projection.coverage.analyzed_chapter_count ? <section className="novel-insights__panel"><EmptyState title={projection.safe_through_chapter === 0 ? "Start reading to unlock a spoiler-safe guide" : "Your guide starts with downloaded chapters"}>{projection.safe_through_chapter === 0 ? "Nexus will not reveal analyzed material ahead of your saved reading position. Open a chapter first, then return for a guide bounded to what you have reached." : "Download public chapters first. Nexus will analyze them in the background and keep the resulting guide bounded to what you have read."}</EmptyState></section> : <>
        <nav className="story-guide-page__tabs" aria-label="Story Guide sections">
          {GUIDE_TABS.map((tab) => <button key={tab.id} className={activeTab === tab.id ? "story-guide-page__tab story-guide-page__tab--active" : "story-guide-page__tab"} type="button" onClick={() => setActiveTab(tab.id)}>{tab.label}{tab.id === "characters" && <span>{projection.characters.length}</span>}{tab.id === "relationships" && <span>{projection.relationships.length}</span>}{tab.id === "chapters" && <span>{projection.chapter_dossiers?.length || 0}</span>}</button>)}
        </nav>

        {projection.coverage.state === "degraded" && <section className="story-guide-page__status story-guide-page__status--error"><strong>The latest evidence materialization needs attention.</strong><span>{projection.coverage.stale_reason || "The chapter evidence remains available; retry the rebuild when the analysis service is ready."}</span><button type="button" className="novel-insights__browse" onClick={() => void regenerate()}>Retry rebuild</button></section>}
        {(projection.coverage.state === "analyzing" || processingStates.has(guide?.guide_status || "")) && <section className="story-guide-page__status"><strong>Guide update in progress.</strong><span>New evidence is being checked. This page keeps the last completed snapshot visible while it runs.</span><span className="story-guide-page__status-pulse" aria-hidden="true" /></section>}

        {activeTab !== "overview" && <div className="story-guide-page__toolbar"><label htmlFor="story-guide-search">Search this section</label><input id="story-guide-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={activeTab === "characters" ? "Find a character…" : activeTab === "chapters" ? "Find a chapter, POV, or setting…" : "Filter visible evidence…"} /><button type="button" className="novel-insights__browse" onClick={() => setQuery("")}>Clear</button></div>}

        {activeTab === "overview" && <div className="story-guide-page__section-stack">
          {projection && <section className="novel-insights__panel story-guide-page__overview">
            <div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Evidence-led snapshot</p><h2>What matters at chapter {projection.safe_through_chapter}</h2><p className="story-guide-page__muted">{projection.coverage.state === "partial" ? `Catching up: ${projection.coverage.materialized_chapter_count || 0} of ${projection.coverage.analyzed_chapter_count || 0} analyzed reader-visible chapters are materialized.` : `${projection.coverage.analyzed_chapter_count || 0} reader-visible chapters analyzed · ${projection.coverage.citations} reusable citations.`}</p></div><EvidenceBadge count={projection.coverage.citations} /></div>
            {projection.overview.story_so_far.length ? <div className="story-guide-page__chapter-list">{projection.overview.story_so_far.map((fact) => <FactCard key={fact.id} title={`${fact.subject || "Story"} · ${fact.predicate || "established"}`} eyebrow={fact.state || "cited fact"} description={fact.object} meta={fact.chapter ? `Chapter ${fact.chapter}` : undefined} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : <EmptyState title="No strong story-state facts yet">Nexus will promote only cited facts from downloaded, reader-visible chapters.</EmptyState>}
            {recentChanges?.count ? <div className="story-guide-page__callout"><strong>New in chapter {recentChanges.through_chapter}</strong><p className="story-guide-page__muted">Only cited developments after chapter {recentChanges.from_chapter} are shown.</p><div className="story-guide-page__chapter-list">{Object.values(recentChanges.changes).flat().slice(0, 6).map((fact) => <FactCard key={`recent:${fact.id}`} title={`${fact.subject || "Story"} · ${fact.predicate || "change"}`} description={fact.object} meta={`Chapter ${fact.chapter}`} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div></div> : null}
            {projection.overview.active_threads?.length ? <div className="story-guide-page__callout"><strong>Active arcs and mysteries</strong><div className="story-guide-page__chapter-list">{projection.overview.active_threads.slice(0, 6).map((thread) => <FactCard key={thread.id} title={thread.title} eyebrow={`${thread.kind} · ${thread.status}`} description={thread.latest_development.object} meta={`Chapters ${thread.first_chapter}–${thread.latest_chapter} · ${(thread.confidence * 100).toFixed(0)}% extraction confidence`} citations={thread.evidence} />)}</div></div> : null}
            {projection.overview.story_signals?.length ? <div className="story-guide-page__callout"><strong>Nexus insights from downloaded chapters</strong><p className="story-guide-page__muted">These are local analysis signals, not source tags or facts.</p><div className="novel-insights__chips">{projection.overview.story_signals.slice(0, 16).map((signal) => <span key={`${signal.family}:${signal.label}`} title={`Observed in ${signal.chapter_count} analyzed chapter${signal.chapter_count === 1 ? "" : "s"}; ${(signal.confidence * 100).toFixed(0)}% confidence`}>{signal.family}: <strong>{signal.label}</strong> · ch. {signal.first_seen_chapter}–{signal.last_seen_chapter}</span>)}</div></div> : null}
          </section>}
          <div className="story-guide-page__overview-grid"><section className="novel-insights__panel"><p className="novel-insights__eyebrow">Reader orientation</p><h2>At a glance</h2><div className="story-guide-page__stat-list"><div><span>Cited identities</span><strong>{projection.characters.length}</strong></div><div><span>World entities</span><strong>{projection.world.length}</strong></div><div><span>Relationships</span><strong>{projection.relationships.length}</strong></div><div><span>Active arcs</span><strong>{projection.arcs?.filter((arc) => arc.status !== "resolved").length || 0}</strong></div><div><span>Timeline events</span><strong>{projection.timeline.length}</strong></div><div><span>Needs review</span><strong>{projection.coverage.needs_review}</strong></div></div></section><section className="novel-insights__panel"><p className="novel-insights__eyebrow">Latest evidence</p><h2>Current situation</h2>{projection.chapter_dossiers?.[0] ? <><DossierQuality chapter={projection.chapter_dossiers[0]} />{projection.chapter_dossiers[0].takeaways?.length ? <div className="story-guide-page__chapter-list">{projection.chapter_dossiers[0].takeaways.slice(0, 2).map((takeaway) => <FactCard key={takeaway.id} title="What matters now" eyebrow={takeaway.qualifiers?.importance || "notable"} description={takeaway.object} citations={takeaway.citations} />)}</div> : null}{projection.chapter_dossiers[0].revelations?.length ? <div className="story-guide-page__chapter-list">{projection.chapter_dossiers[0].revelations.slice(0, 2).map((revelation) => <FactCard key={revelation.id} title="Latest revelation" eyebrow={revelation.qualifiers?.reader_only === "true" ? "reader knowledge" : `known to ${revelation.qualifiers?.known_to || "not specified"}`} description={revelation.object} citations={revelation.citations} />)}</div> : null}<FactCard title={`Chapter ${projection.chapter_dossiers[0].chapter}`} description={projection.chapter_dossiers[0].summary[0]?.object || "Evidence is present but no compact recap has passed validation yet."} meta={`${projection.chapter_dossiers[0].point_of_view[0]?.object || "POV not identified"}${projection.chapter_dossiers[0].setting[0]?.object ? ` · ${projection.chapter_dossiers[0].setting[0].object}` : ""}`} citations={projection.chapter_dossiers[0].summary[0]?.citations}><button className="novel-insights__browse story-guide-page__article-action" type="button" disabled={chapterArticleLoading} onClick={() => void openChapterArticle(projection.chapter_dossiers![0].chapter)}>{chapterArticleLoading ? "Opening…" : "Open cited dossier"}</button></FactCard></> : <EmptyState title="No chapter dossier yet">Analyze a downloaded chapter to populate this section.</EmptyState>}</section></div>
          {(projection.arcs?.length || projection.overview.story_so_far.length) ? <div className="story-guide-page__overview-grid"><section className="novel-insights__panel"><p className="novel-insights__eyebrow">Story now</p><h2>Active arcs and mysteries</h2>{projection.arcs?.filter((arc) => arc.status !== "resolved").slice(0, 4).map((arc) => <FactCard key={`arc:${arc.id}`} title={arc.title} eyebrow={`${arc.kind} · ${arc.status}`} description={arc.latest_development.object} reviewState={arc.latest_development.review_state} citations={arc.evidence} />)}</section><section className="novel-insights__panel"><p className="novel-insights__eyebrow">Cited state changes</p><h2>What the story establishes</h2>{projection.overview.story_so_far.slice(0, 8).map((claim) => <FactCard key={claim.id} title={`${claim.subject || "Story"} · ${claim.predicate || "established"}`} eyebrow={claim.state} description={claim.object} reviewState={claim.review_state} qualifiers={claim.qualifiers} citations={claim.citations} />)}</section></div> : null}
        </div>}

        {activeTab === "characters" && <section className="novel-insights__panel novel-insights__guide"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">People in the story</p><h2>Character dossiers</h2></div><span className="story-guide-page__result-count">{projectedCharacters.length} cited identities</span></div>{projectedCharacters.length ? <div className="story-guide-page__character-grid">{projectedCharacters.map((entity) => { const profile = entity.profile; const facts = Object.values(entity.facts || {}).flat(); return <FactCard key={entity.id} title={entity.name} eyebrow={`${entity.kind} · ${entity.review_state === "approved" ? "reviewed" : entity.identity_state}`} meta={`First seen chapter ${entity.first_chapter} · last cited appearance ${entity.last_chapter} · ${entity.mention_count} mention${entity.mention_count === 1 ? "" : "s"}`} reviewState={entity.review_state} citations={entity.citations}>{entity.aliases.length ? <p className="story-guide-page__muted"><b>Approved aliases</b> {entity.aliases.join(" · ")}</p> : null}{profile?.roles?.length ? <p><b>Role</b> {profile.roles.join(" · ")}</p> : null}{profile?.descriptions?.[0] ? <p>{profile.descriptions[0]}</p> : null}{profile?.appearance?.length ? <p className="story-guide-page__muted"><b>Appearance</b> {profile.appearance.join(" · ")}</p> : null}{profile?.personality?.length ? <p className="story-guide-page__muted"><b>Disposition</b> {profile.personality.join(" · ")}</p> : null}{profile?.goals?.length ? <p className="story-guide-page__muted"><b>Goals</b> {profile.goals.join(" · ")}</p> : null}{profile?.status?.length ? <p className="story-guide-page__muted"><b>Known status</b> {profile.status.join(" · ")}</p> : null}{facts.length ? <ul className="story-guide-page__compact-list">{facts.slice(0, 8).map((fact) => <li key={fact.id}>{fact.predicate}: {fact.object} <small>· ch. {fact.chapter}</small></li>)}</ul> : <p className="story-guide-page__muted">Nexus has cited appearances, but not enough evidence for a fuller dossier yet.</p>}<button className="novel-insights__browse story-guide-page__article-action" type="button" disabled={entityArticleLoading} onClick={() => void openEntityArticle(entity.id)}>{entityArticleLoading ? "Opening…" : "Open cited article"}</button></FactCard>; })}</div> : <EmptyState title={query ? "No character matches" : "Profiles need more evidence"}>{query ? "Try another name or clear the search." : "Profiles appear only when downloaded chapters support a useful, cited role, description, goal, or status."}</EmptyState>}{entityArticle && <section className="story-guide-page__entity-article"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Cited entity article</p><h3>{entityArticle.entity.name}</h3></div><button className="novel-insights__browse" type="button" onClick={() => setEntityArticle(null)}>Close</button></div><p className="story-guide-page__muted">Known through chapter {entityArticle.safe_through_chapter} · {entityArticle.entity.mentions.length} cited mentions</p>{entityArticle.claims.length ? <div className="story-guide-page__chapter-list">{entityArticle.claims.map((claim) => <FactCard key={claim.id} title={`${claim.predicate}`} description={claim.object} meta={`Chapter ${claim.chapter} · ${claim.state}`} reviewState={claim.review_state} qualifiers={claim.qualifiers} citations={claim.evidence.map((evidence) => ({ chapter: evidence.chapter, quote: evidence.preview, start_offset: evidence.start_offset, end_offset: evidence.end_offset, anchor_state: evidence.anchor_state }))} />)}</div> : <EmptyState title="No cited claims yet">This identity has mentions, but no stable claim that is safe to present yet.</EmptyState>}</section>}</section>}

        {activeTab === "characters" && entityProfile && <section className="story-guide-page__entity-article"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Cited development history</p><h3>{entityProfile.entity.name}</h3></div><button className="novel-insights__browse" type="button" onClick={() => setEntityProfile(null)}>Close</button></div><p className="story-guide-page__muted">Known through chapter {entityProfile.safe_through_chapter}. Exact same-name appearances may remain separate provisional identities until reviewed; no hidden merge is made.</p>{entityProfile.developments.length ? <div className="story-guide-page__chapter-list">{entityProfile.developments.map((fact) => <FactCard key={`profile:${fact.id}`} title={`${fact.subject} · ${(fact.predicate || "development").replace("character_update:", "")}`} description={fact.object} meta={`Chapter ${fact.chapter} · ${fact.state}`} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : <EmptyState title="No cited development yet">This profile currently has appearances but no state change that passed evidence validation.</EmptyState>}</section>}
        {activeTab === "relationships" && <section className="novel-insights__panel novel-insights__guide"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Connections</p><h2>Evidence-backed relationships</h2><p className="story-guide-page__muted">Follow how trust, conflict, and alliances change across the chapters you have read.</p></div><span className="story-guide-page__result-count">{relationshipTimeline?.timelines.length ?? projection.coverage.relationships} cited connections</span></div>{relationshipTimeline?.timelines.length ? <div className="story-guide-page__relationship-grid">{relationshipTimeline.timelines.map((timeline) => <FactCard key={timeline.id} title={timeline.entities.join(" ↔ ")} eyebrow={timeline.current_state?.predicate?.replace("relationship:", "") || "relationship"} description={timeline.current_state?.object} meta={`Current cited state: ${timeline.current_state?.state || "uncertain"} · ${timeline.developments.length} development${timeline.developments.length === 1 ? "" : "s"}`} citations={timeline.current_state?.citations}>{<ol className="story-guide-page__relationship-developments">{timeline.developments.map((development) => <li key={development.id}><span>Chapter {development.chapter}</span><strong>{development.state}</strong></li>)}</ol>}</FactCard>)}</div> : projection.relationships.length ? <div className="story-guide-page__relationship-grid">{projection.relationships.map((relationship) => <FactCard key={relationship.id} title={`${relationship.subject || "Unknown"} → ${relationship.object || "Unknown"}`} eyebrow={relationship.predicate?.replace("relationship:", "") || "relationship"} meta={`Established in chapter ${relationship.chapter || "?"} · ${relationship.state || "active"}`} reviewState={relationship.review_state} qualifiers={relationship.qualifiers} citations={relationship.citations} />)}</div> : <EmptyState title="No cited relationships yet">Nexus only adds a connection when the downloaded text supplies cited evidence. Uncertain names stay separate until reviewed.</EmptyState>}</section>}

        {activeTab === "world" && <div className="story-guide-page__world-grid"><section className="novel-insights__panel"><p className="novel-insights__eyebrow">World</p><h2>Places, groups, and concepts</h2>{projectedWorld.length ? projectedWorld.map((entity) => <FactCard key={entity.id} title={entity.name} eyebrow={entity.kind} meta={`First seen chapter ${entity.first_chapter} · ${entity.mention_count} cited mention${entity.mention_count === 1 ? "" : "s"}`} reviewState={entity.review_state} citations={entity.citations}>{entity.aliases.length ? <p className="story-guide-page__muted">Also known as {entity.aliases.join(" · ")}</p> : null}<button className="novel-insights__browse story-guide-page__article-action" type="button" disabled={entityArticleLoading} onClick={() => void openEntityArticle(entity.id)}>{entityArticleLoading ? "Opening…" : "Open cited article"}</button></FactCard>) : <EmptyState title="No world entities yet">Locations, factions, items, and concepts will appear as chapter evidence supports them.</EmptyState>}</section><section className="novel-insights__panel"><p className="novel-insights__eyebrow">Reader-safe detail</p><h2>World facts established so far</h2>{projection.assertions.filter((fact) => projectedWorld.some((entity) => entity.id === fact.subject_entity_id)).slice(0, 12).map((fact) => <FactCard key={fact.id} title={`${fact.subject} · ${fact.predicate}`} eyebrow={fact.state} description={fact.object} meta={fact.chapter ? `Chapter ${fact.chapter}` : undefined} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</section>{entityArticle && <section className="story-guide-page__entity-article"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Cited world article</p><h3>{entityArticle.entity.name}</h3></div><button className="novel-insights__browse" type="button" onClick={() => setEntityArticle(null)}>Close</button></div><p className="story-guide-page__muted">Known through chapter {entityArticle.safe_through_chapter} · {entityArticle.entity.mentions.length} cited mentions</p>{entityArticle.claims.length ? <div className="story-guide-page__chapter-list">{entityArticle.claims.map((claim) => <FactCard key={claim.id} title={`${claim.predicate}`} description={claim.object} meta={`Chapter ${claim.chapter} · ${claim.state}`} reviewState={claim.review_state} qualifiers={claim.qualifiers} citations={articleCitations(claim.evidence)} />)}</div> : <EmptyState title="No cited world facts yet">This entry has mentions, but no stable reader-safe claim yet.</EmptyState>}</section>}</div>}

        {activeTab === "timeline" && <section className="novel-insights__panel novel-insights__guide"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Story chronology</p><h2>What has happened</h2></div><span className="story-guide-page__result-count">{projectedTimeline.length} events</span></div>{projectedTimeline.length ? <div className="story-guide-page__timeline">{projectedTimeline.map((event, index) => <div className="story-guide-page__timeline-item" key={event.id}><span className="story-guide-page__timeline-marker">{index + 1}</span><FactCard title={`${event.subject || "Story"} · ${event.predicate || "event"}`} eyebrow={event.state || "narrative order"} description={event.object} meta={event.chapter ? `Chapter ${event.chapter}` : undefined} reviewState={event.review_state} qualifiers={event.qualifiers} citations={event.citations} /></div>)}</div> : <EmptyState title="The timeline is waiting for more synthesis">Rebuild the guide after analyzing chapters to create cited story events.</EmptyState>}</section>}

        {activeTab === "chapters" && <section className="novel-insights__panel novel-insights__guide"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Chapter encyclopedia</p><h2>Recaps, changes, and source evidence</h2></div><span className="story-guide-page__result-count">{projectedDossiers.length} chapters</span></div>{projectedDossiers.length ? <div className="story-guide-page__chapter-list">{projectedDossiers.map((chapter) => <article key={chapter.chapter}><header><div><strong>Chapter {chapter.chapter}</strong><small>{chapter.point_of_view[0]?.object || "POV not identified"}{chapter.setting[0]?.object ? ` · ${chapter.setting[0].object}` : ""}</small></div><EvidenceBadge count={chapter.summary[0]?.citations.length || 0} /></header><DossierQuality chapter={chapter} />{chapter.summary.map((summary) => <FactCard key={summary.id} title="Chapter recap" eyebrow="cited summary" description={summary.object} reviewState={summary.review_state} qualifiers={summary.qualifiers} citations={summary.citations} />)}{chapter.takeaways?.length ? <div className="story-guide-page__chapter-events"><h3>What matters</h3>{chapter.takeaways.map((fact) => <FactCard key={fact.id} title="Reader takeaway" description={fact.object} eyebrow={fact.qualifiers?.importance || "notable"} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{chapter.revelations?.length ? <div className="story-guide-page__chapter-events"><h3>Revelations</h3>{chapter.revelations.map((fact) => <FactCard key={fact.id} title="Newly established" description={fact.object} eyebrow={fact.qualifiers?.reader_only === "true" ? "reader knowledge" : `known to ${fact.qualifiers?.known_to || "not specified"}`} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{Object.entries(chapter.tags).length ? <div className="novel-insights__chips novel-insights__chapter-tags">{Object.entries(chapter.tags).flatMap(([family, tags]) => tags.map((tag) => <span key={tag.id}>{family}: <strong>{tag.object}</strong></span>))}</div> : null}{chapter.scenes.length ? <div className="story-guide-page__chapter-events"><h3>Scenes</h3>{chapter.scenes.map((scene) => <FactCard key={scene.id} title={scene.object || "Scene"} eyebrow={scene.state || "scene"} reviewState={scene.review_state} qualifiers={scene.qualifiers} citations={scene.citations} />)}</div> : null}{chapter.events.length ? <div className="story-guide-page__chapter-events"><h3>Key events</h3>{chapter.events.map((event) => <FactCard key={event.id} title={event.object || "Event"} eyebrow={event.state || "event"} reviewState={event.review_state} qualifiers={event.qualifiers} citations={event.citations} />)}</div> : null}{chapter.consequences?.length ? <div className="story-guide-page__chapter-events"><h3>Consequences and changes</h3>{chapter.consequences.map((fact) => <FactCard key={fact.id} title={fact.predicate === "event_consequence" ? "Consequence" : "Scene change"} description={fact.object} eyebrow={fact.state || "established"} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{chapter.character_updates?.length ? <div className="story-guide-page__chapter-events"><h3>Character updates</h3>{chapter.character_updates.map((fact) => <FactCard key={fact.id} title={`${fact.subject} · ${fact.predicate?.replace("character_update:", "") || "change"}`} description={fact.object} eyebrow={fact.state || "changed"} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{chapter.character_facts.length ? <div className="story-guide-page__chapter-events"><h3>Character facts</h3>{chapter.character_facts.map((fact) => <FactCard key={fact.id} title={`${fact.subject} · ${fact.predicate}`} description={fact.object} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{chapter.world_updates?.length ? <div className="story-guide-page__chapter-events"><h3>World updates</h3>{chapter.world_updates.map((fact) => <FactCard key={fact.id} title={`${fact.subject} · ${fact.predicate?.replace("world_update:", "") || "established"}`} description={fact.object} eyebrow={fact.state || "confirmed"} reviewState={fact.review_state} qualifiers={fact.qualifiers} citations={fact.citations} />)}</div> : null}{chapter.relationships?.length ? <div className="story-guide-page__chapter-events"><h3>Relationship developments</h3>{chapter.relationships.map((relationship) => <FactCard key={relationship.id} title={`${relationship.subject || "Unknown"} · ${relationship.predicate || "relationship"}`} description={relationship.object} reviewState={relationship.review_state} qualifiers={relationship.qualifiers} citations={relationship.citations} />)}</div> : null}{chapter.open_questions?.length ? <div className="story-guide-page__chapter-events"><h3>Open questions</h3>{chapter.open_questions.map((question) => <FactCard key={question.id} title={question.object || "Unresolved question"} eyebrow={question.state || "open thread"} reviewState={question.review_state} qualifiers={question.qualifiers} citations={question.citations} />)}</div> : null}<button className="novel-insights__browse story-guide-page__article-action" type="button" disabled={chapterArticleLoading} onClick={() => void openChapterArticle(chapter.chapter)}>{chapterArticleLoading ? "Opening…" : "Open full cited dossier"}</button></article>)}</div> : <EmptyState title="No chapters match this search">Try a chapter number, title, POV, or location.</EmptyState>}{chapterArticle && <section className="story-guide-page__entity-article"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Chapter evidence file</p><h3>Chapter {chapterArticle.chapter}</h3></div><button className="novel-insights__browse" type="button" onClick={() => setChapterArticle(null)}>Close</button></div><p className="story-guide-page__muted">{chapterArticle.status === "not_yet_read" ? "This chapter is outside your reader-safe guide cutoff." : `${chapterArticle.assertions.length} cited claim${chapterArticle.assertions.length === 1 ? "" : "s"} · ${chapterArticle.dossier?.quality?.citation_count || 0} citation${chapterArticle.dossier?.quality?.citation_count === 1 ? "" : "s"}`}</p>{chapterArticle.assertions.length ? <div className="story-guide-page__chapter-list">{chapterArticle.assertions.map((claim) => <FactCard key={claim.id} title={`${claim.subject} · ${claim.predicate}`} description={claim.object} meta={`Chapter ${claim.chapter} · ${claim.state}`} reviewState={claim.review_state} qualifiers={claim.qualifiers} citations={articleCitations(claim.evidence)} />)}</div> : <EmptyState title="No reader-safe claims available">This dossier is still waiting for analysis or stronger evidence.</EmptyState>}</section>}</section>}
      </>}
    </div>
    </ReaderAnchorContext.Provider>
  );
};

export default StoryGuide;
