import React, { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, Download, RefreshCw, Server, XCircle } from "lucide-react";
import { useLibraryContext } from "../context/LibraryContext";
import { activityService, OperationsSummary } from "../services/activityService";
import "../styles/operations.css";

const Operations: React.FC = () => {
  const { activeLibrary } = useLibraryContext();
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!activeLibrary) {
      setSummary(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setSummary(await activityService.getOperationsSummary(activeLibrary.id));
      setError(null);
    } catch {
      setError("Operations data is unavailable. Check the Novel API and metadata server.");
    } finally {
      setLoading(false);
    }
  }, [activeLibrary?.id]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!activeLibrary) return <div className="operations-page"><h1>Operations</h1><p className="operations-empty">Select a library to view its automation status.</p></div>;

  const metadataStatus = summary?.metadata_server.status || "unknown";
  const metadataHealth = Object.entries(summary?.source_health || {}).map(([status, count]) => `${count} ${status}`).join(" · ") || "No source health records";

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
    <section className="operations-notice"><CheckCircle2 size={17} /><p><strong>Automation is event-driven.</strong> Source refreshes create update events and eligible downloads. Paused, completed, dropped, and ignored stories are excluded from automatic actions.</p></section>
    {summary?.source_failures ? <section className="operations-alert operations-alert--warning"><XCircle size={17} /> {summary.source_failures} source failure event(s) need attention in the Activity feed.</section> : null}
  </div>;
};

export default Operations;
