import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Clock3, Database, Play, RefreshCw, Search, Server, Sparkles, XCircle } from "lucide-react";
import { catalogScrapeService, CatalogCandidate, CatalogDefinition, CatalogJob, CatalogPreview, CatalogQuery } from "../services/catalogScrapeService";
import { discoveryService } from "../services/discoveryService";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import { FandomInfo } from "../types/discovery";
import { cancelPendingRequests, getUserFacingError, isRequestCancelled } from "../services/apiClient";
import { RequestCoordinator, useAdaptivePolling } from "../services/requestResilience";
import { useLibraryContext } from "../context/LibraryContext";
import "../styles/scrape-jobs.css";

const initialQuery: CatalogQuery = { mode: "newest", media: "book", fandom_a: "Harry Potter", fandom_a_id: null, fandom_b: "", crossover: false, include_genres: [], exclude_genres: [], rating_min: "all", rating_max: "m", language: "English", status: "any", min_words: 10000, max_words: null, min_reviews: 0, min_favorites: 0, min_follows: 0, time_field: "updated", time_range: "all", sort: "updated", limit: 100, max_pages: 40 };
const modes = [{ id: "top_rated", label: "Top Rated" }, { id: "newest", label: "Newest Stories" }, { id: "most_reviewed", label: "Most Reviewed" }, { id: "most_favorited", label: "Most Favorited" }, { id: "most_followed", label: "Most Followed" }, { id: "genre", label: "Genre List" }, { id: "crossover", label: "Crossover List" }, { id: "search", label: "Search Query" }, { id: "custom_urls", label: "Custom URL List" }];
const fallbackMedia = [{ value: "anime", label: "Anime/Manga" }, { value: "book", label: "Books" }, { value: "cartoon", label: "Cartoons" }, { value: "comic", label: "Comics" }, { value: "game", label: "Games" }, { value: "misc", label: "Miscellaneous" }, { value: "movie", label: "Movies" }, { value: "play", label: "Plays/Musicals" }, { value: "tv", label: "TV Shows" }];

