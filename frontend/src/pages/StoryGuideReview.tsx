import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminIntegrationService, GuideReviewAssertion, GuideReviewHistoryItem } from "../services/adminIntegrationService";
import { useToast } from "../context/ToastContext";
import "../styles/novel-detail.css";

const StoryGuideReview: React.FC = () => {
  const { metadataId } = useParams<{ metadataId: string }>();
  const novelId = Number(metadataId);
  const { addToast } = useToast();
  const [items, setItems] = useState<GuideReviewAssertion[]>([]);
  const [history, setHistory] = useState<GuideReviewHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    if (!Number.isInteger(novelId) || novelId < 1) return;
    setLoading(true);
    try {
      const [queue, audit] = await Promise.all([adminIntegrationService.storyGuideReviewQueue(novelId), adminIntegrationService.storyGuideReviewHistory(novelId)]);
      setItems(queue.data || queue.assertions || []);
      setHistory(audit.data || audit.history || []);
      setError(null);
    } catch (caught: any) {
      setError(caught?.response?.status === 403 ? "This editorial workbench is available to Nexus administrators only." : "The review service is temporarily unavailable. Reader-facing guide pages remain unaffected.");
    } finally { setLoading(false); }
  }, [novelId]);

  useEffect(() => { void load(); }, [load]);
  const suggested = useMemo(() => items.filter((item) => item.review_state === "machine_suggested"), [items]);

  const decide = async (id: string, state: "approved" | "hidden" | "machine_suggested") => {
    setBusy(id);
    try {
      await adminIntegrationService.reviewStoryGuideAssertion(id, state);
      addToast(state === "approved" ? "Claim marked reviewed." : state === "hidden" ? "Claim removed from reader views." : "Claim returned to the Nexus suggestion queue.", "success");
      await load();
    } catch { addToast("Could not update this claim. No reader-visible guide data was changed.", "error"); }
    finally { setBusy(null); }
  };

  const restore = async (id: string) => {
    setBusy(id);
    try { await adminIntegrationService.restoreStoryGuideAssertion(id); addToast("The last editorial decision was restored.", "success"); await load(); }
    catch { addToast("Could not restore that decision.", "error"); }
    finally { setBusy(null); }
  };

  if (loading) return <main className="story-guide-page"><div className="story-guide-page__loading"><span className="story-guide-page__loading-orb">◇</span><strong>Loading editorial review</strong><p>Collecting cited Nexus suggestions…</p></div></main>;
  if (error) return <main className="story-guide-page"><section className="novel-insights__panel story-guide-page__state-panel"><p className="novel-insights__eyebrow">Story Guide editorial workbench</p><h1>Review unavailable</h1><p className="novel-insights__notice">{error}</p><button className="novel-insights__browse" type="button" onClick={() => void load()}>Try again</button><Link className="novel-insights__browse" to={`/story-guide/${novelId}`}>Open reader guide</Link></section></main>;

  return <main className="story-guide-page story-guide-review">
    <header className="novel-insights__panel story-guide-page__hero">
      <div className="story-guide-page__hero-copy"><p className="novel-insights__eyebrow">Administrator editorial workbench</p><h1>Review Story Guide claims</h1><p className="novel-insights__notice">Approve, hide, or return AI-extracted claims to the suggestion queue. Every decision keeps its evidence and audit trail.</p></div>
      <div className="story-guide-page__hero-actions"><button className="novel-insights__browse" type="button" onClick={() => void load()}>Refresh</button><Link className="novel-insights__browse" to={`/story-guide/${novelId}`}>Open reader guide</Link></div>
      <div className="story-guide-page__coverage"><div><span>Needs review</span><strong>{suggested.length}</strong></div><div><span>Reviewed</span><strong>{items.filter((item) => item.review_state === "approved").length}</strong></div><div><span>Hidden</span><strong>{items.filter((item) => item.review_state === "hidden").length}</strong></div><div><span>Audit events</span><strong>{history.length}</strong></div></div>
    </header>
    <section className="novel-insights__panel"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Evidence before status</p><h2>Claim queue</h2></div><span className="story-guide-page__result-count">{items.length} records</span></div>
      {items.length ? <div className="story-guide-review__list">{items.map((item) => <article className="story-guide-review__claim" key={item.id}><header><div><span className={`story-guide-page__claim-status story-guide-page__claim-status--${item.review_state === "approved" ? "reviewed" : "suggested"}`}>{item.review_state === "approved" ? "Reviewed" : item.review_state === "hidden" ? "Hidden" : "Nexus suggestion"}</span><h3>{item.subject || "Story"} · {item.predicate || "claim"}</h3></div><small>{item.confidence === undefined || item.confidence === null ? "Confidence unavailable" : `${Math.round(item.confidence * 100)}% extraction confidence`}</small></header><p>{item.object}</p>{item.chapter ? <small className="story-guide-page__fact-meta">Established in chapter {item.chapter}{item.state ? ` · ${item.state}` : ""}</small> : null}{item.qualifiers && Object.keys(item.qualifiers).length ? <div className="story-guide-page__qualifiers">{Object.entries(item.qualifiers).map(([key, value]) => <span key={key}>{key.replace(/_/g, " ")}: <strong>{value}</strong></span>)}</div> : null}<details className="story-guide-page__citations"><summary>Evidence · {item.citations.length}</summary><div className="story-guide-page__evidence-list">{item.citations.map((citation, index) => <blockquote key={`${citation.chapter}:${index}`}><strong>Chapter {citation.chapter}</strong><span>“{citation.quote}”</span></blockquote>)}</div></details><footer><button type="button" className="novel-insights__browse" disabled={busy === item.id} onClick={() => void decide(item.id, "approved")}>Approve</button><button type="button" className="novel-insights__browse" disabled={busy === item.id} onClick={() => void decide(item.id, "machine_suggested")}>Return to suggestions</button><button type="button" className="novel-insights__browse story-guide-review__hide" disabled={busy === item.id} onClick={() => void decide(item.id, "hidden")}>Hide</button><button type="button" className="novel-insights__browse" disabled={busy === item.id} onClick={() => void restore(item.id)}>Restore last decision</button></footer></article>)}</div> : <div className="story-guide-page__empty-state"><span className="story-guide-page__empty-icon">✓</span><div><strong>No claims are waiting for review</strong><p>New downloaded chapters will add only cited suggestions here.</p></div></div>}</section>
    <section className="novel-insights__panel"><div className="story-guide-page__section-heading"><div><p className="novel-insights__eyebrow">Append-only audit trail</p><h2>Editorial history</h2></div><button className="novel-insights__browse" type="button" onClick={() => setShowHistory((value) => !value)}>{showHistory ? "Hide history" : "Show history"}</button></div>{showHistory && (history.length ? <ol className="story-guide-review__history">{history.map((event) => <li key={event.id}><strong>{event.action.replace(/_/g, " ")}</strong><span>{event.from_state || "—"} → {event.to_state || "—"}</span>{event.reason ? <em>{event.reason}</em> : null}<small>{event.created_at ? new Date(event.created_at).toLocaleString() : "Time unavailable"}</small></li>)}</ol> : <p className="story-guide-page__muted">No editorial decisions have been recorded yet.</p>)}</section>
  </main>;
};

export default StoryGuideReview;
