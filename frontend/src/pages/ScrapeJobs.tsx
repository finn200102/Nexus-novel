import axios from "axios";
import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
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
import {Banner,Button,Dialog} from "../components/ui";
import CatalogActiveWork from "../components/organization/CatalogActiveWork";
import {loadCatalogJobIntent,saveCatalogJobIntent,type BuiltinCatalogIntent} from "../services/catalogJobIntent";
import {readingJournalOperationId} from "../services/readingJournalService";
import CatalogPluginJobs from "../components/organization/CatalogPluginJobs";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";

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

const ScrapeJobsContents: React.FC = () => {
  const { activeLibraryId } = useLibraryContext();
  const navigate = useNavigate();
  const [site, setSite] = useState("fanfiction");
  const [query, setQuery] = useState<CatalogQuery>(() => baseQuery());
  const [name, setName] = useState("Harry Potter — Newest stories");
  const [schedule, setSchedule] = useState<number | null>(null);
  const [customSchedule, setCustomSchedule] = useState(1440);
  const generation=storageGeneration(),mounted=useRef(false),formEpoch=useRef(0),jobEpoch=useRef(0);
  const current=useCallback(()=>mounted.current&&generation===storageGeneration(),[generation]);
  const [editingDefinition,setEditingDefinition]=useState<CatalogDefinition|null>(null),[editingQuery,setEditingQuery]=useState("");
  const [pendingIntent,setPendingIntent]=useState<BuiltinCatalogIntent|null>(loadCatalogJobIntent),[review,setReview]=useState<BuiltinCatalogIntent|null>(null),[notice,setNotice]=useState("");
  const [candidateOffset,setCandidateOffset]=useState(0),[activeDefinition,setActiveDefinition]=useState<CatalogDefinition|null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [scheduleChanged, setScheduleChanged] = useState(false);
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [definitions, setDefinitions] = useState<CatalogDefinition[]>([]);
  const [job, setJob] = useState<CatalogJob | null>(null);
  const [candidates, setCandidates] = useState<CatalogCandidate[]>([]);
  const [sourcesLimited, setSourcesLimited] = useState(false);
  const [registry, setRegistry] = useState<CatalogSourceCapability[]>([]);
  const [fandoms, setFandoms] = useState<FandomInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<HTMLElement>(null);
  const coordinator = useRef(new RequestCoordinator());
  const capability = useMemo(() => registry.find((item) => item.site === site), [registry, site]);
  const modes = useMemo(() => (capability?.modes || []).filter(mode => mode !== "crossover"), [capability]);
  const update = <K extends keyof CatalogQuery>(key: K, value: CatalogQuery[K]) => {
    setPreview(null);
    setQuery((current) => ({ ...current, [key]: value }));
  };
  const updateFandom = (field: "fandom_a" | "fandom_b", value: string) => {
    setPreview(null);
    const match = fandoms.find(item => item.display_name === value);
    const sourceId = Number(match?.external_category_id);
    setQuery(current => ({ ...current, [field]: value,
      ...(field === "fandom_a" ? { fandom_a_id: Number.isInteger(sourceId) && sourceId > 0 ? sourceId : null } : { crossover: Boolean(value) || current.crossover }) }));
  };

  const loadDefinitions = async () => {
    try { const value=await coordinator.current.run("catalog-definitions", () => catalogScrapeService.definitions()); if(current())setDefinitions(value); }
    catch (reason) { if (current()&&!isRequestCancelled(reason)) setError(getUserFacingError(reason, "Administrator access is required, or the catalog service is unavailable.")); }
  };
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;formEpoch.current+=1;jobEpoch.current+=1;};},[]);
  useEffect(()=>{formEpoch.current++;setPreview(null);},[site,query,name,schedule,scheduleChanged,editingId]);
  const refreshPluginCatalog = async () => {
    const [nextDefinitions, nextCapabilities] = await Promise.all([catalogScrapeService.definitions(), catalogScrapeService.capabilities()]);
    setDefinitions(nextDefinitions); setRegistry(nextCapabilities.sources); setSourcesLimited(nextCapabilities.sources_limited === true);
  };
  useEffect(() => {
    // StrictMode intentionally tears down and restarts effects. An aborted
    // coordinator must not be reused by the replacement workspace load.
    const requests = new RequestCoordinator();
    coordinator.current = requests;
    let live = true;
    const generation = storageGeneration();
    const current = () => live && generation === storageGeneration();
    void requests.run("catalog-definitions", () => catalogScrapeService.definitions())
      .then(value => { if (current()) setDefinitions(value); })
      .catch(reason => { if (current() && !isRequestCancelled(reason)) setError(getUserFacingError(reason, "Administrator access is required, or the catalog service is unavailable.")); });
    void requests.run("catalog-capabilities", () => catalogScrapeService.capabilities())
      .then(value => { if (current()) { setRegistry(value.sources); setSourcesLimited(value.sources_limited === true); setSite(value.default_site || "fanfiction"); } })
      .catch(reason => { if (current() && !isRequestCancelled(reason)) setError(getUserFacingError(reason, "Catalog capabilities are temporarily unavailable.")); });
    return () => { live = false; cancelPendingRequests("/catalog-scrapes"); };
  }, []);
  const fandomsSupported = supports(capability, "fandoms");
  useEffect(() => {
    if (!fandomsSupported) { setFandoms([]); return; }
    let live = true;
    const timer = window.setTimeout(() => {
      const term = [query.fandom_a, query.fandom_b].filter(Boolean).join(" ");
      void coordinator.current.run(`catalog-fandoms:${site}:${query.media}:${term}`, () => discoveryService.getFandoms(site, term))
        .then((items) => { if(live&&current())setFandoms(items.filter((item) => !query.media || item.media_type === query.media || item.media_type === "unknown")); })
        .catch(() => { if(live&&current())setFandoms([]); });
    }, 180);
    return () => { live=false; window.clearTimeout(timer); };
  }, [site, fandomsSupported, query.fandom_a, query.fandom_b, query.media,current]);

  const selectSite = (next: string) => {
    const nextCapability = registry.find((item) => item.site === next);
    const nextQuery = baseQuery(next);
    const firstMode = nextCapability?.modes.find(mode => mode !== "crossover") || "newest";
    nextQuery.intent = firstMode; nextQuery.mode = firstMode;
    setSite(next); setQuery(nextQuery); setPreview(null); setSelected([]); setEditingId(null); setEditingDefinition(null); setEditingQuery(""); if (next === "archive") setSchedule(null);
    setName(`${nextCapability?.name || next} — ${labels[firstMode] || firstMode}`);
  };
  const selectMode = (mode: string) => {
    setPreview(null);
    setQuery((current) => ({ ...current, mode, intent: mode }));
    setName(`${capability?.name || site} — ${labels[mode] || mode}`);
  };
  const pendingChildren = candidates.some((candidate) => candidate.candidate_status === "import_queued" || candidate.candidate_status === "import_running");
  const refreshJob = async (offset=candidateOffset,selectedJob=job) => {
    if (!selectedJob) return;
    const token=++jobEpoch.current;
    try {
      const [nextJob,nextCandidates]=await Promise.all([catalogScrapeService.job(selectedJob.id),catalogScrapeService.candidates(selectedJob.id,offset)]);
      if(!current()||token!==jobEpoch.current)return;
      setJob(nextJob);setCandidateOffset(offset);
      setCandidates(nextCandidates.map(candidate=>candidate.candidate_status==="filtered"||candidate.candidate_status==="ignored"?candidate:{...candidate,skip_reason:undefined}));
    }catch(reason){if(current()&&token===jobEpoch.current&&!isRequestCancelled(reason))setError(getUserFacingError(reason,"Catalog status is temporarily unavailable; the last successful snapshot remains visible."));}
  };
  useAdaptivePolling(()=>refreshJob(),Boolean(job&&(["queued","running","retry_wait"].includes(job.status)||pendingChildren)),{activeMs:3000,visibleIdleMs:15000,hiddenMs:30000});
  const runPreview = async () => {
    const token=++formEpoch.current;setPreviewing(true);setError(null);
    try{const value=await catalogScrapeService.preview(site,query);if(current()&&token===formEpoch.current){setPreview(value);window.requestAnimationFrame(()=>previewRef.current?.scrollIntoView({behavior:"smooth",block:"start"}));}}
    catch(reason){if(current()&&token===formEpoch.current&&!isRequestCancelled(reason))setError(getUserFacingError(reason,`Could not preview ${capability?.name||site}.`));}
    finally{if(current())setPreviewing(false);}
  };
  const executeIntent=async(original:BuiltinCatalogIntent)=>{
    if(busy||!current())return;setBusy(true);setError(null);
    let intent=original;
    try{
      saveCatalogJobIntent(intent);setPendingIntent(intent);let id=intent.acknowledged_id;
      if(!id){if(intent.kind==="create"){const response=await catalogScrapeService.create(intent.body);id=response.definition.id;}else{if(intent.kind==="update")await catalogScrapeService.update(intent.id,intent.body);else if(intent.kind==="run")await catalogScrapeService.run(intent.id,intent.body);else if(intent.kind==="pause")await catalogScrapeService.pause(intent.id,intent.body);else if(intent.kind==="resume")await catalogScrapeService.resume(intent.id,intent.body);else await catalogScrapeService.remove(intent.id,intent.body);id=intent.id;}if(!current())return;intent={...intent,acknowledged_id:id};saveCatalogJobIntent(intent);setPendingIntent(intent);}
      let latest:CatalogDefinition|null=null;try{latest=await catalogScrapeService.definition(id);}catch(err){if(!(axios.isAxiosError(err)&&err.response?.status===404))throw err;}if(!current())return;
      if(latest?.last_job_id){const latestJob=await catalogScrapeService.job(latest.last_job_id);if(!current())return;setJob(latestJob);setCandidates([]);setSelected([]);setCandidateOffset(0);}else setJob(null);
      const latestDefinitions=await catalogScrapeService.definitions();if(!current())return;setDefinitions(latestDefinitions);saveCatalogJobIntent(null);setPendingIntent(null);setReview(null);setPreview(null);setEditingId(null);setEditingDefinition(null);setEditingQuery("");setNotice(latest?`Action confirmed. Current job “${latest.name}” is ${latest.enabled?"enabled":"paused"}.`:intent.kind==="delete"?"Deletion confirmed. Previously imported stories remain.":"Action confirmed. This catalog job was subsequently removed.");
    }catch(reason){if(!current())return;if(axios.isAxiosError(reason)&&reason.response&&[403,409,422].includes(reason.response.status)){try{const latest=await catalogScrapeService.definitions();if(!current())return;setDefinitions(latest);saveCatalogJobIntent(null);setPendingIntent(null);setReview(null);setPreview(null);}catch{/* Keep the original operation until its outcome can be reviewed. */}}setError(getUserFacingError(reason,"The action could not be confirmed. Retry confirmation reuses the original reviewed operation."));}
    finally{if(current())setBusy(false);}
  };
  const queryNeedsReview=editingId===null||editingDefinition?.control_state!=="ready"||JSON.stringify(query)!==editingQuery;
  const create=()=>{
    if(!name.trim()||pendingIntent||queryNeedsReview&&!preview?.review_token)return;
    const operation_id=readingJournalOperationId();
    if(editingId!==null){if(!editingDefinition?.definition_revision)return;setReview({kind:"update",id:editingId,body:{name,expected_revision:editingDefinition.definition_revision,operation_id,...(queryNeedsReview?{query:preview!.query,review_token:preview!.review_token}:{}),...(scheduleChanged?{schedule:null,schedule_interval_minutes:schedule}:{})}});}
    else if(preview?.review_token)setReview({kind:"create",body:{name,site,query:preview.query,schedule_interval_minutes:schedule,enabled:true,review_token:preview.review_token,operation_id}});
  };
  const reviewControl=(definition:CatalogDefinition,kind:"run"|"pause"|"resume"|"delete")=>{if(!definition.definition_revision)return;setReview({kind,id:definition.id,body:{expected_revision:definition.definition_revision,operation_id:readingJournalOperationId()}});};
  const viewSavedRun=async(definition:CatalogDefinition)=>{if(!definition.last_job_id)return;setBusy(true);setCandidates([]);setSelected([]);try{const latest=await catalogScrapeService.job(definition.last_job_id);if(current())await refreshJob(0,latest);}catch(reason){if(current())setError(getUserFacingError(reason,"This run is no longer available."));}finally{if(current())setBusy(false);}};
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
    const loaded = { ...baseQuery(definition.site), ...definition.query };
    if (loaded.mode === "crossover" || loaded.intent === "crossover") {
      loaded.mode = loaded.intent = ({ favorites: "most_favorited", follows: "most_followed", reviews: "most_reviewed" } as Record<string, string>)[loaded.sort] || "newest";
      loaded.crossover = true;
    }
    setSite(definition.site); setQuery(loaded); setName(definition.name); setEditingId(definition.id);setEditingDefinition(definition);setEditingQuery(JSON.stringify(loaded));
    setCustomSchedule(definition.schedule_interval_minutes || 1440);
    setSchedule(definition.schedule_interval_minutes || null); setScheduleChanged(false); setPreview(null); window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const definitionAction = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await action(); if(current())await loadDefinitions(); }
    catch (reason) { setError(getUserFacingError(reason, "Could not update this catalog job.")); }
    finally { if(current())setBusy(false); }
  };

  return <div className="scrape-page">
    <header className="scrape-page__header"><div><h2>Catalog jobs</h2><p>Find stories on a site, add them to your catalog, and keep each site within its request limit.</p></div><button className="scrape-primary" onClick={() => void runPreview()} disabled={busy || !!pendingIntent || previewing || !capability}><Search size={16} /> {previewing ? `Previewing ${capability?.name || "source"}…` : "Preview results"}</button></header>
    {sourcesLimited && <p role="status">This source list is limited. Manage installed packages to find sources not shown here, then refresh package jobs.</p>}
    {(registry.some(item => item.plugin_id || item.site.startsWith("plugin-")) || definitions.some(item => item.site.startsWith("plugin-"))) && <CatalogPluginJobs capabilities={registry} definitions={definitions} onRefresh={refreshPluginCatalog} />}
    {pendingIntent&&<Banner tone="warning" action={<Button disabled={busy} onClick={()=>void executeIntent(pendingIntent)}>Retry catalog job confirmation</Button>}>A reviewed catalog action is awaiting confirmation. Its identity is preserved across reloads.</Banner>}
    {notice&&<Banner tone="success">{notice}</Banner>}
    <Dialog open={!!review} title="Review catalog job action" onClose={()=>{if(!busy)setReview(null);}} actions={<><Button disabled={busy} onClick={()=>setReview(null)}>Cancel</Button><Button disabled={busy||!!pendingIntent} onClick={()=>{if(review)void executeIntent(review);}}>Confirm catalog {review?.kind}</Button></>}>{review&&<><p>{review.kind} {review.kind==="create"?review.body.name:`catalog job ${review.id}`} using the reviewed source settings?</p>{review.kind==="update"&&<p>Saving does not start a run. Existing calendar schedules stay unchanged unless explicitly replaced. Changed criteria reset the checkpoint.</p>}{review.kind==="delete"&&<p>Previously imported stories remain.</p>}</>}</Dialog>
    {error && <div className="scrape-alert"><XCircle size={17} />{error}</div>}
    <fieldset className="scrape-workspace-fields" disabled={busy||!!pendingIntent}><legend className="sr-only">Catalog job settings</legend>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">1</span><div><h2>Choose source</h2><p>Every source declares its own modes, filters, request budget, and collection policy.</p></div></div></div><div className="scrape-source-picker">{registry.filter(item => !item.plugin_id && !item.site.startsWith("plugin-")).map((item) => <button key={item.site} className={site === item.site ? "scrape-source-option is-selected" : "scrape-source-option"} onClick={() => selectSite(item.site)}><Database size={18} /><strong>{item.name}</strong><small>{item.rate_limit} · {item.modes.length} modes</small><span>{item.policy || "Catalog adapter"}</span></button>)}</div></section>
    <section className="scrape-source-grid"><article className="scrape-card scrape-source"><div className="scrape-icon scrape-icon--blue"><Database size={20} /></div><div><small>Selected source</small><h2>{capability?.name || "Loading sources…"}</h2><span className="scrape-health"><i /> {capability?.rate_limit || "Checking budget"} · adapter v{capability?.adapter_version || 2}</span></div><Server size={20} className="scrape-source__server" /></article><article className="scrape-card"><small>Import behavior</small><h2>Metadata + chapter manifest</h2><p>Text downloads remain an explicit library action after import.</p></article><article className="scrape-card"><small>Current job</small><h2>{job?.status || "No active job"}</h2><p>{job?.message || "Preview a query to begin."}</p></article></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">2</span><div><h2>Choose job type</h2><p>Only modes supported by {capability?.name || "this source"} are available.</p></div></div></div><div className="scrape-mode-grid">{modes.map((mode) => <button key={mode} className={query.mode === mode ? "scrape-mode is-selected" : "scrape-mode"} onClick={() => selectMode(mode)}><Sparkles size={16} /><span>{labels[mode] || mode}</span></button>)}</div></section>
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">3</span><div><h2>Configure filters</h2><p>Controls are capability-aware. Filters marked Nexus-side are applied after the listing is parsed.</p></div></div></div>
      {site !== "archive" && <label>Collection scope<select value={query.run_mode || "scheduled_check"} onChange={(event) => { const backfill = event.target.value === "backfill"; setPreview(null); setQuery(current => ({ ...current, run_mode: backfill ? "backfill" : "scheduled_check", max_pages: backfill ? 1000 : 40, top_n: null, daily_request_budget: backfill ? current.daily_request_budget || 300 : null, max_pages_per_run: backfill ? current.max_pages_per_run || 20 : null })); }}><option value="scheduled_check">Check a limited set of listing pages</option><option value="backfill">Walk the archive with a saved checkpoint</option></select></label>}
      {query.run_mode === "backfill" && <div className="scrape-form-grid"><label>Listing requests per day<input type="number" min="1" max="100000" value={query.daily_request_budget || 300} onChange={(event) => update("daily_request_budget", Math.min(100000, Math.max(1, Number(event.target.value) || 1)))} /></label><label>Pages per run<input type="number" min="1" max="1000" value={query.max_pages_per_run || 20} onChange={(event) => update("max_pages_per_run", Math.min(1000, Math.max(1, Number(event.target.value) || 1)))} /></label><p className="scrape-help">Pauses and request limits preserve the next page. Changing filters starts a fresh checkpoint. These limits cover listing requests; child imports also follow the source’s shared request budget.</p></div>}
      <div className="scrape-form-grid">
        {Boolean(capability?.media?.length) && <label>Archive / media<select value={query.media} onChange={(event) => update("media", event.target.value)}>{(capability?.media || fallbackMedia).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>}
        {supports(capability, "fandoms") && <label>Fandom A<input list="catalog-fandom-a" value={query.fandom_a} onChange={(event) => updateFandom("fandom_a", event.target.value)} placeholder="Type or select a fandom" /><datalist id="catalog-fandom-a">{fandoms.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}{item.story_count ? ` · ${item.story_count.toLocaleString()}` : ""}</option>)}</datalist><small className="scrape-field-note">Type freely when Nexus has not cached this taxonomy value yet.</small></label>}
        {supports(capability, "fandoms") && <label>Fandom B<input list="catalog-fandom-b" value={query.fandom_b} onChange={(event) => updateFandom("fandom_b", event.target.value)} placeholder="Optional second fandom" /><datalist id="catalog-fandom-b">{fandoms.slice(0, 100).map((item) => <option key={item.id} value={item.display_name}>{item.media_type}</option>)}</datalist></label>}
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
        <label>Maximum pages<input type="number" min="1" max={query.run_mode === "backfill" ? 1000 : 40} value={query.max_pages} onChange={(event) => update("max_pages", Math.min(query.run_mode === "backfill" ? 1000 : 40, Math.max(1, Number(event.target.value) || 1)))} /></label>
      </div>
      {supports(capability, "crossover") && query.mode !== "custom_urls" && <label className="scrape-check"><input type="checkbox" checked={query.crossover || Boolean(query.fandom_b)} onChange={(event) => { setPreview(null); setQuery(current => ({ ...current, crossover: event.target.checked, fandom_b: event.target.checked ? current.fandom_b : "" })); }} /> Crossovers only — combine with any ranking above. Leave Fandom B empty for all crossovers with Fandom A.</label>}
      {query.mode === "custom_urls" && <label className="scrape-custom-urls">Custom URLs<textarea value={(query.custom_urls || []).join("\n")} placeholder={`One ${capability?.name || "source"} URL per line`} onChange={(event) => update("custom_urls", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} /></label>}
    </section>
    <section className="scrape-two-col"><article ref={previewRef} className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">4</span><div><h2>Preview matches</h2><p>{preview ? `${preview.matched_count} ready to import · approximately ${preview.estimated_pages} pages` : "Preview the current source and criteria before creating or changing a query."}</p></div></div></div>{preview && <><p className="scrape-help">Request: <code>{preview.source_url}</code></p><p className="scrape-help">Remote: {(preview.filter_provenance?.remote || preview.capabilities.remote_filters).join(", ") || "none"} · Nexus-side: {(preview.filter_provenance?.local || preview.capabilities.local_filters).join(", ") || "none"}</p>{preview.warnings.map((warning) => <p key={warning} className="scrape-warning">{warning}</p>)}{preview.preview.some((item) => item.matched === false) && <p className="scrape-help">{preview.preview.filter((item) => item.matched === false).length} first-page candidates are excluded by the selected filters and are hidden below.</p>}<div className="scrape-table-wrap"><table><thead><tr><th>Story</th><th>Author</th><th>Words</th><th>Rating / status</th><th>Import</th></tr></thead><tbody>{preview.preview.filter((item) => item.matched !== false).map((item) => <tr key={item.source_url}><td><a href={item.source_url} target="_blank" rel="noreferrer"><strong>{item.title || "Source listing entry"}</strong><ExternalLink size={12} /></a><small>{item.source_url}</small></td><td>{item.author || "Pending detail import"}</td><td>{item.word_count?.toLocaleString() || "Pending"}</td><td>{item.status || "Pending"}</td><td>Ready</td></tr>)}</tbody></table></div></>}</article>
      <article className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">5</span><div><h2>Schedule and create</h2><p>All unique URLs returned by this listing are queued for metadata and manifest import. A reviewed preview is required for a new job or changed source criteria.</p></div></div></div><label>Job name<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="scrape-schedule" hidden={site === "archive"}><button className={schedule === null ? "is-selected" : ""} onClick={() => { setScheduleChanged(true); setSchedule(null); }}><Play size={15} /> Run once</button><button className={schedule === 1440 ? "is-selected" : ""} onClick={() => { setScheduleChanged(true); setSchedule(1440); }}><Clock3 size={15} /> Daily</button><button className={schedule !== null && schedule !== 1440 ? "is-selected" : ""} onClick={() => { setScheduleChanged(true); setSchedule(Math.max(15, customSchedule)); }}><Clock3 size={15} /> Custom</button></div>{schedule !== null && schedule !== 1440 && <label>Repeat every (minutes)<input type="number" min="15" max="10080" value={customSchedule} onChange={(event) => { const value = Math.max(15, Number(event.target.value) || 15); setCustomSchedule(value); setSchedule(value); setScheduleChanged(true); }} /></label>}{editingId !== null && <p className="scrape-help">Editing an existing job. Saving does not launch another run; use Run now in Saved jobs. Existing calendar schedules are kept unless you select a new schedule above.</p>}<button className="scrape-primary scrape-create" onClick={() => void create()} disabled={busy || !!pendingIntent || !capability || !name.trim() || (queryNeedsReview&&!preview?.review_token) || (editingId!==null&&!editingDefinition?.definition_revision)}><CheckCircle2 size={16} /> {editingId !== null ? "Save changes" : "Create job from preview"}</button></article></section>
    </fieldset>
    {activeDefinition&&<CatalogActiveWork key={`${generation}:${activeDefinition.id}`} definitionId={activeDefinition.id} name={activeDefinition.name}/>}
    {job && <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><span className="scrape-step">6</span><div><h2>Job progress</h2><p>{job.message || `${job.status} · retry cycle ${job.retry_cycle || 1}`}</p></div></div><div className="scrape-actions"><button className="scrape-icon-button" aria-label="Refresh catalog run" onClick={() => void refreshJob()}><RefreshCw size={16} /></button>{["queued", "running", "retry_wait"].includes(job.status) && <button className="scrape-secondary" disabled={busy} onClick={() => void definitionAction(async () => setJob(await catalogScrapeService.cancel(job.id)))}>Cancel</button>}{["failed", "cancelled"].includes(job.status) && <button className="scrape-secondary" disabled={!job.retryable} title={job.retryable ? "" : "The source rejected this request; Nexus will not retry it automatically."} onClick={() => void definitionAction(async () => setJob(await catalogScrapeService.retry(job.id)))}>{job.retryable ? "Retry" : "Not retryable"}</button>}</div></div><div className="scrape-progress"><div><span style={{ width: `${Math.round(job.progress * 100)}%` }} /></div><strong>{Math.round(job.progress * 100)}%</strong></div><div className="scrape-stats">{Object.entries(job.results || {}).map(([key, value]) => <div key={key}><strong>{typeof value === "number" || typeof value === "string" ? value : "—"}</strong><small>{key.replace(/_/g, " ")}</small></div>)}</div>{candidates.length > 0 && <><div className="scrape-actions scrape-candidate-bulk"><button className="scrape-primary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected()}>Add to library ({selected.length})</button><button className="scrape-secondary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected(true)}>Follow selected</button><button className="scrape-secondary" disabled={busy || !activeLibraryId || !selected.length} onClick={() => void addSelected(false, 10)}>Queue next 10</button></div><div className="scrape-table-wrap"><table><thead><tr><th>Select</th><th>Candidate</th><th>Import</th><th>Actions</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.id || item.source_url}><td><input aria-label={`Select ${item.listing_metadata?.title || item.source_url}`} type="checkbox" checked={selected.includes(item.source_url)} disabled={item.candidate_status === "ignored"} onChange={() => setSelected((current) => current.includes(item.source_url) ? current.filter((url) => url !== item.source_url) : [...current, item.source_url])} /></td><td><strong>{item.listing_metadata?.title || item.source_url}</strong><small>{item.source_key || item.site}</small></td><td>{item.skip_reason || item.candidate_status || "pending"}</td><td><div className="scrape-actions"><a href={item.source_url} target="_blank" rel="noreferrer">Source</a><button className="scrape-secondary" disabled={busy || !activeLibraryId} onClick={() => void openCandidate(item)}>Open in library</button></div></td></tr>)}</tbody></table></div></>}<p>Candidate page {Math.floor(candidateOffset/100)+1} · {candidates.length} shown. Only this page is selected.</p><div className="scrape-actions"><Button disabled={busy||candidateOffset===0} onClick={()=>{setSelected([]);void refreshJob(Math.max(0,candidateOffset-100));}}>Previous candidates</Button><Button disabled={busy||candidates.length<100} onClick={()=>{setSelected([]);void refreshJob(candidateOffset+100);}}>Try next candidate page</Button></div></section>}
    <section className="scrape-card scrape-section"><div className="scrape-section__heading"><div><h2>Saved jobs</h2><p>Definitions retain their capability and request snapshot for reproducible retries.</p></div></div>{definitions.length === 0 ? <p className="scrape-help">No saved catalog jobs yet.</p> : <div className="scrape-history">{definitions.filter(definition => !definition.site.startsWith("plugin-")).map((definition) => <div key={definition.id}><div><strong>{definition.name}</strong><small>{definition.site} · {definition.schedule_interval_minutes ? `every ${definition.schedule_interval_minutes}m` : definition.schedule ? `${definition.schedule.kind} schedule` : "run once"} · {definition.enabled ? "enabled" : "paused"}</small>{definition.progress && <small>{definition.progress.pages_done} pages checked · next page {definition.progress.next_page} · {definition.progress.items_added} added · {definition.progress.requests_today}{definition.progress.daily_request_budget ? ` / ${definition.progress.daily_request_budget}` : ""} listing requests today</small>}{definition.control_state!=="ready"&&<small>Review source criteria before running or resuming this saved job.</small>}{definition.next_run_at && <small>Next run: {new Date(definition.next_run_at).toLocaleString()}</small>}</div><div className="scrape-actions"><Button disabled={busy||!!pendingIntent} onClick={()=>setActiveDefinition(definition)}>View active work for {definition.name}</Button>{definition.last_job_id&&<Button disabled={busy||!!pendingIntent} onClick={()=>void viewSavedRun(definition)}>View run for {definition.name}</Button>}<button className="scrape-secondary" disabled={busy||!!pendingIntent||!definition.definition_revision||definition.control_state!=="ready"||!definition.enabled} onClick={() => reviewControl(definition,"run")}>Run now</button><button className="scrape-secondary" disabled={busy||!!pendingIntent||!definition.definition_revision} onClick={() => loadDefinition(definition)}>Edit</button><button className="scrape-secondary" disabled={busy||!!pendingIntent||!definition.definition_revision||(!definition.enabled&&definition.control_state!=="ready")} onClick={() => reviewControl(definition,definition.enabled?"pause":"resume")}> {definition.enabled ? "Pause" : "Resume"}</button><button className="scrape-secondary scrape-danger" disabled={busy||!!pendingIntent||!definition.definition_revision} onClick={() => reviewControl(definition,"delete")}>Delete</button></div></div>)}</div>}</section>
  </div>;
};

export default function ScrapeJobs() { const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration); return <ScrapeJobsContents key={generation} />; }
