import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Clock3, Database, ExternalLink, Play, RefreshCw, Search, Server, Sparkles, XCircle } from "lucide-react";
import { CatalogCandidate, CatalogDefinition, CatalogJob, CatalogPreview, CatalogQuery, CatalogSourceCapability, catalogScrapeService } from "../services/catalogScrapeService";
import { discoveryService } from "../services/discoveryService";
import { chapterService } from "../services/chapterService";
import { novelService } from "../services/novelService";
import { FandomInfo } from "../types/discovery";
import { cancelPendingRequests, getUserFacingError, isRequestCancelled } from "../services/apiClient";
import { RequestCoordinator, useAdaptivePolling } from "../services/requestResilience";
import { useLibraryContext } from "../context/useLibraryContext";
import "../styles/scrape-jobs.css";

const labels: Record<string, string> = {
  ranked: "Ranked", top_rated: "Top rated", newest: "Newest", updated: "Recently updated",
  most_reviewed: "Most reviewed", most_favorited: "Most favorited", most_followed: "Most followed",
  genre: "Genre / tag", crossover: "Crossover", search: "Search", feed: "Latest feed", custom_urls: "Custom URL list",
};
const fallbackMedia = [{ value: "all", label: "All media" }, { value: "book", label: "Books" }, { value: "tv", label: "TV" }, { value: "game", label: "Games" }];
const baseQuery = (site = "fanfiction"): CatalogQuery => ({
  version: 2, intent: "newest", mode: "newest", media: site === "fanfiction" ? "book" : site === "webnovel" ? "fanfic" : "all",
  fandom_a: site === "fanfiction" ? "Harry Potter" : "", fandom_a_id: null, fandom_b: "", crossover: false,
  include_genres: [], exclude_genres: [], include_tags: [], exclude_tags: [], content_warnings: [], rating_min: "all", rating_max: "m",
  // Listing feeds such as Royal Road and SpaceBattles do not always publish
  // statistics. Start permissively and let the child metadata import enrich
  // the record instead of silently filtering every otherwise-valid URL.
  language: "English", status: "any", min_words: null, max_words: null, min_reviews: 0, min_favorites: 0,
  min_follows: 0, time_field: "updated", time_range: "all", sort: "updated", limit: 100, max_pages: 40,
  custom_urls: [], search_text: "", source_options: {},
});

const supports = (capability: CatalogSourceCapability | undefined, filter: string) => Boolean(capability?.filters.includes(filter));
const supportsWords = (capability: CatalogSourceCapability | undefined) => supports(capability, "word_count") || supports(capability, "words");
const supportsStatistics = (capability: CatalogSourceCapability | undefined) => (
  supports(capability, "statistics") || Boolean(capability?.local_filters.some((filter) => filter.startsWith("min_")))
);