const ScrapeJobs: React.FC = () => {
  const { activeLibraryId } = useLibraryContext();
  const navigate = useNavigate();
  const [query, setQuery] = useState<CatalogQuery>(initialQuery);
  const [name, setName] = useState("Harry Potter — Newest Stories");
  const [schedule, setSchedule] = useState<number | null>(null);
  const [customSchedule, setCustomSchedule] = useState(240);
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [definitions, setDefinitions] = useState<CatalogDefinition[]>([]);
  const [job, setJob] = useState<CatalogJob | null>(null);
  const [candidates, setCandidates] = useState<CatalogCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<{ rate_limit?: string; filters?: string[]; media?: { value: string; label: string }[] } | null>(null);
  const [fandomOptions, setFandomOptions] = useState<FandomInfo[]>([]);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([]);
  const previewSectionRef = useRef<HTMLElement>(null);
  const coordinatorRef = useRef(new RequestCoordinator());

  const update = (key: keyof CatalogQuery, value: unknown) => setQuery((current) => ({ ...current, [key]: value }));
  const availableModes = useMemo(() => {
    const supported = capabilities && "modes" in capabilities ? (capabilities as { modes?: string[] }).modes : undefined;
    return supported?.length ? modes.filter((mode) => supported.includes(mode.id)) : modes;
  }, [capabilities]);
  const updateMode = (mode: string) => { update("mode", mode); if (mode === "crossover") update("crossover", true); setName(`${query.fandom_a || "Fandom"} — ${modes.find((item) => item.id === mode)?.label || "Catalog"}`); };
  const selectFandomA = (value: string) => {
    const match = fandomOptions.find((item) => item.display_name.toLowerCase() === value.trim().toLowerCase());
    setQuery((current) => ({
      ...current,
      fandom_a: value,
      fandom_a_id: match?.external_category_id ? Number(match.external_category_id) : null,
    }));
  };
  const loadDefinitions = async () => {
    try {
      setDefinitions(await coordinatorRef.current.run("catalog-definitions", () => catalogScrapeService.definitions()));
    } catch (requestError) {
      if (!isRequestCancelled(requestError)) setError(getUserFacingError(requestError, "Administrator access is required, or the catalog service is unavailable."));
    }
  };
  useEffect(() => {
    void loadDefinitions();
    void coordinatorRef.current.run("catalog-capabilities", () => catalogScrapeService.capabilities()).then(setCapabilities).catch(() => undefined);
    return () => cancelPendingRequests("/catalog-scrapes");
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const term = [query.fandom_a, query.fandom_b].filter(Boolean).join(" ").trim();
      void coordinatorRef.current.run(
        `catalog-fandoms:fanfiction:${query.media}:${term}`,
        () => discoveryService.getFandoms("fanfiction", term),
      ).then((items) => setFandomOptions(items.filter((item) => item.media_type === query.media || item.media_type === "unknown"))).catch(() => setFandomOptions([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [query.fandom_a, query.fandom_b, query.media]);
  const hasPendingChildImports = candidates.some((candidate) => candidate.candidate_status === "import_queued");
  useEffect(() => {
    if (!job || (["completed", "failed", "cancelled"].includes(job.status) && !hasPendingChildImports)) return;

    const refreshJob = async () => {
      try {
        const [current, currentCandidates] = await coordinatorRef.current.run(
          `catalog-job:${job.id}`,
          () => Promise.all([
            catalogScrapeService.job(job.id),
            catalogScrapeService.candidates(job.id),
          ])
        );
        setJob(current);
        setCandidates(currentCandidates);
      } catch (requestError) {
        if (!isRequestCancelled(requestError)) {
          setError(getUserFacingError(requestError, "Catalog job status is temporarily unavailable. The last successful status remains visible."));
        }
        // Keep the last successful snapshot visible while a background refresh fails.
      }
    };

    void refreshJob();
    return () => cancelPendingRequests(`/catalog-scrapes/jobs/${job.id}`);
  }, [job?.id, job?.status, hasPendingChildImports]);

  useAdaptivePolling(async () => {
    if (!job || ( ["completed", "failed", "cancelled"].includes(job.status) && !hasPendingChildImports)) return;
    try {
      const [current, currentCandidates] = await coordinatorRef.current.run(
        `catalog-job:${job.id}`,
        () => Promise.all([
          catalogScrapeService.job(job.id),
          catalogScrapeService.candidates(job.id),
        ])
      );
      setJob(current);
      setCandidates(currentCandidates);
    } catch (requestError) {
      if (!isRequestCancelled(requestError)) setError(getUserFacingError(requestError, "Catalog job status is temporarily unavailable. The last successful status remains visible."));
    }
  }, Boolean(job && (!["completed", "failed", "cancelled"].includes(job.status) || hasPendingChildImports)), {
    activeMs: 3000,
    visibleIdleMs: 15000,
    hiddenMs: 30000,
  });

  const runPreview = async () => {
    setPreviewing(true);
    setError(null);
    try {
      // Catalog workers own retry/backoff. Retrying a browser preview turns one
      // bounded source timeout into a long, apparently stuck UI operation.
      setPreview(await coordinatorRef.current.run(
        `catalog-preview:${JSON.stringify(query)}`,
        () => catalogScrapeService.preview("fanfiction", query),
        0,
      ));
      window.requestAnimationFrame(() => previewSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (requestError) {
      if (!isRequestCancelled(requestError)) setError(getUserFacingError(requestError, "Could not preview FanFiction.net results."));
    } finally {
      setPreviewing(false);
    }
  };
  const createJob = async () => { setBusy(true); setError(null); try { const result = await catalogScrapeService.create({ name, site: "fanfiction", query, schedule_interval_minutes: schedule, enabled: true }); setJob(result.job); await loadDefinitions(); } catch (requestError) { setError(getUserFacingError(requestError, "Could not create catalog job.")); } finally { setBusy(false); } };
  const runDefinition = async (definition: CatalogDefinition) => { try { setJob(await catalogScrapeService.run(definition.id)); } catch (requestError) { setError(getUserFacingError(requestError, "Could not start the saved job.")); } };
  const toggleDefinition = async (definition: CatalogDefinition) => { try { if (definition.enabled) await catalogScrapeService.pause(definition.id); else await catalogScrapeService.resume(definition.id); await loadDefinitions(); } catch (requestError) { setError(getUserFacingError(requestError, "Could not update the saved job.")); } };
  const removeDefinition = async (definition: CatalogDefinition) => { try { await catalogScrapeService.remove(definition.id); await loadDefinitions(); } catch (requestError) { setError(getUserFacingError(requestError, "Could not delete the saved job.")); } };
  const duplicateDefinition = (definition: CatalogDefinition) => {
    setQuery(definition.query);
    setName(`${definition.name} (copy)`);
    setSchedule(definition.schedule_interval_minutes || null);
    setPreview(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const editDefinition = (definition: CatalogDefinition) => {
    setQuery(definition.query);
    setName(definition.name);
    setSchedule(definition.schedule_interval_minutes || null);
    setPreview(null);
    setError("Definition loaded into the editor. Preview it, then create a replacement or update its schedule below.");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const ignoreCandidate = async (candidate: CatalogCandidate) => {
    if (!job || !candidate.id) return;
    try {
      const updated = await catalogScrapeService.ignoreCandidate(job.id, candidate.id);
      setCandidates((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
      setSelectedCandidates((current) => current.filter((url) => url !== candidate.source_url));
    } catch (requestError) { setError(getUserFacingError(requestError, "Could not ignore this candidate.")); }
  };
  const retryChildImport = async (candidate: CatalogCandidate) => {
    if (!candidate.import_job_id) return;
    try { await catalogScrapeService.retry(candidate.import_job_id); } catch (requestError) { setError(getUserFacingError(requestError, "Could not retry the metadata import.")); }
  };
  const toggleCandidate = (sourceUrl: string) => setSelectedCandidates((current) => current.includes(sourceUrl) ? current.filter((url) => url !== sourceUrl) : [...current, sourceUrl]);
  const importSelectedCandidates = async () => {
    if (!activeLibraryId || selectedCandidates.length === 0) { setError("Select a library and at least one candidate first."); return; }
    setBusy(true); setError(null);
    try {
      const novels = await Promise.all(selectedCandidates.map((sourceUrl) => discoveryService.addToLibrary(activeLibraryId, sourceUrl)));
      setSelectedCandidates([]);
      return novels as Array<{ id: number }>;
    } catch (requestError) { setError(getUserFacingError(requestError, "One or more candidates could not be added to the library.")); }
    finally { setBusy(false); }
  };
  const addSelectedToLibrary = async () => { await importSelectedCandidates(); };
  const followSelectedCandidates = async () => {
    const novels = await importSelectedCandidates();
    if (!activeLibraryId || !novels?.length) return;
    try {
      await Promise.all(novels.map((novel) => novelService.updateFollowState(activeLibraryId, novel.id, "plan_to_read")));
    } catch (requestError) { setError(getUserFacingError(requestError, "Stories were imported, but following one or more failed.")); }
  };
  const queueSelectedDownloads = async (count: number) => {
    const novels = await importSelectedCandidates();
    if (!activeLibraryId || !novels?.length) return;
    try {
      await Promise.all(novels.map((novel) => chapterService.queueChapterDownloads(activeLibraryId, novel.id, count)));
    } catch (requestError) { setError(getUserFacingError(requestError, "Stories were imported, but chapter downloads could not be queued yet.")); }
  };
  const openCandidateInLibrary = async (candidate: CatalogCandidate) => {
    if (!activeLibraryId) { setError("Select an active library first."); return; }
    setBusy(true); setError(null);
    try {
      const novel = await discoveryService.addToLibrary(activeLibraryId, candidate.source_url) as { id: number };
      navigate(`/library/${activeLibraryId}/novels/${novel.id}`);
    } catch (requestError) { setError(getUserFacingError(requestError, "Could not open this candidate in your library.")); }
    finally { setBusy(false); }
  };
  const filteredPreview = useMemo(() => preview?.preview || [], [preview]);

  return <div className="scrape-page">
    <header className="scrape-page__header"><div><p className="scrape-eyebrow">Nexus Server · Catalog automation</p><h1>Scrape Jobs</h1><p>Discover, import, and monitor FanFiction.net stories without leaving Nexus.</p></div><button className="scrape-primary" onClick={() => void runPreview()} disabled={busy || previewing} aria-busy={previewing}><Search size={16} /> {previewing ? "Previewing FanFiction.net…" : "Preview results"}</button></header>
    {error && <div className="scrape-alert"><XCircle size={17} />{error}</div>}
    <section className="scrape-source-grid"><article className="scrape-card scrape-source"><div className="scrape-icon scrape-icon--blue"><Database size={20} /></div><div><small>Source</small><h2>FanFiction.net</h2><span className="scrape-health"><i /> Adapter available · {capabilities?.rate_limit || "1 request/sec"}</span></div><Server size={20} className="scrape-source__server" /></article><article className="scrape-card"><small>Import behavior</small><h2>Metadata + chapter manifest</h2><p>Chapter text downloads remain a separate follow-up action.</p></article><article className="scrape-card"><small>Current job</small><h2>{job ? job.status : "No active job"}</h2><p>{job?.message || "Preview a query to begin."}</p></article></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">1</span><div><h2>Choose job type</h2><p>Pick the source listing to scan. Unsupported adapter modes stay hidden.</p></div></div></div><div className="scrape-mode-grid">{availableModes.map((mode) => <button key={mode.id} className={query.mode === mode.id ? "scrape-mode is-selected" : "scrape-mode"} onClick={() => updateMode(mode.id)}><Sparkles size={16} /><span>{mode.label}</span></button>)}</div></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">2</span><div><h2>Configure filters</h2><p>Choose the FanFiction.net archive category first. Type freely for a new fandom, or select a source-verified result.</p></div></div></div><div className="scrape-form-grid"><label>Archive category<select value={query.media} onChange={(e) => update("media", e.target.value)}>{(capabilities?.media || fallbackMedia).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Fandom A<input list="fandom-values-a" value={query.fandom_a} onChange={(e) => selectFandomA(e.target.value)} placeholder="Harry Potter" /><datalist id="fandom-values-a">{fandomOptions.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}{item.story_count ? ` · ${item.story_count.toLocaleString()} stories` : ""}</option>)}</datalist><small className="scrape-field-note">{query.fandom_a_id ? `Source category ID ${query.fandom_a_id}` : "Free-text fallback"}</small></label><label>Fandom B<input list="fandom-values-b" value={query.fandom_b} onChange={(e) => update("fandom_b", e.target.value)} placeholder="Optional crossover" /><datalist id="fandom-values-b">{fandomOptions.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}{item.story_count ? ` · ${item.story_count.toLocaleString()} stories` : ""}</option>)}</datalist></label><label>Include genres<input value={query.include_genres.join(", ")} placeholder="Fantasy, Adventure" onChange={(e) => update("include_genres", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></label><label>Exclude genres<input value={query.exclude_genres.join(", ")} placeholder="Harem, Romance" onChange={(e) => update("exclude_genres", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></label><label>Rating<select value={query.rating_min} onChange={(e) => update("rating_min", e.target.value)}><option value="all">All ratings</option><option value="k">K</option><option value="k+">K+</option><option value="t">T</option><option value="m">M</option></select></label><label>Status<select value={query.status} onChange={(e) => update("status", e.target.value)}><option value="any">Any status</option><option value="complete">Complete</option><option value="in_progress">In progress</option></select></label><label>Minimum words<input type="number" min="0" value={query.min_words ?? ""} onChange={(e) => update("min_words", e.target.value ? Number(e.target.value) : null)} /></label><label>Maximum words<input type="number" min="0" value={query.max_words ?? ""} onChange={(e) => update("max_words", e.target.value ? Number(e.target.value) : null)} /></label><label>Minimum favorites<input type="number" min="0" value={query.min_favorites} onChange={(e) => update("min_favorites", Number(e.target.value))} /></label><label>Minimum follows<input type="number" min="0" value={query.min_follows} onChange={(e) => update("min_follows", Number(e.target.value))} /></label><label>Minimum reviews<input type="number" min="0" value={query.min_reviews} onChange={(e) => update("min_reviews", Number(e.target.value))} /></label><label>Time range<select value={query.time_range} onChange={(e) => update("time_range", e.target.value)}><option value="all">All time</option><option value="24h">24 hours</option><option value="1w">1 week</option><option value="1m">1 month</option><option value="6m">6 months</option><option value="1y">1 year</option></select></label><label>Sort by<select value={query.sort} onChange={(e) => update("sort", e.target.value)}><option value="updated">Updated</option><option value="published">Published</option><option value="reviews">Reviews</option><option value="favorites">Favorites</option><option value="follows">Follows</option></select></label><label>Result limit<input type="number" min="1" max="1000" value={query.limit} onChange={(e) => update("limit", Number(e.target.value))} /></label><label>Maximum pages<input type="number" min="1" max="40" value={query.max_pages} onChange={(e) => update("max_pages", Number(e.target.value))} /></label></div><label className="scrape-check"><input type="checkbox" checked={query.crossover} onChange={(e) => update("crossover", e.target.checked)} /> Crossover between fandom A and fandom B in this archive category</label>{query.mode === "custom_urls" && <label className="scrape-custom-urls">Custom URLs<textarea placeholder="One FanFiction.net URL per line" onChange={(e) => update("custom_urls", e.target.value.split("\n").map((x) => x.trim()).filter(Boolean))} /></label>}</section>
    <section className="scrape-two-col"><article ref={previewSectionRef} className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">3</span><div><h2>Preview matches</h2><p>{preview ? `${preview.matched_count} matches on the first page · ${preview.estimated_pages} pages estimated` : "The job is not created until you confirm the preview."}</p></div></div></div>{preview && <><p className="scrape-help">Source request: <code>{preview.source_url}</code></p><p className="scrape-help">Remote filters: {preview.capabilities.remote_filters.join(", ")} · Nexus-side filters: {preview.capabilities.local_filters.join(", ")}</p>{preview.warnings.map((warning) => <p key={warning} className="scrape-warning">{warning}</p>)}<div className="scrape-table-wrap"><table><thead><tr><th>Story</th><th>Author</th><th>Words</th><th>Reviews</th><th>Favs</th><th>Follows</th><th>Status</th></tr></thead><tbody>{filteredPreview.map((item) => <tr key={item.source_url} className={item.matched === false ? "is-filtered" : ""}><td><strong>{item.title || "Untitled"}</strong><small>{item.source_url}</small></td><td>{item.author || "—"}</td><td>{item.word_count?.toLocaleString() || "—"}</td><td>{item.reviews?.toLocaleString() || "—"}</td><td>{item.favorites?.toLocaleString() || "—"}</td><td>{item.follows?.toLocaleString() || "—"}</td><td>{item.matched === false ? item.skip_reason : item.status || "—"}</td></tr>)}</tbody></table></div></>}</article><article className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">4</span><div><h2>Schedule and create</h2><p>Run once now or monitor this query automatically.</p></div></div></div><label>Job name<input value={name} onChange={(e) => setName(e.target.value)} /></label><div className="scrape-schedule"><button className={schedule === null ? "is-selected" : ""} onClick={() => setSchedule(null)}><Play size={15} /> Run once</button><button className={schedule === 1440 ? "is-selected" : ""} onClick={() => setSchedule(1440)}><Clock3 size={15} /> Daily</button><button className={schedule !== null && schedule !== 1440 ? "is-selected" : ""} onClick={() => setSchedule(Math.max(15, customSchedule))}><Clock3 size={15} /> Custom</button></div>{schedule !== null && schedule !== 1440 && <label>Repeat every (minutes)<input type="number" min="15" max="10080" value={customSchedule} onChange={(e) => { const value = Math.max(15, Number(e.target.value) || 15); setCustomSchedule(value); setSchedule(value); }} /></label>}<button className="scrape-primary scrape-create" onClick={() => void createJob()} disabled={!preview || busy}><CheckCircle2 size={16} /> Confirm and create job</button>{preview && <p className="scrape-help">This will enqueue metadata imports for new or changed stories. Existing active imports are deduplicated.</p>}</article></section>
    {job && <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">5</span><div><h2>Job progress</h2><p>{job.message || `${job.status} · retry cycle ${job.retry_cycle || 1}`}</p></div></div><div className="scrape-actions"><button className="scrape-icon-button" onClick={() => void catalogScrapeService.job(job.id).then(setJob)}><RefreshCw size={16} /></button>{["queued", "running"].includes(job.status) && <button className="scrape-secondary" onClick={() => void catalogScrapeService.cancel(job.id).then(setJob)}>Cancel</button>}{["failed", "cancelled"].includes(job.status) && <button className="scrape-secondary" onClick={() => void catalogScrapeService.retry(job.id).then(setJob)}>Retry</button>}</div></div><div className="scrape-progress"><div><span style={{ width: `${Math.round(job.progress * 100)}%` }} /></div><strong>{Math.round(job.progress * 100)}%</strong></div><div className="scrape-stats">{Object.entries(job.results || {}).map(([key, value]) => <div key={key}><strong>{value}</strong><small>{key.replace(/_/g, " ")}</small></div>)}</div>{candidates.length > 0 && <><div className="scrape-actions scrape-candidate-bulk"><button className="scrape-primary" onClick={() => void addSelectedToLibrary()} disabled={busy || selectedCandidates.length === 0 || !activeLibraryId}>Add to library ({selectedCandidates.length})</button><button className="scrape-secondary" onClick={() => void followSelectedCandidates()} disabled={busy || selectedCandidates.length === 0 || !activeLibraryId}>Follow selected</button><button className="scrape-secondary" onClick={() => void queueSelectedDownloads(10)} disabled={busy || selectedCandidates.length === 0 || !activeLibraryId}>Queue next 10</button><button className="scrape-secondary" onClick={() => void queueSelectedDownloads(100)} disabled={busy || selectedCandidates.length === 0 || !activeLibraryId}>Queue next 100</button><small className="scrape-help">Import is idempotent. Queues only request chapter text after the manifest is available.</small></div><div className="scrape-table-wrap"><table><thead><tr><th>Select</th><th>Candidate</th><th>Status</th><th>Actions</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.id || item.source_url}><td><input type="checkbox" checked={selectedCandidates.includes(item.source_url)} disabled={item.candidate_status === "ignored"} onChange={() => toggleCandidate(item.source_url)} aria-label={`Select ${item.listing_metadata?.title || item.source_url}`} /></td><td><strong>{item.listing_metadata?.title || item.source_url}</strong><small>{item.candidate_status || "found"}</small></td><td>{item.skip_reason || item.candidate_status || "pending"}</td><td><div className="scrape-actions"><a href={item.source_url} target="_blank" rel="noreferrer">Open source</a><button className="scrape-secondary" disabled={busy || item.candidate_status === "ignored" || !activeLibraryId} onClick={() => void openCandidateInLibrary(item)}>Open in library</button>{item.import_job_id && item.candidate_status === "import_failed" && <button className="scrape-secondary" onClick={() => void retryChildImport(item)}>Retry import</button>}{!item.import_job_id && item.candidate_status !== "ignored" && <button className="scrape-secondary" onClick={() => void ignoreCandidate(item)}>Ignore</button>}</div></td></tr>)}</tbody></table></div></>}</section>}
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><div><h2>Saved jobs</h2><p>Reusable definitions, schedules, and execution history.</p></div></div></div>{definitions.length === 0 ? <p className="scrape-help">No saved catalog jobs yet.</p> : <div className="scrape-history">{definitions.map((definition) => <div key={definition.id}><div><strong>{definition.name}</strong><small>{definition.site} · {definition.schedule_interval_minutes ? `every ${definition.schedule_interval_minutes}m` : "run once"} · {definition.enabled ? "enabled" : "paused"}{definition.last_run_at ? ` · last run ${new Date(definition.last_run_at).toLocaleString()}` : ""}</small></div><div className="scrape-actions"><button className="scrape-secondary" onClick={() => void runDefinition(definition)}><Play size={14} /> Run now</button><button className="scrape-secondary" onClick={() => editDefinition(definition)}>Edit</button><button className="scrape-secondary" onClick={() => duplicateDefinition(definition)}>Duplicate</button><button className="scrape-secondary" onClick={() => void toggleDefinition(definition)}>{definition.enabled ? "Pause" : "Resume"}</button><button className="scrape-secondary scrape-danger" onClick={() => void removeDefinition(definition)}>Delete</button></div></div>)}</div>}</section>
  </div>;
};

export default ScrapeJobs;
