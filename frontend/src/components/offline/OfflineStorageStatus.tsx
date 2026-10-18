import { useEffect, useRef, useState } from "react";
import { Banner, Button, Input } from "../ui";
import { storageGeneration } from "../../services/accountStorage";
import { offlineBytes } from "./offlineLabels";
type Props = { usedBytes: number | null; limitBytes: number | null; onBudget: (bytes: number | null) => Promise<void> };
type Persistence = "unknown" | "granted" | "not-granted" | "unsupported";
export default function OfflineStorageStatus({ usedBytes, limitBytes, onBudget }: Props) {
  const generation = storageGeneration(), mounted = useRef(false), inspection = useRef(0), persistence = useRef(0), dirtyBudget = useRef(false);
  const [persistent, setPersistent] = useState<Persistence>("unknown");
  const [estimate, setEstimate] = useState<StorageEstimate | null>(null);
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const [requesting, setRequesting] = useState(false), [saving, setSaving] = useState(false);
  const [budget, setBudget] = useState(limitBytes == null ? "" : String(limitBytes / 1_000_000));
  const current = () => mounted.current && generation === storageGeneration();
  async function inspect() {
    const version = ++inspection.current, persistentVersion = ++persistence.current, storage = navigator.storage;
    const results = await Promise.allSettled([
      Promise.resolve().then(() => storage?.persisted ? storage.persisted() : null),
      Promise.resolve().then(() => storage?.estimate ? storage.estimate() : null),
    ]);
    if (!current() || version !== inspection.current) return;
    if (persistentVersion === persistence.current && results[0].status === "fulfilled") setPersistent(results[0].value == null ? "unsupported" : results[0].value ? "granted" : "not-granted");
    if (results[1].status === "fulfilled") setEstimate(results[1].value);
    if (results[1].status === "rejected" || persistentVersion === persistence.current && results[0].status === "rejected") setError("This browser could not report its storage status. You can retry the check.");
  }
  useEffect(() => { mounted.current = true; void inspect(); return () => { mounted.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (!dirtyBudget.current) setBudget(limitBytes == null ? "" : String(limitBytes / 1_000_000)); }, [limitBytes]);
  async function requestPersistence() {
    const version = ++persistence.current;
    setRequesting(true); setError("");
    try {
      const granted = await navigator.storage.persist();
      if (current() && version === persistence.current) { setPersistent(granted ? "granted" : "not-granted"); setMessage(granted ? "This browser accepted the persistent storage request." : "The browser did not grant persistent storage. Offline files may be evicted when space is needed."); }
    } catch { if (current()) setError("The browser could not process the persistent storage request. You can try again."); }
    finally { if (current()) setRequesting(false); }
  }
  async function saveBudget(bytes: number | null) {
    setSaving(true); setError(""); setMessage("");
    try { await onBudget(bytes); if (current()) { dirtyBudget.current = false; setBudget(bytes == null ? "" : String(bytes / 1_000_000)); setMessage(bytes == null ? "The optional offline budget was removed. Existing files are kept." : "Offline storage budget saved. Existing files are kept."); } }
    catch { if (current()) setError("Couldn’t save the offline budget on this device. Try again."); }
    finally { if (current()) setSaving(false); }
  }
  const budgetNumber = budget.trim() === "" ? NaN : Number(budget);
  const budgetBytes = Math.round(budgetNumber * 1_000_000);
  const validBudget = Number.isFinite(budgetNumber) && budgetNumber > 0 && budgetNumber <= 1_000_000 && Number.isSafeInteger(budgetBytes);
  return <section className="offline-library__storage" aria-label="Browser storage and offline budget">
    <h2>Storage on this device</h2>
    {error && <Banner tone="warning">{error}</Banner>}{message && <p role="status">{message}</p>}
    <p>{persistent === "granted" ? "Persistent storage granted by this browser." : persistent === "unsupported" ? "This browser does not report persistent storage support." : persistent === "unknown" ? "Checking persistent storage…" : "Persistent storage has not been granted. The browser may evict offline files when space is needed."}</p>
    <div className="offline-library__actions"><Button disabled={requesting || !navigator.storage?.persist} onClick={() => void requestPersistence()}>Request persistent storage</Button><Button disabled={requesting} onClick={() => { setError(""); void inspect(); }}>Refresh browser storage status</Button></div>
    <p>Browser-origin usage: {estimate?.usage != null ? offlineBytes(estimate.usage) : "Unavailable"} · quota: {estimate?.quota != null ? offlineBytes(estimate.quota) : "Unavailable"}</p>
    <p className="text-muted">The browser estimate includes application files and other accounts on this origin. It is separate from your private offline library. A saved or pinned file can still be removed by you or your browser.</p>
    <p>Optional offline budget: {limitBytes == null ? "Not set" : offlineBytes(limitBytes)}{usedBytes != null ? ` · your files use ${offlineBytes(usedBytes)}` : ""}</p>
    {usedBytes != null && limitBytes != null && usedBytes > limitBytes && <Banner tone="warning">Your saved files exceed this budget. Existing files are kept; new storage growth is paused until you free space or raise the budget.</Banner>}
    <form onSubmit={event => { event.preventDefault(); if (validBudget) void saveBudget(budgetBytes); }}>
      <Input label="Offline storage budget (MB)" disabled={saving} type="number" min="0.1" max="1000000" step="0.1" value={budget} onChange={event => { dirtyBudget.current = true; setBudget(event.target.value); }} hint="Optional, per account on this browser. 1 MB is 1,000,000 bytes. Lowering a budget does not delete files." />
      <div className="offline-library__actions"><Button type="submit" disabled={saving || !validBudget}>Save offline budget</Button><Button disabled={saving || limitBytes == null} onClick={() => void saveBudget(null)}>Remove offline budget</Button></div>
    </form>
  </section>;
}
