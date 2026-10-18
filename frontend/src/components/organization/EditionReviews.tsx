import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Banner, Button, Input } from "../ui";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import { accountStorage, onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { readingJournalOperationId } from "../../services/readingJournalService";
import { editionReviewService as service, type EditionReview, type EditionReviewAction, type EditionReviewSummary, type ReviewPage } from "../../services/editionReviewService";
import axios from "axios";
import type { ReviewLookupItem, ReviewLookupPage } from "../../generated/api";
import "./catalogReviews.css";
export type CatalogLookup = ReviewLookupItem;
type LookupPage = ReviewLookupPage;
type Intent = { id: string; action: "apply" | "undo"; input: EditionReviewAction; acknowledged?: boolean };
const intentKey = "edition-review-intent";
function readIntent(): Intent | null {
  try {
    const value = JSON.parse(accountStorage.getItem(intentKey) || "null");
    if (typeof value?.id === "string" && ["apply", "undo"].includes(value.action) && Number.isSafeInteger(value.input?.expected_revision) && value.input.expected_revision > 0 && typeof value.input?.operation_id === "string" && value.input.operation_id.length <= 120) return value;
  } catch { /* No operation can have been submitted if its intent was never saved. */ }
  return null;
}
export function CatalogStoryLookup({ label, value, onSelect, disabled = false }: { label: string; value: CatalogLookup | null; onSelect: (value: CatalogLookup) => void; disabled?: boolean }) {
  const [query, setQuery] = useState(""), [search, setSearch] = useState<string | null>(null), [offset, setOffset] = useState(0), [page, setPage] = useState<LookupPage | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false);
  useEffect(() => {
    if (search === null) return;
    const controller = new AbortController(); const generation = storageGeneration(); let live = true;
    setLoading(true); setPage(null); setError("");
    void apiClient.get<LookupPage>("/admin/review-catalog/lookup", { params: { q: search, offset, limit: 10 }, signal: controller.signal }).then(({ data }) => { if (live && generation === storageGeneration()) setPage(data); }).catch(err => { if (live && generation === storageGeneration()) setError(getUserFacingError(err, "Catalog lookup failed.")); }).finally(() => { if (live && generation === storageGeneration()) setLoading(false); });
    return () => { live = false; controller.abort(); };
  }, [search, offset]);
  return <fieldset disabled={disabled} className="catalog-review-lookup"><legend>{label}</legend>
    {value && <p>Selected: <strong>{value.title}</strong> · {value.site || "Unknown source"} · {value.author || "Unknown author"}</p>}
    <form onSubmit={event => { event.preventDefault(); setOffset(0); setSearch(query.trim()); }}><Input label={`${label} title or author`} value={query} maxLength={200} onChange={event => setQuery(event.target.value)} /><Button type="submit">Search {label.toLowerCase()}</Button></form>
    {loading && <p role="status">Searching saved catalog records…</p>}{error && <Banner tone="danger">{error}</Banner>}
    {page && <><p>{page.total} catalog records</p><ul>{page.items.map(item => <li key={item.novel_id}><div><strong>{item.title}</strong><small>{item.author || "Unknown author"} · {item.site || "Unknown source"}</small><small>{item.source_url}</small></div><Button onClick={() => onSelect(item)} aria-label={`Choose ${label.toLowerCase()}: ${item.title} · ${item.site || "Unknown source"}`}>Choose</Button></li>)}</ul><div className="catalog-review-actions"><Button disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 10))}>Previous {label.toLowerCase()} results</Button><Button disabled={!page.has_more} onClick={() => setOffset(value => value + 10)}>Next {label.toLowerCase()} results</Button></div></>}
  </fieldset>;
}
function Contents() {
  const generation = storageGeneration(), mounted = useRef(false);
  const [source, setSource] = useState<CatalogLookup | null>(null), [target, setTarget] = useState<CatalogLookup | null>(null);
  const [review, setReview] = useState<EditionReview | null>(null), [history, setHistory] = useState<ReviewPage<EditionReviewSummary> | null>(null), [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [intent, setIntent] = useState<Intent | null>(readIntent), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { let live = true; void service.list(offset).then(page => { if (live && current()) setHistory(page); }).catch(err => { if (live && current()) setError(getUserFacingError(err, "Edition review history is unavailable.")); }); return () => { live = false; }; /* account remount fences the request */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, refresh]);
  async function preview() {
    if (!source || !target || busy || intent) return;
    setBusy(true); setError(""); setReview(null);
    try { const next = await service.preview(source.novel_id, target.novel_id); if (current()) setReview(next); }
    catch (err) { if (current()) setError(getUserFacingError(err, "Could not prepare an edition review.")); }
    finally { if (current()) setBusy(false); }
  }
  async function decide(action: "apply" | "undo", existing?: Intent) {
    if (busy || (!existing && (!review || intent))) return;
    const operation = existing ?? { id: review!.id, action, input: { expected_revision: review!.revision, operation_id: readingJournalOperationId() } };
    setBusy(true); setError(""); setNotice("");
    try {
      accountStorage.setItem(intentKey, JSON.stringify(operation)); setIntent(operation);
      if (!operation.acknowledged) {
        await service.decide(operation.id, operation.action, operation.input);
        if (!current()) return;
        operation.acknowledged = true; accountStorage.setItem(intentKey, JSON.stringify(operation)); setIntent({ ...operation });
      }
      const latest = await service.get(operation.id);
      if (!current()) return;
      setReview(latest); accountStorage.removeItem(intentKey); setIntent(null); setRefresh(value => value + 1);
      setNotice(`Action confirmed. Current review status: ${latest.status}. Existing library copies and reading progress were preserved.`);
    } catch (err) {
      if (!current()) return;
      if (axios.isAxiosError(err) && err.response && err.response.status >= 400 && err.response.status < 500) {
        try { const latest = await service.get(operation.id); if (!current()) return; setReview(latest); accountStorage.removeItem(intentKey); setIntent(null); setRefresh(value => value + 1); } catch { /* Keep the operation until authoritative recovery is available. */ }
      }
      setError(getUserFacingError(err, "The action could not be confirmed. Retry confirmation to reuse the same operation; do not start another review."));
    } finally { if (current()) setBusy(false); }
  }
  async function open(id: string) { setBusy(true); setError(""); try { const value = await service.get(id); if (current()) setReview(value); } catch (err) { if (current()) setError(getUserFacingError(err, "Could not load this review.")); } finally { if (current()) setBusy(false); } }
  return <section className="catalog-review" aria-label="Reviewed edition links">
    <p>Link editions of the same work after reviewing every affected member. This groups catalog stories; it does not merge library copies, content, or reading progress.</p>
    {error && <Banner tone="danger">{error}</Banner>}{notice && <Banner tone="success">{notice}</Banner>}
    {intent && <Banner tone="warning" action={<Button disabled={busy} onClick={() => void decide(intent.action, intent)}>Retry edition confirmation</Button>}>A previous edition action is awaiting confirmation. Its operation identity is preserved.</Banner>}
    <div className="catalog-review-columns"><CatalogStoryLookup label="Source group" value={source} disabled={busy || !!intent} onSelect={value => { setSource(value); setReview(null); }} /><CatalogStoryLookup label="Destination group" value={target} disabled={busy || !!intent} onSelect={value => { setTarget(value); setReview(null); }} /></div>
    <Button disabled={busy || !!intent || !source || !target || source.novel_id === target.novel_id} onClick={() => void preview()}>Preview edition links</Button>
    {review && <article className="catalog-review-plan"><h3>Edition review · {review.status}</h3><p>All editions in “{review.source_group.title}” will join “{review.target_group.title}”.</p>
      <div className="catalog-review-columns">{[review.source_group, review.target_group].map((group, index) => <div key={index}><h4>{index ? "Destination group" : "Source group"} · {group.edition_count} editions</h4><ul>{group.editions.map(edition => <li key={edition.edition_id}><div><strong>{edition.title}</strong><small>{[edition.author, edition.site, edition.language, edition.edition_kind].filter(Boolean).join(" · ")}</small><small>{edition.source_url}</small></div></li>)}</ul></div>)}</div>
      {review.warnings.map(warning => <Banner key={warning} tone="warning">{warning}</Banner>)}
      {review.status === "preview" && <Button disabled={busy || !!intent} onClick={() => void decide("apply")}>Confirm reviewed edition links</Button>}
      {review.status === "applied" && <><Button disabled={busy || !!intent || !review.can_undo} onClick={() => void decide("undo")}>Undo edition links</Button>{review.undo_blocked_reason && <p>{review.undo_blocked_reason}</p>}<p>Undo restores the prior groups only if no later changes conflict.</p></>}
    </article>}
    <h3>Edition review history</h3><Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh edition history</Button>
    {history && <><p>{history.total} reviews</p><ul>{history.items.map(item => <li key={item.id}><div><strong>{item.source_title} → {item.target_title}</strong><small>{item.status} · {item.created_at}</small></div><Button disabled={busy || !!intent} onClick={() => void open(item.id)}>Open review {item.id.slice(0, 8)}</Button></li>)}</ul><div className="catalog-review-actions"><Button disabled={!offset || busy} onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous edition reviews</Button><Button disabled={busy || offset + history.items.length >= history.total} onClick={() => setOffset(value => value + 20)}>Next edition reviews</Button></div></>}
  </section>;
}
export default function EditionReviews() { const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration); return <Contents key={generation} />; }
