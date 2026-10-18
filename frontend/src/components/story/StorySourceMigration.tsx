import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Banner, Button, Dialog, Input } from "../ui";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { getQueuedProgress } from "../../services/progressSyncQueue";
import { chapterService } from "../../services/chapterService";
import { getUserFacingError } from "../../services/apiClient";
import { readingJournalOperationId } from "../../services/readingJournalService";
import { sourceMigrationService as service, readMigrationIntent, saveMigrationIntent, type MigrationChapter, type MigrationIntent, type MigrationMapping, type MigrationPage, type MigrationPreview, type MigrationRecord, type MigrationStory } from "../../services/sourceMigrationService";
import "./StorySourceMigration.css";
type Props = { novelId: number; libraryId: number };
const progressLabel = (story: MigrationStory) => story.current_progress?.chapter_number == null ? "No saved reading position" : `Chapter ${story.current_progress.chapter_number} · ${Math.round(story.current_progress.percent ?? 0)}%`;
const pendingFor = (...ids: number[]) => getQueuedProgress().filter(row => ids.includes(row.novelId));
const evidenceLabel = (value: string) => ({ stable_id: "Stable source identifier", source_id: "Stable source identifier", fingerprint: "Matching content fingerprint", content_fingerprint: "Matching content fingerprint", title: "Matching chapter title", normalized_title: "Matching chapter title" })[value] ?? value.replace(/_/g, " ");
const storyHref = (story: MigrationStory) => `/library/${story.library_id}/novels/${story.novel_id}`;
function Contents({ novelId, libraryId }: Props) {
  const generation = storageGeneration(), mounted = useRef(false), epoch = useRef(0), metadataEpoch = useRef(0);
  const [query, setQuery] = useState(""), [search, setSearch] = useState(""), [offset, setOffset] = useState(0), [historyOffset, setHistoryOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [targets, setTargets] = useState<MigrationPage<MigrationStory> | null>(null), [history, setHistory] = useState<MigrationPage<MigrationRecord> | null>(null);
  const [target, setTarget] = useState<MigrationStory | null>(null), [chapters, setChapters] = useState<MigrationChapter[]>([]);
  const [chapterPage, setChapterPage] = useState(0), [chapterTotal, setChapterTotal] = useState(0), [chapterLoading, setChapterLoading] = useState(false), [previewOffset, setPreviewOffset] = useState(0), [chapterRefresh, setChapterRefresh] = useState(0);
  const [preview, setPreview] = useState<MigrationPreview | null>(null), [mappings, setMappings] = useState<MigrationMapping[]>([]), [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [pending, setPending] = useState(() => pendingFor(novelId).length);
  const [attempt, setAttempt] = useState<MigrationIntent | null>(() => readMigrationIntent(novelId));
  const [confirm, setConfirm] = useState<"apply" | MigrationRecord | null>(null), [picker, setPicker] = useState<number | null>(null), [picked, setPicked] = useState("");
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let live = true; const version = ++metadataEpoch.current; setLoading(true); setTargets(null); setHistory(null);
    void Promise.allSettled([service.targets(novelId, search, offset, 20), service.history(novelId, historyOffset, 20)]).then(results => {
      if (!live || !current() || version !== metadataEpoch.current) return;
      const failures: string[] = [];
      if (results[0].status === "fulfilled") setTargets(results[0].value); else failures.push("Your existing source copies could not be loaded.");
      if (results[1].status === "fulfilled") setHistory(results[1].value); else failures.push("Transfer history could not be loaded.");
      if (failures.length) setError(failures.join(" ")); setLoading(false);
    });
    return () => { live = false; };
    // Account changes remount this workspace; page changes fence every response.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId, search, offset, historyOffset, refresh]);
  useEffect(() => {
    const update = () => setPending(pendingFor(novelId, target?.novel_id ?? -1).length);
    update(); const timer = window.setInterval(update, 1000); window.addEventListener("storage", update);
    return () => { clearInterval(timer); window.removeEventListener("storage", update); };
  }, [novelId, target?.novel_id]);
  useEffect(() => {
    if (picker === null || !target) return;
    let live = true; setChapterLoading(true); setChapters([]);
    void service.chapters(target.novel_id, chapterPage * 100, 100).then(page => {
      if (live && current()) { setChapters(page.items); setChapterTotal(page.total); }
    }).catch(err => { if (live && current()) setError(getUserFacingError(err, "Couldn’t load target chapters. Retry the chapter page.")); })
      .finally(() => { if (live && current()) setChapterLoading(false); });
    return () => { live = false; };
    // The selected target and account are fixed for each open picker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picker, chapterPage, target?.novel_id, chapterRefresh]);
  function blocked(...ids: number[]) {
    if (!pendingFor(...ids).length) return false;
    setPending(pendingFor(...ids).length); setError("Unsynchronized progress exists in one of these stories. Open its reader to review it before transferring or undoing. Nothing was discarded."); return true;
  }
  function retain(value: MigrationIntent | null) { saveMigrationIntent(novelId, value); setAttempt(value); }
  function changeMapping(source: number, value: number | null) {
    epoch.current++; setMappings(rows => [...rows.filter(row => row.source_chapter_id !== source), { source_chapter_id: source, target_chapter_id: value }]); setDirty(true); setConfirm(null); setNotice("");
  }
  async function buildPreview(nextOffset = previewOffset) {
    if (!target || busy || attempt || blocked(novelId, target.novel_id)) return;
    setBusy(true); setError(""); const version = ++epoch.current;
    try {
      const data = await service.preview({ source_novel_id: novelId, target_novel_id: target.novel_id, mappings }, nextOffset, 100);
      if (!current() || version !== epoch.current) return;
      setPreview(data); setPreviewOffset(nextOffset); setDirty(false); setNotice("Chapter matches are ready to review. No reading state has changed.");
    } catch (err) { if (current() && version === epoch.current) setError(getUserFacingError(err, "Couldn’t prepare a chapter preview.")); }
    finally { if (current() && version === epoch.current) setBusy(false); }
  }
  async function refreshConfirmed(value: MigrationIntent, id: number) {
    // Receipts are immutable. Read current state before accepting any reading snapshot.
    const record = await service.get(id);
    if (!current()) return;
    await Promise.all([chapterService.getReadingProgress(record.source.novel_id), chapterService.getReadingProgress(record.target.novel_id)]);
    if (!current()) return;
    const latest = await service.history(novelId, 0, 20);
    if (!current()) return;
    retain(null); setHistory(latest); setHistoryOffset(0); setPreview(null); setConfirm(null); setMappings([]); setDirty(false); setTarget(null); setChapters([]);
    setNotice(value.kind === "apply" ? "Transfer confirmed. Current reading state and transfer history have been refreshed. Both story copies are kept." : "Undo confirmed. Current reading state and transfer history have been refreshed.");
    setRefresh(count => count + 1);
  }
  async function submit(existing?: MigrationIntent) {
    if (busy) return;
    let value = existing ?? attempt;
    if (!value) {
      if (confirm === "apply" && preview?.can_apply && preview.review_token && !dirty && target) value = { kind: "apply", input: { source_novel_id: novelId, target_novel_id: target.novel_id, mappings, review_token: preview.review_token, operation_id: readingJournalOperationId() } };
      else if (confirm && confirm !== "apply") value = { kind: "undo", migration_id: confirm.id, source_novel_id: confirm.source.novel_id, target_novel_id: confirm.target.novel_id, input: { expected_revision: confirm.revision, operation_id: readingJournalOperationId() } };
    }
    if (!value) return;
    const sourceId = value.kind === "apply" ? value.input.source_novel_id : value.source_novel_id;
    const targetId = value.kind === "apply" ? value.input.target_novel_id : value.target_novel_id;
    if (!value.acknowledged_id && blocked(sourceId, targetId)) return;
    setBusy(true); setError(""); ++epoch.current; ++metadataEpoch.current; setLoading(false);
    try {
      retain(value); // Persist before the request, so reloads reuse the same operation.
      if (!value.acknowledged_id) {
        const receipt = value.kind === "apply" ? await service.apply(value.input) : await service.undo(value.migration_id, value.input);
        if (!current()) return;
        value = { ...value, acknowledged_id: receipt.id }; retain(value);
      }
      await refreshConfirmed(value, value.acknowledged_id!);
    } catch (err) {
      if (!current()) return;
      const rejected = axios.isAxiosError(err) && !!err.response && err.response.status >= 400 && err.response.status < 500 && ![408, 429].includes(err.response.status);
      if (rejected && !value.acknowledged_id) { retain(null); setConfirm(null); setPreview(null); setDirty(true); setRefresh(count => count + 1); }
      setError(getUserFacingError(err, value.acknowledged_id ? "The transfer was confirmed, but current state could not be refreshed. Refresh the confirmed transfer before making another change." : "The action could not be confirmed. Retry the same saved operation; do not submit a new transfer."));
    } finally { if (current()) setBusy(false); }
  }
  async function reviewUndo(record: MigrationRecord) {
    if (blocked(record.source.novel_id, record.target.novel_id)) return;
    setBusy(true); setError(""); const version = ++epoch.current;
    try { const latest = await service.get(record.id); if (current() && version === epoch.current) { if (!latest.can_undo) setError(latest.undo_blocked_reason ?? "This transfer can no longer be undone."); else setConfirm(latest); } }
    catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t review this transfer.")); }
    finally { if (current()) setBusy(false); }
  }
  const locked = busy || !!attempt;
  return <section className="story-source-migration" aria-label="Source migration">
    <h2>Continue with another source</h2>
    <p>Choose another copy already in your own library, review its chapter matches, and transfer your reading place. This does not search or download from source sites.</p>
    <p>Both story copies stay in your library. The reading continues with one shared history and completion identity. Audio, translations and downloaded content stay with their original copy.</p>
    {error && confirm === null && picker === null && <Banner tone="warning">{error}</Banner>}{notice && <p role="status">{notice}</p>}
    {pending > 0 && <Banner tone="warning">Unsynchronized progress must be reviewed first. <Link to={`/library/${libraryId}/novels/${novelId}`}>Open this story</Link>{target && <> or <Link to={storyHref(target)}>open the target story</Link></>}. Pending writes are kept.</Banner>}
    {attempt && <section aria-label="Pending source transfer"><h3>A saved action needs confirmation</h3><p>Changing accounts or reloading does not create another operation. Confirm this saved action before making a new transfer.</p><Button disabled={busy} onClick={() => void submit(attempt)}>{attempt.acknowledged_id ? "Refresh confirmed transfer" : attempt.kind === "apply" ? "Retry same transfer" : "Retry same undo"}</Button></section>}
    <form onSubmit={event => { event.preventDefault(); if (!locked) { setSearch(query.trim()); setOffset(0); setRefresh(count => count + 1); } }}>
      <Input label="Find an existing copy in your library" maxLength={200} value={query} disabled={locked} onChange={event => setQuery(event.target.value)} />
      <div className="story-source-migration__actions"><Button type="submit" disabled={locked}>Search my copies</Button><Button disabled={locked} variant="secondary" onClick={() => { setError(""); setRefresh(count => count + 1); }}>Refresh copies and history</Button></div>
    </form>
    {loading && <p role="status">Loading your copies and transfer history…</p>}
    {targets && <section aria-label="Existing target copies"><h3>Choose the target copy</h3>{targets.total === 0 && <p>No other matching copies are in your library. Add the target story to your library first.</p>}
      <ul className="story-source-migration__list">{targets.items.map(row => <li key={row.novel_id}><h4>{row.title}</h4><p>{row.site ?? "Local copy"} · {row.chapter_count} chapters</p><p>{progressLabel(row)}</p>{row.blocked_reason && <p>{row.blocked_reason}</p>}<Button disabled={locked || !row.eligible} aria-pressed={target?.novel_id === row.novel_id} onClick={() => { ++epoch.current; setTarget(row); setPreview(null); setPreviewOffset(0); setMappings([]); setDirty(false); setError(""); setNotice(""); }}>Choose {row.title}</Button></li>)}</ul>
      <nav className="story-source-migration__actions" aria-label="Target copy pages"><Button disabled={locked || offset === 0} onClick={() => setOffset(count => count - 20)}>Previous copies</Button><span>{targets.total ? targets.offset + 1 : 0}–{Math.min(targets.offset + targets.items.length, targets.total)} of {targets.total} copies</span><Button disabled={locked || offset + targets.limit >= targets.total} onClick={() => setOffset(count => count + 20)}>Next copies</Button></nav>
    </section>}
    {target && <section aria-label="Chapter match review"><h3>Target: {target.title}</h3><p>Only a target without existing reading state can receive this transfer. Source chapters and earlier notes remain available.</p><div className="story-source-migration__actions"><Button variant="primary" disabled={locked || pending > 0} onClick={() => void buildPreview()}>{preview ? "Review changed chapter matches" : "Build chapter preview"}</Button></div>
      {preview && <><p>{preview.counts.mapped} mapped · {preview.counts.skipped} skipped · {preview.counts.unresolved} unresolved chapters</p><p>Copyable annotations: {preview.counts.annotations_copied} · retained only in the original copy: {preview.counts.annotations_retained} · {preview.counts.receipts_copied} reading evidence records and {preview.counts.history_copied} reading checkpoints can be copied</p><p>{preview.counts.preferences_copied ? "Reader appearance settings will be copied because the target has none." : "Target reader appearance settings stay unchanged."} {preview.counts.followed_categories_copied ? "Followed chapter categories will be copied." : "Target followed chapter categories stay unchanged."}</p><p>Personal notes, ratings, automatic downloads and notifications are not transferred. Permissions for sending text to external providers stay with the original copy.</p><p>Only exact matching content keeps passage anchors. Other matched reading positions are approximate; changed-text annotations remain in the original copy.</p>{preview.warnings.map((warning, index) => <Banner key={index} tone="warning">{warning}</Banner>)}{dirty && <Banner tone="warning">Chapter choices changed. Build a new preview before confirming.</Banner>}
        <ol className="story-source-migration__list">{preview.items.map(row => {
          const override = mappings.find(mapping => mapping.source_chapter_id === row.source_chapter_id);
          const selected = override ? override.target_chapter_id === null ? "skip" : String(override.target_chapter_id) : "";
          const extra = override?.target_chapter_id != null && !row.candidates.some(candidate => candidate.target_chapter_id === override.target_chapter_id) ? chapters.find(chapter => chapter.id === override.target_chapter_id) : null;
          return <li key={row.source_chapter_id}><h4>Chapter {row.source_chapter_number}{row.source_title ? ` · ${row.source_title}` : ""}</h4><p>{row.decision === "ambiguous" ? "Ambiguous match · choose explicitly" : row.decision === "unmatched" ? "No automatic match" : row.decision === "skipped" ? "Skipped" : row.approximate_position ? "Matched · approximate position" : "Matched"}{row.required_for_progress ? " · required for current or furthest progress" : ""}</p>
            <label>Target for chapter {row.source_chapter_number}<select disabled={locked} value={selected} onChange={event => { if (event.target.value === "other") { setPicker(row.source_chapter_id); setChapterPage(0); setPicked(""); } else if (event.target.value === "") { setMappings(rows => rows.filter(mapping => mapping.source_chapter_id !== row.source_chapter_id)); setDirty(true); setConfirm(null); } else changeMapping(row.source_chapter_id, event.target.value === "skip" ? null : Number(event.target.value)); }}>
              <option value="">{row.selected_target_chapter_id != null ? `Suggested chapter ${row.candidates.find(candidate => candidate.target_chapter_id === row.selected_target_chapter_id)?.chapter_number ?? "match"}` : "Choose a chapter match"}</option><option value="skip" disabled={row.required_for_progress}>Skip; keep original annotations</option>{row.candidates.map(candidate => <option key={candidate.target_chapter_id} value={candidate.target_chapter_id}>Chapter {candidate.chapter_number}{candidate.title ? ` · ${candidate.title}` : ""}</option>)}{override?.target_chapter_id != null && !row.candidates.some(candidate => candidate.target_chapter_id === override.target_chapter_id) && <option value={override.target_chapter_id}>{extra ? `Chapter ${extra.chapter_number} · ${extra.title ?? "Selected chapter"}` : `Selected target chapter ID ${override.target_chapter_id}`}</option>}<option value="other">Choose another target chapter…</option>
            </select></label>
            {row.candidates.length > 0 && <details><summary>Match evidence for chapter {row.source_chapter_number}</summary><ul>{row.candidates.map(candidate => <li key={candidate.target_chapter_id}>Chapter {candidate.chapter_number}: {candidate.evidence.map(evidenceLabel).join(", ") || "Manual comparison required"}{candidate.content_equal ? " · identical saved text" : " · text is different or unverified"}</li>)}</ul></details>}{row.candidates_truncated && <p>Only the strongest 20 candidates are shown. Choose another target chapter to inspect the remaining chapters.</p>}<p>{row.annotation_count} original annotations · {row.annotations_copyable} copyable{row.receipt_copyable ? " · reading evidence matches" : ""}</p>
          </li>;
        })}</ol>
        <nav className="story-source-migration__actions" aria-label="Chapter match pages"><Button disabled={locked || previewOffset === 0} onClick={() => void buildPreview(Math.max(0, previewOffset - 100))}>Previous chapter matches</Button><span>{preview.total ? preview.offset + 1 : 0}–{Math.min(preview.offset + preview.items.length, preview.total)} of {preview.total} chapters</span><Button disabled={locked || previewOffset + preview.limit >= preview.total} onClick={() => void buildPreview(previewOffset + 100)}>Next chapter matches</Button></nav>
        <Button variant="primary" disabled={locked || dirty || !preview.can_apply || !preview.review_token || pending > 0} onClick={() => setConfirm("apply")}>Review transfer</Button>
      </>}
    </section>}
    <section aria-label="Source transfer history"><h3>Transfer history</h3>{history?.total === 0 && <p>No source transfers have been recorded for this story.</p>}{history && <><ol className="story-source-migration__list">{history.items.map(record => <li key={record.id}><h4>{record.source.title} → {record.target.title}</h4><p>{record.status === "undone" ? "Undone" : "Applied"} · {new Date(record.created_at).toLocaleString()}</p><p>{record.counts.mapped} chapters mapped · {record.counts.annotations_copied} annotations copied · {record.counts.annotations_retained} retained in the source · {record.counts.history_copied} reading checkpoints copied</p><div className="story-source-migration__actions"><Link to={`${storyHref(record.source)}?tab=history`}>Original reading history</Link><Link to={storyHref(record.target)}>Open target copy</Link></div>{record.undo_blocked_reason && <p>{record.undo_blocked_reason}</p>}{record.status === "applied" && <Button disabled={locked || !record.can_undo || pending > 0} onClick={() => void reviewUndo(record)}>Review undo transfer {record.id}</Button>}</li>)}</ol><nav className="story-source-migration__actions" aria-label="Transfer history pages"><Button disabled={locked || historyOffset === 0} onClick={() => setHistoryOffset(count => count - 20)}>Previous transfers</Button><span>{history.total ? history.offset + 1 : 0}–{Math.min(history.offset + history.items.length, history.total)} of {history.total} transfers</span><Button disabled={locked || historyOffset + history.limit >= history.total} onClick={() => setHistoryOffset(count => count + 20)}>Next transfers</Button></nav></>}</section>
    <Dialog open={confirm !== null} className="source-migration-dialog" onClose={() => { if (!busy) setConfirm(null); }} title={confirm === "apply" ? "Confirm source transfer" : "Confirm source transfer undo"} actions={<><Button disabled={busy} onClick={() => setConfirm(null)}>Keep current reading state</Button><Button variant={confirm === "apply" ? "primary" : "danger"} disabled={busy || pending > 0 || !!attempt} onClick={() => void submit()}>{confirm === "apply" ? "Confirm transfer" : "Undo reviewed transfer"}</Button></>}>
      {error && <Banner tone="warning">{error}</Banner>}
      {confirm === "apply" && preview ? <><p>Continue from <strong>{preview.source.title}</strong> in <strong>{preview.target.title}</strong>.</p><p>{progressLabel(preview.source)}</p><p>Chapter matches: {preview.counts.mapped}. Copyable annotations: {preview.counts.annotations_copied}. Annotations retained only in the original copy: {preview.counts.annotations_retained}.</p><p>Both copies and your shared reading history are kept. Downloaded content, audio and translations are not moved. Ambiguous chapter choices require your explicit review.</p></> : confirm && confirm !== "apply" ? <><p>Undo the transfer from {confirm.source.title} to {confirm.target.title}.</p><p>The target returns to a blank reading session with a new identity. Later target changes prevent undo. Original content and reading history are preserved.</p></> : null}
    </Dialog>
    <Dialog open={picker !== null} className="source-migration-dialog" onClose={() => setPicker(null)} title="Choose a target chapter" actions={<><Button onClick={() => setPicker(null)}>Cancel chapter choice</Button><Button disabled={!picked || chapterLoading} onClick={() => { if (picker !== null && picked) changeMapping(picker, Number(picked)); setPicker(null); }}>Use selected chapter</Button></>}>{error && <Banner tone="warning">{error}</Banner>}{chapterLoading && <p role="status">Loading target chapters…</p>}<label className="story-source-migration">Target chapter<select aria-label="Target chapter" value={picked} onChange={event => setPicked(event.target.value)}><option value="">Choose an existing chapter</option>{chapters.map(chapter => <option key={chapter.id} value={chapter.id}>Chapter {chapter.chapter_number}{chapter.title ? ` · ${chapter.title}` : ""}</option>)}</select></label><div className="story-source-migration__actions"><Button disabled={chapterLoading} onClick={() => setChapterRefresh(count => count + 1)}>Refresh target chapter page</Button></div><nav className="story-source-migration__actions" aria-label="Target chapter pages"><Button disabled={chapterLoading || chapterPage === 0} onClick={() => { setPicked(""); setChapterPage(page => page - 1); }}>Previous target chapters</Button><span>{chapterTotal ? chapterPage * 100 + 1 : 0}–{Math.min(chapterPage * 100 + chapters.length, chapterTotal)} of {chapterTotal} chapters</span><Button disabled={chapterLoading || (chapterPage + 1) * 100 >= chapterTotal} onClick={() => { setPicked(""); setChapterPage(page => page + 1); }}>Next target chapters</Button></nav><p>This is an explicit match, not an automatic merge. Review the new preview before confirming.</p></Dialog>
  </section>;
}
export default function StorySourceMigration(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props} />;
}
