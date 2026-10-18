import "./StoryReadingHistory.css";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Banner, Button, Dialog, TextArea } from "../ui";
import { readingJournalService, readingJournalOperationId, type ReadingJournalPage, type ReadingRunsPage, type ReadingRunAction, type ReadingRunChange, type ReadingRun, type ReadingRunProgress } from "../../services/readingJournalService";
import { chapterService } from "../../services/chapterService";
import { getQueuedProgress } from "../../services/progressSyncQueue";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
type Props = { novelId: number; libraryId: number };
type Review = { action: ReadingRunAction; state: ReadingRunsPage };
type Attempt = Review & { payload: ReadingRunChange };
const snapshotPosition = (progress: ReadingRunProgress | null | undefined, fallback: string) => {
  if (progress?.chapter_number == null) return fallback;
  const percent = progress.percent;
  return `Chapter ${progress.chapter_number} · ${typeof percent === "number" && Number.isFinite(percent) ? `${Math.round(percent)}%` : "position not recorded"}`;
};
const position = (state: ReadingRunsPage) => snapshotPosition(state.current_progress, "No saved position yet");
const dateLabel = (value: string | null, inferred: boolean) => {
  const date = value ? new Date(value) : null;
  const label = date && Number.isFinite(date.getTime()) ? date.toLocaleString() : "Date unknown";
  return inferred ? `${label} · inferred from earlier records` : label;
};
const actionTitle: Record<ReadingRunAction, string> = { start: "Start this story again?", finish: "Mark this reading finished?", drop: "Stop this reading?" };
const actionLabel: Record<ReadingRunAction, string> = { start: "Start new reading", finish: "Mark reading finished", drop: "Stop reading" };
function Contents({ novelId, libraryId }: Props) {
  const navigate = useNavigate(), generation = storageGeneration();
  const mounted = useRef(false), epoch = useRef(0), attempt = useRef<Attempt | null>(null);
  const [currentRun, setCurrentRun] = useState<ReadingRun | null>(null);
  const [runs, setRuns] = useState<ReadingRunsPage | null>(null), [journal, setJournal] = useState<ReadingJournalPage | null>(null);
  const [runPage, setRunPage] = useState(0), [journalPage, setJournalPage] = useState(0), [refresh, setRefresh] = useState(0);
  const [pendingCount, setPendingCount] = useState(() => getQueuedProgress().filter(row => row.novelId === novelId).length);
  const [review, setReview] = useState<Review | null>(null), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [loadError, setLoadError] = useState(""), [notice, setNotice] = useState("");
  const current = () => mounted.current && generation === storageGeneration();
  const pending = () => getQueuedProgress().filter(row => row.novelId === novelId);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let live = true, loading = false;
    const load = async () => {
      if (loading) return;
      loading = true; const version = epoch.current;
      const results = await Promise.allSettled([readingJournalService.runs(novelId, runPage * 20, 20), readingJournalService.journal(novelId, journalPage * 20, 20)]);
      if (live && generation === storageGeneration() && version === epoch.current) {
        const messages: string[] = [];
        if (results[0].status === "fulfilled") {
          const value = results[0].value; setRuns(value);
          setCurrentRun(previous => value.items.find(row => row.reading_run_key === value.current_run_key) ?? (previous?.reading_run_key === value.current_run_key ? previous : null));
        } else messages.push("Reading history could not be refreshed.");
        if (results[1].status === "fulfilled") setJournal(results[1].value); else messages.push("Your journal could not be refreshed.");
        setLoadError(messages.join(" "));
      }
      loading = false;
    };
    void load(); const timer = window.setInterval(() => void load(), 4000);
    return () => { live = false; window.clearInterval(timer); };
  }, [novelId, generation, runPage, journalPage, refresh]);
  useEffect(() => {
    const check = () => setPendingCount(getQueuedProgress().filter(row => row.novelId === novelId).length);
    const timer = window.setInterval(check, 1000); window.addEventListener("focus", check); window.addEventListener("storage", check);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", check); window.removeEventListener("storage", check); };
  }, [novelId]);
  const openReview = (action: ReadingRunAction) => {
    if (!runs || busy) return;
    setError(""); setNotice("");
    if (attempt.current) { setReview(attempt.current); return; }
    if (action === "start" && pending().length) { setPendingCount(pending().length); setError("Open the reader to review unsynchronized progress before starting again. Your pending position has been kept."); return; }
    setReason(""); setReview({ action, state: runs });
  };
  const submit = async () => {
    if (!review || busy) return;
    if (review.action === "start" && pending().length) { setPendingCount(pending().length); setError("New unsynchronized progress was found. Open the reader to review it before starting again. Nothing was discarded."); return; }
    const saved = attempt.current ?? { ...review, payload: { expected_revision: review.state.revision, operation_id: readingJournalOperationId(), reading_run_key: review.state.current_run_key, ...(review.action === "drop" && reason.trim() ? { reason: reason.trim() } : {}) } };
    attempt.current = saved; setBusy(true); setError(""); epoch.current++;
    try {
      const changed = await readingJournalService.change(novelId, saved.action, saved.payload);
      if (!current()) return;
      if (changed.current_progress) await chapterService.acceptReadingRun(novelId, changed.current_progress);
      if (!current()) return;
      attempt.current = null; setUncertain(false); setReview(null); setRuns(changed); setCurrentRun(changed.items.find(row => row.reading_run_key === changed.current_run_key) ?? null); setRunPage(0); setRefresh(value => value + 1);
      setNotice(saved.action === "finish" ? "This reading is marked finished. Its completion stays in your history." : saved.action === "drop" ? "This reading was stopped. Your position and earlier readings are kept." : "A new reading has started. Earlier readings and their completion history are kept.");
      const first = changed.first_chapter_number ?? changed.current_progress?.chapter_number;
      if (saved.action === "start" && first != null) navigate(`/library/${libraryId}/novels/${novelId}/${first}`);
    } catch (err) {
      if (!current()) return;
      if (axios.isAxiosError(err) && err.response && err.response.status >= 400 && err.response.status < 500 && ![408, 429].includes(err.response.status)) {
        attempt.current = null; setUncertain(false); setReview(null); setRefresh(value => value + 1);
        setError(getUserFacingError(err, "Your reading position changed. Review the latest position before trying again."));
      } else {
        setUncertain(true); setError(getUserFacingError(err, "The change could not be confirmed. Retry this same action to check it safely; a second reading will not be created."));
      }
    } finally { epoch.current++; if (current()) setBusy(false); }
  };
  const readerChapter = runs?.current_progress?.chapter_number ?? runs?.first_chapter_number ?? 1;
  return <section className="story-reading-history" aria-label="Private reading history">
    <h2>Reading history</h2><p>Your readings and journal are private to your account. Starting again preserves earlier readings and their completion history.</p>
    {error && !review && <Banner tone="warning">{error}</Banner>}{loadError && <Banner tone="warning">{loadError}</Banner>}{notice && <p role="status">{notice}</p>}
    {!runs && <p role="status">Loading your reading history…</p>}
    {runs && <section aria-label="Current reading"><h3>Current reading</h3><p>{position(runs)}</p><p>{currentRun ? `Reading ${currentRun.ordinal} · ${currentRun.status === "completed" ? "Finished" : currentRun.status === "abandoned" ? "Stopped" : "In progress"}` : "No recorded reading yet"}</p>
      {pendingCount > 0 && <Banner tone="warning">You have unsynchronized progress for this story. <Link to={`/library/${libraryId}/novels/${novelId}/${readerChapter}`}>Open reader to review unsynchronized progress</Link>. Starting again is paused; your pending position is kept.</Banner>}
      {uncertain && <p role="status">A previous action still needs confirmation. Retry that same action before making another reading change.</p>}
      <div className="story-reading-history__actions">
        <Button disabled={busy || pendingCount > 0 || uncertain} onClick={() => openReview("start")}>Start again</Button>
        <Button disabled={busy || uncertain || currentRun?.status === "completed" || !!currentRun?.completed_at || currentRun?.completed_at_inferred} onClick={() => openReview("finish")}>Finish this reading</Button>
        <Button disabled={busy || uncertain || currentRun?.status === "abandoned"} onClick={() => openReview("drop")}>Stop this reading</Button>
        {uncertain && <Button disabled={busy} onClick={() => { if (attempt.current) setReview(attempt.current); }}>Review pending reading change</Button>}
      </div>
    </section>}
    {runs && <section aria-label="Saved readings"><h3>Saved readings</h3>{runs.total === 0 && <p>There are no saved readings yet.</p>}
      <ol className="story-reading-history__list">{runs.items.map(run => <li key={run.reading_run_key}><h4>Reading {run.ordinal}{run.reading_run_key === runs.current_run_key ? " · Current" : ""}</h4><p>{run.status === "completed" ? "Finished" : run.status === "abandoned" ? "Stopped" : run.archived_at ? "Earlier unfinished reading" : "In progress"}</p>
        <p>Started: {dateLabel(run.started_at, run.started_at_inferred)}</p>{(run.completed_at || run.status === "completed") && <p>Finished: {dateLabel(run.completed_at, run.completed_at_inferred)}</p>}{run.abandoned_at && <p>Stopped: {dateLabel(run.abandoned_at, false)}</p>}{run.abandon_reason && <p>Reason: {run.abandon_reason}</p>}
        <p>Last position: {snapshotPosition(run.progress, "Not recorded")}</p>
      </li>)}</ol>
      <nav className="story-reading-history__actions" aria-label="Reading history pages"><Button disabled={busy || runPage === 0 || runs.offset !== runPage * 20} onClick={() => setRunPage(value => value - 1)}>Previous readings</Button><span>{runs.total ? runs.offset + 1 : 0}–{Math.min(runs.offset + runs.items.length, runs.total)} of {runs.total} readings</span><Button disabled={busy || runs.offset !== runPage * 20 || (runPage + 1) * 20 >= runs.total} onClick={() => setRunPage(value => value + 1)}>Next readings</Button></nav>
    </section>}
    <section aria-label="Private reading journal"><h3>Your journal</h3>{!journal && <p role="status">Loading journal…</p>}{journal?.total === 0 && <p>New reading changes will appear here. Older records may have unknown or inferred dates.</p>}
      {journal && <><ol className="story-reading-history__list">{journal.items.map(entry => <li key={entry.id}><p><strong>{entry.kind === "started" ? "Started" : entry.kind === "completed" ? "Finished" : "Stopped"}</strong> · Reading {entry.ordinal}</p><p>{dateLabel(entry.occurred_at, entry.inferred)}</p>{entry.reason && <p>Reason: {entry.reason}</p>}</li>)}</ol>
        <nav className="story-reading-history__actions" aria-label="Reading journal pages"><Button disabled={busy || journalPage === 0 || journal.offset !== journalPage * 20} onClick={() => setJournalPage(value => value - 1)}>Previous journal entries</Button><span>{journal.total ? journal.offset + 1 : 0}–{Math.min(journal.offset + journal.items.length, journal.total)} of {journal.total} journal entries</span><Button disabled={busy || journal.offset !== journalPage * 20 || (journalPage + 1) * 20 >= journal.total} onClick={() => setJournalPage(value => value + 1)}>Next journal entries</Button></nav>
      </>}
    </section>
    <Dialog open={review !== null} onClose={() => { if (!busy) setReview(null); }} title={review ? actionTitle[review.action] : "Review reading change"} description={review?.action === "start" ? "Start a new reading at the first chapter. Your previous reading, completion history and notes are preserved." : review?.action === "finish" ? "Record that you finished this reading. Your saved position stays where it is." : "Stop this reading while keeping your place and all earlier reading history. A reason is optional."} actions={<><Button disabled={busy} onClick={() => setReview(null)}>{uncertain ? "Close review" : "Keep current reading"}</Button><Button variant={review?.action === "drop" ? "danger" : "primary"} disabled={busy || (review?.action === "start" && pendingCount > 0)} loading={busy} onClick={() => void submit()}>{uncertain ? "Retry same reading change" : review ? actionLabel[review.action] : "Confirm reading change"}</Button></>}>
      {review && <>{error && <Banner tone="warning">{error}</Banner>}<p>Existing position: {position(review.state)}</p>{review.action === "start" && <p>The new reading starts {review.state.first_chapter_number != null ? `at chapter ${review.state.first_chapter_number}` : "at the first available chapter"}. Previous completions remain in your history.</p>}{review.action === "drop" && <TextArea label="Reason for stopping (optional)" maxLength={500} rows={3} value={reason} disabled={busy || uncertain} onChange={event => setReason(event.target.value)} hint="Up to 500 characters. This stays private." />}{uncertain && <p>The same saved request will be retried to avoid duplicating your action.</p>}</>}
    </Dialog>
  </section>;
}
export default function StoryReadingHistory(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props} />;
}
