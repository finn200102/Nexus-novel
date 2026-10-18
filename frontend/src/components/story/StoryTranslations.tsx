import {chapterIdentity} from "../../services/chapterIdentity";
import "./StoryTranslations.css";
import StoryTranslationCreation from "./StoryTranslationCreation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Banner, Button, Checkbox, Dialog } from "../ui";
import { readerToolsService, type StoryTranslation, type StoryTranslationsPage } from "../../services/readerToolsService";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";

type Props = { novelId: number; libraryId: number };
const active = (row: StoryTranslation) => ["queued", "processing", "retry_wait"].includes(row.status);
const labels: Record<string, string> = { queued: "Queued", processing: "Translating", retry_wait: "Waiting to retry", completed: "Completed", failed: "Needs attention", cancelled: "Cancelled" };
function Contents({ novelId, libraryId }: Props) {
  const generation = storageGeneration();
  const mounted = useRef(false), epoch = useRef(0);
  const [page, setPage] = useState(0), [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<StoryTranslationsPage | null>(null);
  const [selected, setSelected] = useState<StoryTranslation[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [retry, setRetry] = useState<StoryTranslation | null>(null);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let live = true, pending = false;
    const load = async () => {
      if (pending) return;
      pending = true; const version = epoch.current;
      try {
        const result = await readerToolsService.storyTranslations(novelId, page * 50, 50);
        if (live && generation === storageGeneration() && version === epoch.current) { setData(result); setLoadError(""); }
      } catch (err) { if (live && generation === storageGeneration() && version === epoch.current) setLoadError(getUserFacingError(err, "Couldn’t refresh saved translations. Connect to Nexus and retry.")); }
      finally { pending = false; }
    };
    void load(); const timer = window.setInterval(() => void load(), 3000);
    return () => { live = false; window.clearInterval(timer); };
  }, [novelId, generation, page, refresh]);
  const choose = (row: StoryTranslation, checked: boolean) => {
    if (!checked) { setSelected(items => items.filter(item => item.id !== row.id)); return; }
    if (!row.exportable) return;
    if (selected.length && selected[0].language !== row.language) { setError("Choose one translation language per EPUB. Clear your selection to change language."); return; }
    const next = [...selected.filter(item => item.chapter_id !== row.chapter_id), row];
    if (next.length > 200) { setError("Select at most 200 chapters for one EPUB."); return; }
    setSelected(next.sort((a, b) => (a.chapter_number ?? a.chapter_number_snapshot ?? 0) - (b.chapter_number ?? b.chapter_number_snapshot ?? 0))); setError("");
  };
  const action = async (row: StoryTranslation, operation: "cancel" | "retry") => {
    if (busy) return;
    setBusy(true); epoch.current++; setError("");
    try { await readerToolsService.action(row.id, operation); if (current()) { setRetry(null); setRefresh(value => value + 1); } }
    catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t update this translation. Your saved paragraphs are preserved.")); }
    finally { epoch.current++; if (current()) setBusy(false); }
  };
  const exportSelected = async () => {
    if (busy || !selected.length) return;
    setBusy(true); epoch.current++; setError("");
    try {
      const blob = await readerToolsService.exportStoryTranslations(novelId, selected.map(row => row.id));
      if (!current()) return;
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = `translated-story-${novelId}-${selected[0].language}.epub`;
      document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t export these variants. Check that each is completed and matches the current source.")); }
    finally { epoch.current++; if (current()) setBusy(false); }
  };
  return <section className="story-translations" aria-label="Story translations">
    <h2>Translations</h2>
    <p>Review your saved chapter translations and combine selected completed variants into a private EPUB. Opening this page and exporting use no translation provider.</p>
    <p>To translate a new chapter, open it in the reader and choose Translation. Original text is always kept.</p>
    <StoryTranslationCreation novelId={novelId} libraryId={libraryId} onQueued={() => setRefresh(value => value + 1)} />
    {error && <Banner tone="warning">{error}</Banner>}
    {loadError && <Banner tone="warning">{loadError}</Banner>}
    {!data && <p role="status">Loading saved translations…</p>}
    {data?.total === 0 && <p>No saved translations yet. Start with a chapter in the reader.</p>}
    {data && <>
      <p role="status">{data.total} saved translation variants</p>
      <ul className="story-translations__variants">{data.items.map(row => <li key={row.id}>
        <h3>Chapter {row.chapter_number ?? row.chapter_number_snapshot ?? "unresolved"}: {row.chapter_title || "Untitled chapter"}</h3>
        <p>{row.language} · {labels[row.status] || row.status} · {row.completed_blocks} of {row.total_blocks} paragraphs</p>
        <p>Provider: {row.provider.kind} · {row.provider.model}</p>
        <p>{row.source_current ? "Matches the current source." : "This saved variant differs from the current source or address. Completed aligned variants can still be exported as their saved edition."}</p>
        <details><summary>Source versions for variant {row.id}</summary><p>Saved: <code>{row.source_version}</code></p><p>Current: <code>{row.current_source_version || "Unavailable"}</code></p></details>
        {row.error && <p>{row.error}</p>}
        {active(row) && <progress aria-label={`Translation ${row.id} progress`} value={row.completed_blocks} max={Math.max(1, row.total_blocks)} />}
        <Checkbox label={`Export chapter ${row.chapter_number}, ${row.language}, variant ${row.id}`} disabled={busy || !row.exportable} checked={selected.some(item => item.id === row.id)} onChange={event => choose(row, event.target.checked)} />
        {!row.exportable && <p>EPUB selection requires a completed, aligned saved translation.</p>}
        <div className="story-translations__actions">{chapterIdentity(row) && row.chapter_number != null && !row.chapter_archived ? <Link to={`/library/${libraryId}/novels/${novelId}/${row.chapter_number}?chapter_key=${encodeURIComponent(chapterIdentity(row)!.chapter_key)}`}>Read chapter {row.chapter_number}</Link> : <span>Saved chapter retained; its current reading address is unavailable.</span>}
          {active(row) && <Button disabled={busy} onClick={() => void action(row, "cancel")}>Cancel translation {row.id}</Button>}
          {["failed", "cancelled"].includes(row.status) && <Button disabled={busy} onClick={() => setRetry(row)}>Retry translation {row.id}</Button>}
        </div>
      </li>)}</ul>
      <nav className="story-translations__actions" aria-label="Saved translation pages"><Button disabled={busy || page === 0 || data.offset !== page * 50} onClick={() => setPage(value => value - 1)}>Previous translations</Button><span>{data.total ? data.offset + 1 : 0}–{Math.min(data.offset + data.items.length, data.total)} of {data.total}</span><Button disabled={busy || data.offset !== page * 50 || (page + 1) * 50 >= data.total} onClick={() => setPage(value => value + 1)}>Next translations</Button></nav>
    </>}
    <section aria-label="Translated EPUB selection"><h3>Translated EPUB</h3><p>Choose one variant per chapter, all in the same language. Selecting another variant of a chapter replaces its earlier selection. Omitted chapters are left out; this does not generate missing translations.</p>
      <p role="status">{selected.length} chapters selected{selected.length ? ` · ${selected[0].language}` : ""}</p>
      {selected.length > 0 && <ul>{selected.map(row => <li key={row.id}>Chapter {row.chapter_number ?? row.chapter_number_snapshot ?? "unresolved"} · variant {row.id}<Button disabled={busy} onClick={() => setSelected(items => items.filter(item => item.id !== row.id))}>Remove selected variant {row.id}</Button></li>)}</ul>}
      <div className="story-translations__actions"><Button disabled={busy || !selected.length} onClick={() => setSelected([])}>Clear EPUB selection</Button><Button variant="primary" disabled={busy || !selected.length} onClick={() => void exportSelected()}>Download translated EPUB</Button></div>
    </section>
    <Dialog open={retry !== null} onClose={() => { if (!busy) setRetry(null); }} title="Retry this translation?" description="Retrying resumes saved paragraphs using the configured provider and may incur API charges. Your provider permissions and budget still apply. No other chapters are queued." actions={<><Button disabled={busy} onClick={() => setRetry(null)}>Keep saved translation</Button><Button loading={busy} onClick={() => { if (retry) void action(retry, "retry"); }}>Retry selected translation</Button></>} />
  </section>;
}
export default function StoryTranslations(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props} />;
}
