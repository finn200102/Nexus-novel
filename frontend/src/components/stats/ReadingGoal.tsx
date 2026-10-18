import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import axios from "axios";
import { Banner, Button, Dialog, Input } from "../ui";
import { readingStatsService, type ReadingGoal as Goal, type ReadingGoalWrite } from "../../services/readingStatsService";
import { readingJournalOperationId as operationId } from "../../services/readingJournalService";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { getUserFacingError } from "../../services/apiClient";

type Props = { year: number; completed: number; onSaved?: (target: number | null) => void };
function Contents({ year, completed, onSaved }: Props) {
  const generation = storageGeneration(), mounted = useRef(false);
  const [profile, setProfile] = useState<Goal | null>(null), [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false), [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false);
  const [review, setReview] = useState<ReadingGoalWrite | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true), [loadFailed, setLoadFailed] = useState(false), [reload, setReload] = useState(0);
  const pending = useRef<ReadingGoalWrite | null>(null);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => {
    let active = true; mounted.current = true; setLoading(true); setLoadFailed(false); setError("");
    void readingStatsService.getGoal(year).then(value => {
      if (active && current()) { setProfile(value); setDraft(value.values.target_readings == null ? "" : String(value.values.target_readings)); setLoading(false); }
    }).catch(err => { if (active && current()) { setLoading(false); setLoadFailed(true); setError(getUserFacingError(err, "Couldn’t load the optional reading goal.")); } });
    return () => { active = false; mounted.current = false; };
    // Year and account changes remount this editor so old responses cannot apply.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, generation, reload]);
  const target = draft.trim() ? Number(draft) : null;
  const valid = target !== null && Number.isInteger(target) && target >= 1 && target <= 10000;
  const openReview = (clear: boolean) => {
    if (!profile || busy) return;
    if (pending.current) { setReview(pending.current); return; }
    if (!clear && !valid) return;
    setError(""); setNotice(""); setReview({ expected_revision: profile.revision, operation_id: operationId(), values: { target_readings: clear ? null : target } });
  };
  const save = async () => {
    if (!review || busy) return;
    const value = pending.current ?? review; pending.current = value; setBusy(true); setError("");
    try {
      const changed = await readingStatsService.saveGoal(year, value);
      if (!current()) return;
      pending.current = null; setUncertain(false); setReview(null); setEditing(false);
      // An idempotent receipt can predate another device's later edit. Read current state before displaying it.
      let latest: Goal;
      try {
        latest = await readingStatsService.getGoal(year);
        if (latest.revision < changed.revision) throw new Error("The current goal has not caught up with the confirmed change");
      } catch (loadError) {
        if (current()) { setProfile(null); setLoading(false); setLoadFailed(true); setNotice("Your goal change was confirmed, but the latest target could not be loaded."); setError(getUserFacingError(loadError, "Retry loading the optional goal to see its current target.")); }
        return;
      }
      if (!current()) return;
      setProfile(latest); setLoadFailed(false); setDraft(latest.values.target_readings == null ? "" : String(latest.values.target_readings));
      setNotice(latest.revision > changed.revision && latest.values.target_readings !== changed.values.target_readings ? "Your earlier goal change was confirmed. The goal changed again later; the latest target is shown." : latest.values.target_readings == null ? "The optional goal was cleared. Your reading history is kept." : "Your optional reading goal was saved."); onSaved?.(latest.values.target_readings);
    } catch (err) {
      if (!current()) return;
      if (axios.isAxiosError(err) && err.response && err.response.status >= 400 && err.response.status < 500 && ![408, 429].includes(err.response.status)) {
        pending.current = null; setReview(null); setUncertain(false);
        const latest = err.response.data?.detail?.current as Goal | undefined;
        if (latest && typeof latest.revision === "number" && latest.values && (latest.values.target_readings === null || Number.isInteger(latest.values.target_readings))) setProfile(latest);
        else { try { const fetched = await readingStatsService.getGoal(year); if (current()) setProfile(fetched); } catch { /* Keep the earlier profile; another stale revision will be rejected rather than overwrite newer work. */ } }
        if (current()) { setEditing(true); setError(getUserFacingError(err, "This goal changed elsewhere. Review the latest goal before saving again.")); }
      } else { setUncertain(true); setError(getUserFacingError(err, "The goal change could not be confirmed. Retry the same saved request safely.")); }
    } finally { if (current()) setBusy(false); }
  };
  const savedTarget = profile?.values.target_readings ?? null;
  return <section className="reading-goal" aria-label={`Optional reading goal for ${year}`}>
    <h3>Optional goal for {year}</h3><p>Goals count dated completed readings, including rereads. They never interrupt reading. Completions with unknown or inferred dates do not count toward a year’s goal.</p>
    {error && !review && <Banner tone="warning">{error}</Banner>}{notice && <p role="status">{notice}</p>}
    {!profile && loading && <p role="status">Loading optional goal…</p>}
    {loadFailed && <Button disabled={busy || loading} onClick={() => setReload(value => value + 1)}>Retry optional goal</Button>}
    {profile && <>
      <p>{savedTarget === null ? "No goal set. You can keep reading without one." : `Current goal: ${savedTarget} completed readings`}</p>
      {savedTarget !== null && <><p>{completed} of {savedTarget} readings completed in {year}</p><progress aria-label={`Reading goal progress for ${year}`} value={Math.min(completed, savedTarget)} max={savedTarget} /></>}
      {!editing && !uncertain && <div className="calendar-review__actions"><Button disabled={busy} onClick={() => { setEditing(true); setNotice(""); }}>{savedTarget === null ? "Set an optional goal" : "Edit reading goal"}</Button>{savedTarget !== null && <Button disabled={busy} onClick={() => openReview(true)}>Clear reading goal</Button>}</div>}
      {editing && <><Input label="Completed readings goal" type="number" min={1} max={10000} step={1} value={draft} disabled={busy || uncertain} hint="Choose 1 to 10,000 completed readings. Saving requires a separate confirmation." onChange={event => { setDraft(event.target.value); setError(""); setNotice(""); }} />
        {draft.trim() && !valid && <p role="status">Enter a whole number from 1 to 10,000.</p>}
        <div className="calendar-review__actions"><Button disabled={busy || uncertain || !valid || target === savedTarget} onClick={() => openReview(false)}>Review goal change</Button><Button disabled={busy || uncertain} onClick={() => { setEditing(false); setDraft(savedTarget == null ? "" : String(savedTarget)); }}>Cancel goal editing</Button>{savedTarget !== null && <Button disabled={busy || uncertain} onClick={() => openReview(true)}>Clear reading goal</Button>}</div>
      </>}
      {uncertain && <><p>A previous goal change still needs confirmation. Retry it before making another change.</p><Button disabled={busy} onClick={() => { if (pending.current) setReview(pending.current); }}>Review unconfirmed goal change</Button></>}
    </>}
    <Dialog open={review !== null} onClose={() => { if (!busy) setReview(null); }} title={review?.values.target_readings === null ? "Clear this reading goal?" : "Save this reading goal?"} description="This private goal changes only your target. Your recorded time and reading history are kept." actions={<><Button disabled={busy} onClick={() => setReview(null)}>{uncertain ? "Close review" : "Keep current goal"}</Button><Button loading={busy} disabled={busy} onClick={() => void save()}>{uncertain ? "Retry same goal change" : review?.values.target_readings === null ? "Clear goal" : "Save reading goal"}</Button></>}>
      {review && <>{error && <Banner tone="warning">{error}</Banner>}<p>Calendar year: {year}</p><p>Current goal: {savedTarget === null ? "Unset" : `${savedTarget} completed readings`}</p><p>{review.values.target_readings === null ? "The goal will be unset." : `New goal: ${review.values.target_readings} completed readings, including rereads.`}</p>{uncertain && <p>The original request will be retried without duplicating the change.</p>}</>}
    </Dialog>
  </section>;
}
export default function ReadingGoal(props: Props) { const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration); return <Contents key={`${generation}:${props.year}`} {...props} />; }
