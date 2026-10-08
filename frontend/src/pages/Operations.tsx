import React, { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, Download, RefreshCw, Server, XCircle } from "lucide-react";
import { useLibraryContext } from "../context/useLibraryContext";
import { activityService, MetadataJob, OperationsSummary, RefreshSchedule, SourceHealth, SourcePolicySummary } from "../services/activityService";
import { cancelPendingRequests, getUserFacingError, isRequestCancelled } from "../services/apiClient";
import { RequestCoordinator, useAdaptivePolling } from "../services/requestResilience";
import "../styles/operations.css";

const Operations: React.FC = () => {
  const { activeLibrary } = useLibraryContext();
  const activeLibraryId = activeLibrary?.id;
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [schedules, setSchedules] = useState<RefreshSchedule[]>([]);
  const [failedJobs, setFailedJobs] = useState<MetadataJob[]>([]);
  const [sourceHealth, setSourceHealth] = useState<SourceHealth[]>([]);
  const [sourcePolicy, setSourcePolicy] = useState<SourcePolicySummary | null>(null);
  const [showFailureHistory, setShowFailureHistory] = useState(false);
  const [scheduleDraft, setScheduleDraft] = useState({ site: "", interval_minutes: 360, batch_size: 100 });
  const coordinatorRef = React.useRef(new RequestCoordinator());
  const hasSummaryRef = React.useRef(false);

  const load = useCallback(async () => {
    if (activeLibraryId === undefined) {
      setSummary(null);
      setLoading(false);
      return;
    }
    if (!hasSummaryRef.current) setLoading(true);
    try {
      const nextSummary = await coordinatorRef.current.run(
        `operations-summary:${activeLibraryId}`,
        () => activityService.getOperationsSummary(activeLibraryId)
      );
      setSummary(nextSummary);
      hasSummaryRef.current = true;
      setError(null);
    } catch (requestError) {
      if (!isRequestCancelled(requestError)) {
        setError(getUserFacingError(requestError, "Operations data is unavailable. Check the Novel API and metadata server."));
      }
    } finally {
      setLoading(false);
    }
  }, [activeLibraryId]);

  const loadControls = useCallback(async () => {
    try {
      const nextControls = await coordinatorRef.current.run(
        `operations-controls:${showFailureHistory ? "archived" : "failed"}`,
        () => Promise.all([
          activityService.getRefreshSchedules(),
          activityService.getMetadataJobs(showFailureHistory ? "archived" : "failed"),
          activityService.getSourceHealth(),
          activityService.getSourcePolicy(),
        ])
      );
      const [nextSchedules, nextJobs, nextHealth, nextPolicy] = nextControls;
      setSchedules(nextSchedules);
      setFailedJobs(nextJobs);
      setSourceHealth(nextHealth);
      setSourcePolicy(nextPolicy);
    } catch (requestError) {
      if (!isRequestCancelled(requestError)) {
        setError(getUserFacingError(requestError, "Automation controls are unavailable while the metadata service is offline."));
      }
    }
  }, [showFailureHistory]);

  useEffect(() => {
    void load();
    void loadControls();
    return () => cancelPendingRequests("/operations/");
  }, [load, loadControls]);

  useAdaptivePolling(load, Boolean(activeLibrary), { activeMs: 3000, visibleIdleMs: 15000, hiddenMs: 30000 });
  useAdaptivePolling(loadControls, Boolean(activeLibrary), { activeMs: 15000, visibleIdleMs: 15000, hiddenMs: 30000 });

  const createSchedule = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await activityService.createRefreshSchedule({
        site: scheduleDraft.site.trim() || null,
        interval_minutes: scheduleDraft.interval_minutes,
        batch_size: scheduleDraft.batch_size,
        enabled: true,
      });
      setScheduleDraft({ site: "", interval_minutes: 360, batch_size: 100 });
      await loadControls();
    } catch (requestError) {
      setError(getUserFacingError(requestError, "Could not create refresh schedule."));
    }
  };

  const toggleSchedule = async (schedule: RefreshSchedule) => {
    try {
      await activityService.updateRefreshSchedule(schedule.id, { enabled: !schedule.enabled });
      await loadControls();
    } catch (requestError) {
      setError(getUserFacingError(requestError, "Could not update refresh schedule."));
    }
  };

  const runSchedule = async (schedule: RefreshSchedule) => {
    try {
      await activityService.runRefreshSchedule(schedule.id);
      await loadControls();
      await load();
    } catch (requestError) { setError(getUserFacingError(requestError, "Could not run refresh schedule.")); }
  };

  const removeSchedule = async (schedule: RefreshSchedule) => {
    if (!window.confirm(`Delete the ${schedule.site || "global"} refresh schedule?`)) return;
    try {
      await activityService.deleteRefreshSchedule(schedule.id);
      await loadControls();
    } catch (requestError) {
      setError(getUserFacingError(requestError, "Could not delete refresh schedule."));
    }
  };

  const retryJob = async (job: MetadataJob) => {
    try {
      await activityService.retryMetadataJob(job.id);
      await loadControls();
      await load();
    } catch (requestError) {
      setError(getUserFacingError(requestError, `Could not retry job ${job.id}.`));
    }
  };

  const archiveJob = async (job: MetadataJob) => {
    try {
      await activityService.archiveMetadataJob(job.id);
      await loadControls();
      await load();
    } catch (requestError) { setError(getUserFacingError(requestError, `Could not archive job ${job.id}.`)); }
  };

  const archiveAllFailed = async () => {
    try { await activityService.archiveFailedMetadataJobs(); await loadControls(); await load(); }
    catch (requestError) { setError(getUserFacingError(requestError, "Could not archive the failed metadata jobs.")); }
  };

  const resetSource = async (source: SourceHealth) => {
    try {
      await activityService.resetSourceHealth(source.site);
      await loadControls();
      await load();
    } catch (requestError) { setError(getUserFacingError(requestError, `Could not reset ${source.site} health.`)); }
  };

  const jobExplanation = (job: MetadataJob) => {
    const message = (job.message || job.error_code || "No failure explanation").replace(/\s+/g, " ");
    return message.length > 180 ? `${message.slice(0, 177)}…` : message;
  };

  if (!activeLibrary) return <div className="operations-page"><h1>Operations</h1><p className="operations-empty">Select a library to view its automation status.</p></div>;

  const metadataStatus = summary?.metadata_server.status || "unknown";
  const metadataHealth = Object.entries(summary?.source_health || {}).map(([status, count]) => `${count} ${status}`).join(" · ") || "No source health records";
  const attemptLabel = (job: MetadataJob) => job.attempt_count > job.max_attempts
    ? `retry cycle exhausted (${job.attempt_count}/${job.max_attempts} recorded)`
    : `attempt ${job.attempt_count}/${job.max_attempts}`;

  return <div className="operations-page" aria-live="polite">
    <header className="operations-page__header">
      <div><p className="library-workspace__eyebrow">Control center</p><h1>Operations</h1><p>Monitor followed stories, refresh workers, source health, and downloads.</p></div>
      <button type="button" className="operations-refresh" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "is-spinning" : ""} /> Refresh</button>
    </header>
    {error && <div className="operations-alert"><AlertTriangle size={17} /> {error}</div>}
    <section className="operations-grid" aria-label="Operation status">
      <article className="operations-card"><span className="operations-card__icon operations-card__icon--violet"><Activity size={20} /></span><div><small>Followed stories</small><strong>{summary?.followed_stories ?? "—"}</strong><p>{summary?.reading_stories ?? "—"} currently reading</p></div></article>
      <article className="operations-card"><span className="operations-card__icon operations-card__icon--blue"><Database size={20} /></span><div><small>Metadata server</small><strong className={`operations-status operations-status--${metadataStatus}`}>{metadataStatus}</strong><p>{summary?.metadata_server.detail || "Checking readiness…"}</p></div></article>
      <article className="operations-card"><span className="operations-card__icon operations-card__icon--green"><Download size={20} /></span><div><small>Download queue</small><strong>{summary ? summary.downloads.queued + summary.downloads.running : "—"}</strong><p>{summary?.downloads.failed ?? "—"} failed · {summary?.downloads.completed ?? "—"} completed</p></div></article>
      <article className="operations-card"><span className="operations-card__icon operations-card__icon--amber"><Server size={20} /></span><div><small>Source health</small><strong>{metadataHealth}</strong><p>{summary?.source_failures ?? "—"} recorded source failures</p></div></article>
    </section>
    <section className="operations-panels">
      <article className="operations-panel"><header><h2>Metadata worker queue</h2><span><Clock3 size={14} /> {summary?.refresh_schedules ?? 0} schedules</span></header><div className="operations-breakdown"><div><b>{summary?.metadata_jobs.queued ?? 0}</b><small>Queued</small></div><div><b>{summary?.metadata_jobs.running ?? 0}</b><small>Running</small></div><div><b>{summary?.metadata_jobs.failed ?? 0}</b><small>Failed</small></div><div><b>{summary?.metadata_jobs.completed ?? 0}</b><small>Completed</small></div></div></article>
      <article className="operations-panel"><header><h2>Novel download worker</h2><span><Download size={14} /> Automatic downloads</span></header><div className="operations-breakdown"><div><b>{summary?.downloads.queued ?? 0}</b><small>Queued</small></div><div><b>{summary?.downloads.running ?? 0}</b><small>Running</small></div><div><b>{summary?.downloads.failed ?? 0}</b><small>Failed</small></div><div><b>{summary?.downloads.cancelled ?? 0}</b><small>Cancelled</small></div></div></article>
    </section>
    <section className="operations-controls">
      <article className="operations-panel">
        <header><h2>Refresh schedules</h2><span>{schedules.length} configured</span></header>
        <form className="operations-schedule-form" onSubmit={createSchedule}>
          <input aria-label="Source site" placeholder="Source site or all sources" value={scheduleDraft.site} onChange={(event) => setScheduleDraft({ ...scheduleDraft, site: event.target.value })} />
          <label>Every <input aria-label="Refresh interval minutes" type="number" min="15" max="10080" value={scheduleDraft.interval_minutes} onChange={(event) => setScheduleDraft({ ...scheduleDraft, interval_minutes: Number(event.target.value) })} /> minutes</label>
          <label>Batch <input aria-label="Refresh batch size" type="number" min="1" max="1000" value={scheduleDraft.batch_size} onChange={(event) => setScheduleDraft({ ...scheduleDraft, batch_size: Number(event.target.value) })} /></label>
          <button type="submit" className="operations-action">Add schedule</button>
        </form>
        <div className="operations-control-list">{schedules.map((schedule) => <div className="operations-control-row" key={schedule.id}><div><strong>{schedule.site || "All sources"}</strong><small>Every {schedule.interval_minutes}m · batch {schedule.batch_size}</small></div><div className="operations-control-actions"><button type="button" className="operations-action" onClick={() => void runSchedule(schedule)}>Run now</button><button type="button" className="operations-action operations-action--quiet" onClick={() => void toggleSchedule(schedule)}>{schedule.enabled ? "Pause" : "Enable"}</button><button type="button" className="operations-action operations-action--danger" onClick={() => void removeSchedule(schedule)}>Delete</button></div></div>)}</div>
      </article>
      <article className="operations-panel">
        <header><h2>{showFailureHistory ? "Archived metadata jobs" : "Failed metadata jobs"}</h2><div className="operations-panel__actions"><span>{failedJobs.length} {showFailureHistory ? "archived" : "need attention"}</span><button type="button" className="operations-action operations-action--quiet" onClick={() => setShowFailureHistory((value) => !value)}>{showFailureHistory ? "Show active" : "History"}</button>{!showFailureHistory && failedJobs.length > 0 && <button type="button" className="operations-action operations-action--quiet" onClick={() => void archiveAllFailed()}>Archive all</button>}</div></header>
        {failedJobs.length ? <div className="operations-control-list">{failedJobs.slice(0, 8).map((job) => <div className="operations-control-row" key={job.id}><div><strong>{job.job_type} · {job.site}</strong><small>{jobExplanation(job)} · {attemptLabel(job)}</small></div><div className="operations-control-actions">{!showFailureHistory && <button type="button" className="operations-action" disabled={!job.retryable} onClick={() => void retryJob(job)}>{job.retryable ? "Retry" : "Not retryable"}</button>}{!showFailureHistory && <button type="button" className="operations-action operations-action--quiet" onClick={() => void archiveJob(job)}>Archive</button>}</div></div>)}</div> : <p className="operations-empty">{showFailureHistory ? "No archived metadata jobs." : "No failed metadata jobs."}</p>}
      </article>
    </section>
    <section className="operations-panel">
      <header><h2>Source health</h2><span>{sourceHealth.length} tracked</span></header>
      {sourceHealth.length ? <div className="operations-control-list">{sourceHealth.map((source) => <div className="operations-control-row" key={source.site}><div><strong>{source.site} · {source.status}</strong><small>{source.failure_count} failures{source.last_error ? ` · ${source.last_error}` : ""}</small></div><button type="button" className="operations-action operations-action--quiet" onClick={() => void resetSource(source)}>Reset circuit</button></div>)}</div> : <p className="operations-empty">No source health records.</p>}
    </section>
    <section className="operations-panel">
      <header><h2>Source policy</h2><span>Last {sourcePolicy?.hours || 24} hours · privacy-safe metadata only</span></header>
      {sourcePolicy?.sources.length ? <div className="operations-control-list">{sourcePolicy.sources.map((source) => <div className="operations-control-row" key={source.site}><div><strong>{source.site} · {source.circuit_state}</strong><small>{source.requests} requests · {source.cache_hit_percent}% cache hit · {source.average_latency_ms}ms average · queue work {source.average_job_duration_seconds}s{source.last_error_category ? ` · last ${source.last_error_category}` : ""}</small></div><span className="operations-policy-retention">{source.retention_days}d retention</span></div>)}</div> : <p className="operations-empty">No source requests have been recorded yet. Metadata is recorded after the first gateway request.</p>}
    </section>
    <section className="operations-notice"><CheckCircle2 size={17} /><p><strong>Automation is event-driven.</strong> Source refreshes create update events and eligible downloads. Paused, completed, dropped, and ignored stories are excluded from automatic actions.</p></section>
    {summary?.source_failures ? <section className="operations-alert operations-alert--warning"><XCircle size={17} /> {summary.source_failures} source failure event(s) need attention in the Activity feed.</section> : null}
  </div>;
};

export default Operations;
