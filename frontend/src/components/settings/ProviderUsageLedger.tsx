import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import axios from "axios";
import { Banner, Button, Dialog, Input } from "../ui";
import { accountStorage, onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { getUserFacingError } from "../../services/apiClient";
import { readingJournalOperationId } from "../../services/readingJournalService";
import { providerUsageService, usdToMicros, usageUsd, type ProviderRequest, type ProviderReconciliation, type ProviderRequestsPage } from "../../services/providerUsageService";
import "./ProviderUsageLedger.css";
type Props = { providerId: number; providerName: string; onChanged: () => Promise<void> };
type Attempt = { request_key: string; input: ProviderReconciliation; acknowledged?: boolean };
const requestModel=(row:ProviderRequest)=>row.purpose==='guide_portrait'?(row.model_snapshot.image_model||'Unknown image model'):row.model_snapshot.model;
const purposeLabel=(row:ProviderRequest)=>row.purpose==='guide_portrait'?'Private portrait':row.purpose==='guide_extract'?'Private guide extraction':row.purpose==='guide_synthesize'?'Private guide synthesis':row.translation_job_id!=null?'Translation':'Provider processing';
const pendingKey = (providerId: number) => `provider-reconciliation:${providerId}`;
function pending(providerId: number): Attempt | null {
  try {
    const value = JSON.parse(accountStorage.getItem(pendingKey(providerId)) || "null");
    return value && typeof value.request_key === "string" && /^[a-f0-9-]{36}$/.test(value.request_key)
      && typeof value.input?.operation_id === "string" && value.input.operation_id.length > 0 && value.input.operation_id.length <= 128
      && Number.isSafeInteger(value.input.expected_revision) && value.input.expected_revision >= 0
      && Number.isSafeInteger(value.input.actual_microusd) && value.input.actual_microusd >= 0 && value.input.actual_microusd <= 100_000_000_000
      ? { request_key: value.request_key, input: { expected_revision: value.input.expected_revision, operation_id: value.input.operation_id, actual_microusd: value.input.actual_microusd }, acknowledged: value.acknowledged === true } : null;
  } catch { return null; }
}
const statusLabel: Record<ProviderRequest["status"], string> = { pending: "Pending", unknown: "Charge unknown", completed: "Settled", reconciled: "Reconciled", legacy_unknown: "Legacy reservation · charge unknown" };
function Contents({ providerId, providerName, onChanged }: Props) {
  const generation = storageGeneration(), mounted = useRef(false), epoch = useRef(0);
  const [page, setPage] = useState<ProviderRequestsPage | null>(null), [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [fresh, setFresh] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<ProviderRequest | null>(null), [review, setReview] = useState(false);
  const [amount, setAmount] = useState(""), [verified, setVerified] = useState(false);
  const [attempt, setAttempt] = useState<Attempt | null>(() => pending(providerId));
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function load(nextOffset = offset, refreshProvider = false): Promise<boolean> {
    const version = ++epoch.current; setLoading(true); setFresh(false);
    try {
      const [data] = await Promise.all([providerUsageService.list(providerId, nextOffset, 20), ...(refreshProvider ? [onChanged()] : [])]);
      if (!current() || version !== epoch.current) return false;
      setPage(data); setFresh(true); return true;
    } catch (err) {
      if (current() && version === epoch.current) setError(getUserFacingError(err, "Couldn’t refresh request accounting. Refresh before reconciling another charge."));
      return false;
    } finally { if (current() && version === epoch.current) setLoading(false); }
  }
  useEffect(() => { void load(offset); /* Each request is fenced against account/page changes. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId, offset]);
  function retain(value: Attempt | null) {
    if (value) accountStorage.setItem(pendingKey(providerId), JSON.stringify(value));
    else accountStorage.removeItem(pendingKey(providerId));
    setAttempt(value);
  }
  async function refreshConfirmed(value: Attempt) {
    const refreshed = await load(offset, true);
    if (!current()) return;
    if (refreshed) { retain(null); setSelected(null); setReview(false); setNotice("Reconciliation confirmed. Current provider totals and request history are shown."); }
    else { setAttempt(value); setNotice("Reconciliation was confirmed. Refresh accounting before making another change."); }
  }
  async function submit() {
    if (busy || !current()) return;
    const stored = pending(providerId);
    if (stored && stored.input.operation_id !== attempt?.input.operation_id) {
      setAttempt(stored); setSelected(null); setReview(false); setError("Another reconciliation is recorded on this device. Review that operation before making another change."); return;
    }
    const micros = usdToMicros(amount);
    const value = (stored ?? attempt) ?? (selected && verified && micros !== null ? { request_key: selected.request_key, input: { expected_revision: selected.revision, operation_id: readingJournalOperationId(), actual_microusd: micros } } : null);
    if (!value) return;
    setBusy(true); setError(""); setNotice("");
    // Persist only user intent before sending; storage failure must not create
    // an operation whose identity would be lost on reload.
    try { retain(value); } catch { setError("Couldn’t retain this reconciliation safely on this device. Nothing was submitted. Enable private account storage and try again."); setBusy(false); return; }
    try {
      if (value.acknowledged) { await refreshConfirmed(value); return; }
      await providerUsageService.reconcile(providerId, value.request_key, value.input);
      if (!current()) return;
      const confirmed = { ...value, acknowledged: true }; retain(confirmed);
      await refreshConfirmed(confirmed);
    } catch (err) {
      if (!current()) return;
      const rejected = axios.isAxiosError(err) && err.response && err.response.status >= 400 && err.response.status < 500 && ![408, 429].includes(err.response.status);
      if (rejected) {
        retain(null); setSelected(null); setReview(false); setError(getUserFacingError(err, "This request changed. Refresh and review the current billing record before trying again."));
        await load(offset, true);
      } else setError(getUserFacingError(err, "The reconciliation could not be confirmed. Keep this recorded operation and retry it explicitly; another provider request will not be sent."));
    } finally { if (current()) setBusy(false); }
  }
  const reviewAmount = attempt?.input.actual_microusd ?? usdToMicros(amount);
  const reviewOpen = review || !!attempt && !attempt.acknowledged && !!selected;
  return <section className="provider-usage" aria-label={`Request accounting for ${providerName}`}>
    <p>Check uncertain charges against your provider’s billing before releasing a reservation. Reconciliation records the verified charge; it never sends a new provider request.</p>
    {error && <Banner tone="warning">{error}</Banner>}{notice && <p role="status">{notice}</p>}
    {attempt && <Banner tone="warning">{attempt.acknowledged ? "A confirmed reconciliation still needs a current accounting refresh." : "A recorded reconciliation needs confirmation. Other settlements are paused."}
      <p>Request {attempt.request_key} · verified amount {usageUsd(attempt.input.actual_microusd)}</p>
      <Button disabled={busy || loading} onClick={() => attempt.acknowledged ? void submit() : (setReview(true), setSelected(page?.items.find(row => row.request_key === attempt.request_key) ?? null))}>{attempt.acknowledged ? "Refresh reconciled accounting" : "Review unconfirmed reconciliation"}</Button>
    </Banner>}
    {page && <p>Budget {usageUsd(page.accounting.budget_microusd)} · used {usageUsd(page.accounting.used_microusd)} · reserved {usageUsd(page.accounting.reserved_microusd)}</p>}
    <Button disabled={busy || loading} onClick={() => { setError(""); void load(offset, true); }}>Refresh request accounting</Button>
    {loading && <p role="status">Loading request accounting…</p>}
    {page?.total === 0 && <p>No provider requests have been recorded.</p>}
    <ol className="provider-usage__rows">{page?.items.map(row => <li key={row.request_key}>
      <h3>{statusLabel[row.status]}</h3><p>Request {row.request_key}</p>
      <p>{purposeLabel(row)}</p><p>Original model: {requestModel(row)} · {row.model_snapshot.kind}</p>
      {row.purpose === "guide_portrait" ? <p>Original maximum price per image: {row.model_snapshot.image_price_microusd==null?"Unknown":usageUsd(row.model_snapshot.image_price_microusd)}</p> : row.model_snapshot.kind === "legacy_unknown" || row.model_snapshot.input_price == null || row.model_snapshot.output_price == null
        ? <p>Original pricing is unknown for this legacy reservation.</p>
        : <p>Original price per million tokens: input ${row.model_snapshot.input_price} · output ${row.model_snapshot.output_price}</p>}
      <p>Reserved {usageUsd(row.reserved_microusd)} · actual {row.actual_microusd == null ? "Not confirmed" : usageUsd(row.actual_microusd)}</p>
      {row.purpose!=="guide_portrait"&&<p>Usage: input {row.input_tokens ?? "unknown"} tokens · output {row.output_tokens ?? "unknown"} tokens</p>}
      <p>Recorded {new Date(row.created_at).toLocaleString()}{row.resolved_at ? ` · settled ${new Date(row.resolved_at).toLocaleString()}` : ""}</p>
      {row.translation_job_id != null && <p>Translation job {row.translation_job_id}{row.translation_block_index != null ? ` · passage ${row.translation_block_index + 1}` : ""}</p>}
      {row.status === "pending" && row.expires_at && !row.can_reconcile && <p>Safety window ends {new Date(row.expires_at).toLocaleString()}. Refresh to check whether billing review is available.</p>}
      {row.status === "pending" && !row.can_reconcile && <p>This request may still be in flight. Reconciliation is unavailable until Nexus can safely expire its reservation.</p>}
      {row.can_reconcile && <Button disabled={busy || loading || !fresh || !!attempt} onClick={() => { setSelected(row); setReview(false); setAmount(""); setVerified(false); setError(""); setNotice(""); }}>Reconcile request {row.request_key}</Button>}
    </li>)}</ol>
    {page && <nav className="provider-usage__actions" aria-label={`Request history pages for ${providerName}`}><Button disabled={busy || loading || !!attempt || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous requests</Button><span>{page.total ? page.offset + 1 : 0}–{Math.min(page.offset + page.items.length, page.total)} of {page.total} requests</span><Button disabled={busy || loading || !!attempt || offset + page.limit >= page.total} onClick={() => setOffset(value => value + 20)}>Next requests</Button></nav>}
    <Dialog open={!!selected || reviewOpen} onClose={() => { if (!busy) { setSelected(null); setReview(false); } }} title={reviewOpen ? "Confirm provider billing" : "Reconcile provider request"} actions={<>
      <Button disabled={busy} onClick={() => { setSelected(null); setReview(false); }}>Close</Button>
      {reviewOpen ? <Button disabled={busy || reviewAmount === null} onClick={() => void submit()}>{attempt ? "Retry same reconciliation" : "Confirm reconciliation"}</Button> : <Button disabled={!verified || usdToMicros(amount) === null} onClick={() => setReview(true)}>Review reconciliation</Button>}
    </>}>
      <p>Request {attempt?.request_key ?? selected?.request_key}</p>
      {selected && <><p>Original model: {requestModel(selected)}</p><p>Reserved {usageUsd(selected.reserved_microusd)}. Existing usage and original chapters are retained.</p></>}
      {error && <Banner tone="warning">{error}</Banner>}
      {reviewOpen ? <><p>Record the verified actual charge of <strong>{usageUsd(reviewAmount ?? 0)}</strong> and release this request’s reservation.</p><p>This amount came from your billing review. It does not change your provider’s invoice.</p></> : <>
        <Input label="Verified actual charge (USD)" value={amount} inputMode="decimal" onChange={event => { setAmount(event.target.value); setVerified(false); }} hint="Enter 0 only after verifying that this request was not charged. Up to six decimal places." />
        <label className="provider-usage__confirmation"><input type="checkbox" checked={verified} onChange={event => setVerified(event.target.checked)} />I checked this amount against my provider’s billing, including any zero charge.</label>
      </>}
    </Dialog>
  </section>;
}
export default function ProviderUsageLedger(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${props.providerId}`} {...props} />;
}
