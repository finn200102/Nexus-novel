import React, { useEffect, useState } from "react";
import { Check, Link2, RefreshCw, RotateCw, Send, ShieldCheck, X } from "lucide-react";
import { adminIntegrationService, MergeReview, WebhookDelivery, WebhookSubscription } from "../services/adminIntegrationService";
import { getUserFacingError } from "../services/apiClient";
import { useToast } from "../context/ToastContext";
import "../styles/integrations.css";

const DEFAULT_EVENTS = ["import.completed", "source_refreshed", "chapter.found", "download.completed", "download.failed", "source_returned_from_hiatus", "metadata.merge", "source.degraded", "source.recovered", "job.state_changed"];

const Integrations: React.FC = () => {
  const { addToast } = useToast();
  const [reviews, setReviews] = useState<MergeReview[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookSubscription[]>([]);
  const [history, setHistory] = useState<Record<string, WebhookDelivery[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", target_url: "", secret: "", event_types: "job.state_changed, chapter.found", enabled: true });

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [nextReviews, nextWebhooks] = await Promise.all([adminIntegrationService.mergeReviews(), adminIntegrationService.webhooks()]);
      setReviews(nextReviews); setWebhooks(nextWebhooks);
    } catch (err) { setError(getUserFacingError(err, "Administrator integrations are unavailable.")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const decide = async (review: MergeReview, action: "approve" | "reject" | "revert") => {
    try { await adminIntegrationService.decideMerge(review.id, action); addToast(`Merge review ${action}d`, "success"); await load(); }
    catch (err) { addToast(getUserFacingError(err, "Could not update merge review"), "error"); }
  };
  const createWebhook = async (event: React.FormEvent) => {
    event.preventDefault();
    const eventTypes = form.event_types.split(",").map((value) => value.trim()).filter(Boolean);
    try {
      await adminIntegrationService.createWebhook({ ...form, event_types: eventTypes });
      setForm({ name: "", target_url: "", secret: "", event_types: "job.state_changed, chapter.found", enabled: true });
      addToast("Signed webhook subscription created", "success"); await load();
    } catch (err) { addToast(getUserFacingError(err, "Could not create webhook"), "error"); }
  };
  const showHistory = async (id: string) => {
    try {
      const deliveries = await adminIntegrationService.webhookHistory(id);
      setHistory((current) => ({ ...current, [id]: deliveries }));
    }
    catch (err) { addToast(getUserFacingError(err, "Could not load delivery history"), "error"); }
  };

  return <div className="integrations-page">
    <header className="integrations-page__header"><div><p className="library-workspace__eyebrow">Administrator controls</p><h1>Trust & integrations</h1><p>Review uncertain identity matches and manage signed, durable external event deliveries.</p></div><button className="operations-refresh" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "is-spinning" : ""} /> Refresh</button></header>
    {error && <div className="integrations-alert"><ShieldCheck size={18} /> {error}</div>}
    <section className="integrations-grid">
      <article className="integrations-panel"><header><div><h2>Merge review</h2><p>Nothing merges silently. Each decision is auditable and reversible.</p></div><span>{reviews.length} open</span></header>
        {loading ? <p className="integrations-muted">Loading merge review…</p> : reviews.length === 0 ? <p className="integrations-muted">No merge candidates need review.</p> : <div className="integrations-list">{reviews.map((review) => <div className="integration-row" key={review.id}><div><strong>{review.source.site} → {review.target_title}</strong><small>{Math.round(review.confidence * 100)}% confidence · {review.match_reasons.join(" · ") || "No explanation supplied"}</small>{review.conflicts.length > 0 && <small className="integration-warning">Conflicts: {review.conflicts.join(", ")}</small>}</div><div className="integration-actions">{review.status === "pending" ? <><button className="operations-action" onClick={() => void decide(review, "approve")}><Check size={14} /> Approve</button><button className="operations-action operations-action--quiet" onClick={() => void decide(review, "reject")}><X size={14} /> Reject</button></> : review.status === "approved" ? <button className="operations-action operations-action--quiet" onClick={() => void decide(review, "revert")}><RotateCw size={14} /> Revert</button> : <span className="integration-status">{review.status}</span>}</div></div>)}</div>}
      </article>
      <article className="integrations-panel"><header><div><h2>Webhook subscriptions</h2><p>Nexus signs every delivery and disables a target after repeated failures.</p></div><span>{webhooks.filter((hook) => hook.enabled).length} active</span></header>
        <form className="integration-form" onSubmit={createWebhook}><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Subscription name" /><input required type="url" value={form.target_url} onChange={(e) => setForm({ ...form, target_url: e.target.value })} placeholder="https://example.net/nexus" /><input required minLength={16} type="password" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} placeholder="Signing secret (16+ characters)" /><input required value={form.event_types} onChange={(e) => setForm({ ...form, event_types: e.target.value })} placeholder="Comma-separated events" /><button className="operations-action"><Link2 size={14} /> Add signed webhook</button></form>
        <small className="integrations-event-help">Available events: {DEFAULT_EVENTS.join(", ")}</small>
        <div className="integrations-list">{webhooks.map((hook) => <div className="integration-row integration-row--webhook" key={hook.id}><div><strong>{hook.name} <span className={hook.enabled ? "integration-good" : "integration-warning"}>{hook.enabled ? "active" : "disabled"}</span></strong><small>{hook.target_url}</small><small>{hook.event_types.join(", ")} · {hook.failure_count} consecutive failures</small>{hook.last_error && <small className="integration-warning">Last error: {hook.last_error}</small>}{history[hook.id]?.map((delivery) => <small key={delivery.id}>#{delivery.id.slice(0, 8)} · {delivery.event_type} · {delivery.status} · attempts {delivery.attempt_count}</small>)}</div><div className="integration-actions"><button className="operations-action operations-action--quiet" onClick={() => void adminIntegrationService.testWebhook(hook.id).then(() => addToast("Test delivery queued", "success")).catch((err) => addToast(getUserFacingError(err, "Could not queue webhook test"), "error"))}><Send size={14} /> Test</button><button className="operations-action operations-action--quiet" onClick={() => void showHistory(hook.id)}>History</button><button className="operations-action operations-action--danger" onClick={() => void adminIntegrationService.deleteWebhook(hook.id).then(load).catch((err) => addToast(getUserFacingError(err, "Could not delete webhook"), "error"))}>Delete</button></div></div>)}</div>
      </article>
    </section>
  </div>;
};

export default Integrations;