const ScrapeJobs: React.FC = () => {
  const { activeLibraryId } = useLibraryContext();
  const navigate = useNavigate();
  const [site, setSite] = useState("fanfiction");
  const [query, setQuery] = useState<CatalogQuery>(() => baseQuery());
  const [name, setName] = useState("Harry Potter — Newest stories");
  const [schedule, setSchedule] = useState<number | null>(null);
  const [customSchedule, setCustomSchedule] = useState(1440);
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [definitions, setDefinitions] = useState<CatalogDefinition[]>([]);
  const [job, setJob] = useState<CatalogJob | null>(null);
  const [candidates, setCandidates] = useState<CatalogCandidate[]>([]);
  const [registry, setRegistry] = useState<CatalogSourceCapability[]>([]);
  const [fandoms, setFandoms] = useState<FandomInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<HTMLElement>(null);
  const coordinator = useRef(new RequestCoordinator());
  const capability = useMemo(() => registry.find((item) => item.site === site), [registry, site]);
  const modes = useMemo(() => capability?.modes || [], [capability]);
  const update = <K extends keyof CatalogQuery>(key: K, value: CatalogQuery[K]) => setQuery((current) => ({ ...current, [key]: value }));

  const loadDefinitions = async () => {
    try { setDefinitions(await coordinator.current.run("catalog-definitions", () => catalogScrapeService.definitions())); }
    catch (reason) { if (!isRequestCancelled(reason)) setError(getUserFacingError(reason, "Administrator access is required, or the catalog service is unavailable.")); }
  };
  useEffect(() => {
    void loadDefinitions();
    void coordinator.current.run("catalog-capabilities", () => catalogScrapeService.capabilities())
      .then((value) => { setRegistry(value.sources); setSite(value.default_site || "fanfiction"); })
      .catch((reason) => setError(getUserFacingError(reason, "Catalog capabilities are temporarily unavailable.")));
    return () => cancelPendingRequests("/catalog-scrapes");
  }, []);
  const fandomsSupported = supports(capability, "fandoms");
  useEffect(() => {
    if (!fandomsSupported) { setFandoms([]); return; }
    const timer = window.setTimeout(() => {
      const term = [query.fandom_a, query.fandom_b].filter(Boolean).join(" ");
      void coordinator.current.run(`catalog-fandoms:${site}:${query.media}:${term}`, () => discoveryService.getFandoms(site, term))
        .then((items) => setFandoms(items.filter((item) => !query.media || item.media_type === query.media || item.media_type === "unknown")))
        .catch(() => setFandoms([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [site, fandomsSupported, query.fandom_a, query.fandom_b, query.media]);

  const selectSite = (next: string) => {
    const nextCapability = registry.find((item) => item.site === next);
    const nextQuery = baseQuery(next);
    const firstMode = nextCapability?.modes[0] || "newest";
    nextQuery.intent = firstMode; nextQuery.mode = firstMode;
    setSite(next); setQuery(nextQuery); setPreview(null); setSelected([]);
    setName(`${nextCapability?.name || next} — ${labels[firstMode] || firstMode}`);
  };
  const selectMode = (mode: string) => {
    setQuery((current) => ({ ...current, mode, intent: mode, crossover: mode === "crossover" ? true : current.crossover }));
    setName(`${capability?.name || site} — ${labels[mode] || mode}`);
  };
  const pendingChildren = candidates.some((candidate) => candidate.candidate_status === "import_queued" || candidate.candidate_status === "import_running");
  const refreshJob = async () => {
    if (!job) return;
    try {
      const [nextJob, nextCandidates] = await coordinator.current.run(`catalog-job:${job.id}`, () => Promise.all([catalogScrapeService.job(job.id), catalogScrapeService.candidates(job.id)]));
      setJob(nextJob);
      // A previous local filter explanation must not obscure the linked child
      // import state once a candidate is queued, running, or imported.
      setCandidates(nextCandidates.map((candidate) =>
        candidate.candidate_status === "filtered" || candidate.candidate_status === "ignored"
          ? candidate
          : { ...candidate, skip_reason: undefined },
      ));
    } catch (reason) { if (!isRequestCancelled(reason)) setError(getUserFacingError(reason, "Catalog status is temporarily unavailable; the last successful snapshot remains visible.")); }
  };
  useAdaptivePolling(() => refreshJob(), Boolean(job && (!(["completed", "failed", "cancelled"].includes(job.status)) || pendingChildren)), { activeMs: 3000, visibleIdleMs: 15000, hiddenMs: 30000 });

  const runPreview = async () => {
    setPreviewing(true); setError(null);
    try {
      const value = await coordinator.current.run(`catalog-preview:${site}:${JSON.stringify(query)}`, () => catalogScrapeService.preview(site, query), 0);
      setPreview(value); window.requestAnimationFrame(() => previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (reason) { if (!isRequestCancelled(reason)) setError(getUserFacingError(reason, `Could not preview ${capability?.name || site}.`)); }
    finally { setPreviewing(false); }
  };
  const create = async () => {
    setBusy(true); setError(null);
    try { const result = await catalogScrapeService.create({ name, site, query, schedule_interval_minutes: schedule, enabled: true }); setJob(result.job); await loadDefinitions(); }
    catch (reason) { setError(getUserFacingError(reason, "Could not create this catalog job.")); }
    finally { setBusy(false); }
  };
  const addSelected = async (follow = false, downloads?: number) => {
    if (!activeLibraryId || !selected.length) { setError("Select an active library and one or more candidates first."); return; }
    setBusy(true); setError(null);
    try {
      const novels = await Promise.all(selected.map((url) => discoveryService.addToLibrary(activeLibraryId, url) as Promise<{ id: number }>));
      if (follow) await Promise.all(novels.map((novel) => novelService.updateFollowState(activeLibraryId, novel.id, "plan_to_read")));
      if (downloads) await Promise.all(novels.map((novel) => chapterService.queueChapterDownloads(activeLibraryId, novel.id, downloads)));
      setSelected([]);
    } catch (reason) { setError(getUserFacingError(reason, "Nexus could not complete one or more selected actions.")); }
    finally { setBusy(false); }
  };
  const openCandidate = async (candidate: CatalogCandidate) => {
    if (!activeLibraryId) { setError("Select an active library first."); return; }
    setBusy(true);
    try { const novel = await discoveryService.addToLibrary(activeLibraryId, candidate.source_url) as { id: number }; navigate(`/library/${activeLibraryId}/novels/${novel.id}`); }
    catch (reason) { setError(getUserFacingError(reason, "Could not open this candidate in your library.")); }
    finally { setBusy(false); }
  };
  const loadDefinition = (definition: CatalogDefinition) => {
    setSite(definition.site); setQuery({ ...baseQuery(definition.site), ...definition.query }); setName(definition.name);
    setSchedule(definition.schedule_interval_minutes || null); setPreview(null); window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return <div className="scrape-page">
    <header className="scrape-page__header"><div><h2>Catalog jobs</h2><p>Find stories on a site, add them to your catalog, and keep each site within its request limit.</p></div><button className="scrape-primary" onClick={() => void runPreview()} disabled={busy || previewing || !capability}><Search size={16} /> {previewing ? `Previewing ${capability?.name || "source"}…` : "Preview results"}</button></header>
    {error && <div className="scrape-alert"><XCircle size={17} />{error}</div>}
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">1</span><div><h2>Choose source</h2><p>Every source declares its own modes, filters, request budget, and collection policy.</p></div></div></div><div className="scrape-source-picker">{registry.map((item) => <button key={item.site} className={site === item.site ? "scrape-source-option is-selected" : "scrape-source-option"} onClick={() => selectSite(item.site)}><Database size={18} /><strong>{item.name}</strong><small>{item.rate_limit} · {item.modes.length} modes</small><span>{item.policy || "Catalog adapter"}</span></button>)}</div></section>
    <section className="scrape-source-grid"><article className="scrape-card scrape-source"><div className="scrape-icon scrape-icon--blue"><Database size={20} /></div><div><small>Selected source</small><h2>{capability?.name || "Loading sources…"}</h2><span className="scrape-health"><i /> {capability?.rate_limit || "Checking budget"} · adapter v{capability?.adapter_version || 2}</span></div><Server size={20} className="scrape-source__server" /></article><article className="scrape-card"><small>Import behavior</small><h2>Metadata + chapter manifest</h2><p>Text downloads remain an explicit library action after import.</p></article><article className="scrape-card"><small>Current job</small><h2>{job?.status || "No active job"}</h2><p>{job?.message || "Preview a query to begin."}</p></article></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">2</span><div><h2>Choose job type</h2><p>Only modes supported by {capability?.name || "this source"} are available.</p></div></div></div><div className="scrape-mode-grid">{modes.map((mode) => <button key={mode} className={query.mode === mode ? "scrape-mode is-selected" : "scrape-mode"} onClick={() => selectMode(mode)}><Sparkles size={16} /><span>{labels[mode] || mode}</span></button>)}</div></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">3</span><div><h2>Configure filters</h2><p>Controls are capability-aware. Filters marked Nexus-side are applied after the listing is parsed.</p></div></div></div>
      <div className="scrape-form-grid">
        {Boolean(capability?.media?.length) && <label>Archive / media<select value={query.media} onChange={(event) => update("media", event.target.value)}>{(capability?.media || fallbackMedia).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>}
        {supports(capability, "fandoms") && <label>Fandom A<input list="catalog-fandom-a" value={query.fandom_a} onChange={(event) => update("fandom_a", event.target.value)} placeholder="Type or select a fandom" /><datalist id="catalog-fandom-a">{fandoms.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}{item.story_count ? ` · ${item.story_count.toLocaleString()}` : ""}</option>)}</datalist><small className="scrape-field-note">Type freely when Nexus has not cached this taxonomy value yet.</small></label>}
        {supports(capability, "fandoms") && <label>Fandom B<input list="catalog-fandom-b" value={query.fandom_b} onChange={(event) => update("fandom_b", event.target.value)} placeholder="Optional second fandom" /><datalist id="catalog-fandom-b">{fandoms.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}</option>)}</datalist></label>}
        {supports(capability, "search") && <label>Search text<input value={query.search_text || ""} onChange={(event) => update("search_text", event.target.value)} placeholder="Title, author, or keyword" /></label>}
        {(supports(capability, "genres") || supports(capability, "tags")) && <label>Include genres / tags<input value={query.include_genres.join(", ")} onChange={(event) => update("include_genres", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} placeholder="Fantasy, Adventure" /></label>}
        {(supports(capability, "genres") || supports(capability, "tags")) && <label>Exclude genres / tags<input value={query.exclude_genres.join(", ")} onChange={(event) => update("exclude_genres", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} placeholder="Harem, Romance" /></label>}
        {supports(capability, "content_warnings") && <label>Content warnings<input value={(query.content_warnings || []).join(", ")} onChange={(event) => update("content_warnings", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} placeholder="Graphic Violence, Sensitive Content" /></label>}
        {supports(capability, "rating") && <label>Minimum rating<select value={query.rating_min} onChange={(event) => update("rating_min", event.target.value)}><option value="all">Any rating</option><option value="k">K / General</option><option value="t">T / Teen</option><option value="m">M / Mature</option></select></label>}
        {supports(capability, "status") && <label>Status<select value={query.status} onChange={(event) => update("status", event.target.value)}><option value="any">Any status</option><option value="complete">Complete</option><option value="in_progress">In progress</option></select></label>}
        {supports(capability, "time_range") && <label>Update window<select value={query.time_range} onChange={(event) => update("time_range", event.target.value)}><option value="all">All time</option><option value="24h">Last 24 hours</option><option value="1w">Last week</option><option value="1m">Last month</option><option value="6m">Last 6 months</option><option value="1y">Last year</option></select></label>}
        {supportsWords(capability) && <label>Minimum words<input type="number" min="0" value={query.min_words ?? ""} onChange={(event) => update("min_words", event.target.value ? Number(event.target.value) : null)} /></label>}
        {supportsWords(capability) && <label>Maximum words<input type="number" min="0" value={query.max_words ?? ""} onChange={(event) => update("max_words", event.target.value ? Number(event.target.value) : null)} /></label>}
        {supportsStatistics(capability) && <label>Minimum favorites<input type="number" min="0" value={query.min_favorites} onChange={(event) => update("min_favorites", Number(event.target.value) || 0)} /></label>}
        {supportsStatistics(capability) && <label>Minimum follows<input type="number" min="0" value={query.min_follows} onChange={(event) => update("min_follows", Number(event.target.value) || 0)} /></label>}
        {supportsStatistics(capability) && <label>Minimum reviews<input type="number" min="0" value={query.min_reviews} onChange={(event) => update("min_reviews", Number(event.target.value) || 0)} /></label>}
        <label>Result limit<input type="number" min="1" max="1000" value={query.limit} onChange={(event) => update("limit", Math.min(1000, Math.max(1, Number(event.target.value) || 1)))} /></label>
        <label>Maximum pages<input type="number" min="1" max="40" value={query.max_pages} onChange={(event) => update("max_pages", Math.min(40, Math.max(1, Number(event.target.value) || 1)))} /></label>
      </div>
      {query.mode === "crossover" && supports(capability, "fandoms") && <label className="scrape-check"><input type="checkbox" checked={query.crossover} onChange={(event) => update("crossover", event.target.checked)} /> Use the source’s all-crossovers mode if Fandom B is empty.</label>}
      {query.mode === "custom_urls" && <label className="scrape-custom-urls">Custom URLs<textarea value={(query.custom_urls || []).join("\n")} placeholder={`One ${capability?.name || "source"} URL per line`} onChange={(event) => update("custom_urls", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} /></label>}
    </section>
    <section className="scrape-two-col"><article ref={previewRef} className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">4</span><div><h2>Preview matches</h2><p>{preview ? `${preview.matched_count} ready to import · approximately ${preview.estimated_pages} pages` : "Optional: inspect the first source page before importing."}</p></div></div></div>{preview && <><p className="scrape-help">Request: <code>{preview.source_url}</code></p><p className="scrape-help">Remote: {(preview.filter_provenance?.remote || preview.capabilities.remote_filters).join(", ") || "none"} · Nexus-side: {(preview.filter_provenance?.local || preview.capabilities.local_filters).join(", ") || "none"}</p>{preview.warnings.map((warning) => <p key={warning} className="scrape-warning">{warning}</p>)}{preview.preview.some((item) => item.matched === false) && <p className="scrape-help">{preview.preview.filter((item) => item.matched === false).length} first-page candidates are excluded by the selected filters and are hidden below.</p>}<div className="scrape-table-wrap"><table><thead><tr><th>Story</th><th>Author</th><th>Words</th><th>Rating / status</th><th>Import</th></tr></thead><tbody>{preview.preview.filter((item) => item.matched !== false).map((item) => <tr key={item.source_url}><td><a href={item.source_url} target="_blank" rel="noreferrer"><strong>{item.title || "Source listing entry"}</strong><ExternalLink size={12} /></a><small>{item.source_url}</small></td><td>{item.author || "Pending detail import"}</td><td>{item.word_count?.toLocaleString() || "Pending"}</td><td>{item.status || "Pending"}</td><td>Ready</td></tr>)}</tbody></table></div></>}</article>
      <article className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">5</span><div><h2>Schedule and create</h2><p>All unique URLs returned by this listing are queued for metadata and manifest import. Preview is optional.</p></div></div></div><label>Job name<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="scrape-schedule"><button className={schedule === null ? "is-selected" : ""} onClick={() => setSchedule(null)}><Play size={15} /> Run once</button><button className={schedule === 1440 ? "is-selected" : ""} onClick={() => setSchedule(1440)}><Clock3 size={15} /> Daily</button><button className={schedule !== null && schedule !== 1440 ? "is-selected" : ""} onClick={() => setSchedule(Math.max(15, customSchedule))}><Clock3 size={15} /> Custom</button></div>{schedule !== null && schedule !== 1440 && <label>Repeat every (minutes)<input type="number" min="15" max="10080" value={customSchedule} onChange={(event) => { const value = Math.max(15, Number(event.target.value) || 15); setCustomSchedule(value); setSchedule(value); }} /></label>}<button className="scrape-primary scrape-create" onClick={() => void create()} disabled={busy}><CheckCircle2 size={16} /> {preview ? "Create job from preview" : "Start import without preview"}</button></article></section>
    {job && <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">6</span><div><h2>Job progress</h2><p>{job.message || `${job.status} · retry cycle ${job.retry_cycle || 1}`}</p></div></div><div className="scrape-actions"><button className="scrape-icon-button" onClick={() => void refreshJob()}><RefreshCw size={16} /></button>{["queued", "running"].includes(job.status) && <button className="scrape-secondary" onClick={() => void catalogScrapeService.cancel(job.id).then(setJob)}>Cancel</button>}{["failed", "cancelled"].includes(job.status) && <button className="scrape-secondary" disabled={!job.retryable} title={job.retryable ? "" : "The source rejected this request; Nexus will not retry it automatically."} onClick={() => void catalogScrapeService.retry(job.id).then(setJob)}>{job.retryable ? "Retry" : "Not retryable"}</button>}</div></div><div className="scrape-progress"><div><span style={{ width: `${Math.round(job.progress * 100)}%` }} /></div><strong>{Math.round(job.progress * 100)}%</strong></div><div className="scrape-stats">{Object.entries(job.results || {}).map(([key, value]) => <div key={key}><strong>{value}</strong><small>{key.replace(/_/g, " ")}</small></div>)}</div>{candidates.length > 0 && <><div className="scrape-actions scrape-candidate-bulk"><button className="scrape-primary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected()}>Add to library ({selected.length})</button><button className="scrape-secondary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected(true)}>Follow selected</button><button className="scrape-secondary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected(false, 10)}>Queue next 10</button></div><div className="scrape-table-wrap"><table><thead><tr><th>Select</th><th>Candidate</th><th>Import</th><th>Actions</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.id || item.source_url}><td><input aria-label={`Select ${item.listing_metadata?.title || item.source_url}`} type="checkbox" checked={selected.includes(item.source_url)} disabled={item.candidate_status === "ignored"} onChange={() => setSelected((current) => current.includes(item.source_url) ? current.filter((url) => url !== item.source_url) : [...current, item.source_url])} /></td><td><strong>{item.listing_metadata?.title || item.source_url}</strong><small>{item.source_key || item.site}</small></td><td>{item.skip_reason || item.candidate_status || "pending"}</td><td><div className="scrape-actions"><a href={item.source_url} target="_blank" rel="noreferrer">Source</a><button className="scrape-secondary" disabled={busy || !activeLibraryId} onClick={() => void openCandidate(item)}>Open in library</button></div></td></tr>)}</tbody></table></div></>}</section>}
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><h2>Saved jobs</h2><p>Definitions retain their capability and request snapshot for reproducible retries.</p></div></div>{definitions.length === 0 ? <p className="scrape-help">No saved catalog jobs yet.</p> : <div className="scrape-history">{definitions.map((definition) => <div key={definition.id}><div><strong>{definition.name}</strong><small>{definition.site} · {definition.schedule_interval_minutes ? `every ${definition.schedule_interval_minutes}m` : "run once"} · {definition.enabled ? "enabled" : "paused"}</small></div><div className="scrape-actions"><button className="scrape-secondary" onClick={() => void catalogScrapeService.run(definition.id).then(setJob)}>Run now</button><button className="scrape-secondary" onClick={() => loadDefinition(definition)}>Edit</button><button className="scrape-secondary" onClick={() => void (definition.enabled ? catalogScrapeService.pause(definition.id) : catalogScrapeService.resume(definition.id)).then(loadDefinitions)}> {definition.enabled ? "Pause" : "Resume"}</button><button className="scrape-secondary scrape-danger" onClick={() => void catalogScrapeService.remove(definition.id).then(loadDefinitions)}>Delete</button></div></div>)}</div>}</section>
  </div>;
};

export default ScrapeJobs;
