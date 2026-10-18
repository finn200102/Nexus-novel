import { useEffect, useRef, useState } from "react";
import { Banner, Button, Dialog } from "../ui";
import { offlineLibraryStore, type OfflineCleanupKind, type OfflineCleanupPreview, type OfflineStoryInventory } from "../../services/offlineLibraryStore";
import { storageGeneration } from "../../services/accountStorage";
import { offlineBytes } from "./offlineLabels";
type Props = { story: OfflineStoryInventory; onClose: () => void; onRemoved: (message: string) => Promise<void> };
const names: Record<OfflineCleanupKind, string> = { text: "Text and embedded images", audio: "Audio and unfinished audio parts", translations: "Translated chapters" };
export default function OfflineCleanupDialog({ story, onClose, onRemoved }: Props) {
  const mounted = useRef(false), epoch = useRef(0), generation = storageGeneration();
  const [kinds, setKinds] = useState<OfflineCleanupKind[]>([]), [preview, setPreview] = useState<OfflineCleanupPreview | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; epoch.current += 1; }; }, []);
  const available = { text: story.chapters.some(row => row.text.ready || row.text.bytes > 0), audio: story.chapters.some(row => row.audio.bytes > 0 || row.audio.partial_bytes > 0 || row.audio.job_status != null || row.audio.busy), translations: story.chapters.some(row => row.translations.length > 0) };
  async function review() {
    if (!kinds.length || busy || !current()) return;
    const version = ++epoch.current; setBusy(true); setError("");
    try { const result = await offlineLibraryStore.previewCleanup({ novel_id: story.novel_id, kinds }); if (current() && version === epoch.current) setPreview(result); }
    catch { if (current() && version === epoch.current) setError("Couldn’t review these offline files. Refresh your offline library and try again."); }
    finally { if (current() && version === epoch.current) setBusy(false); }
  }
  async function remove() {
    if (!preview || busy || preview.busy_chapters.length || !current()) return;
    setBusy(true); setError("");
    try {
      const result = await offlineLibraryStore.cleanup(preview);
      if (!current()) return;
      await onRemoved(`Removed ${result.removed_records} local records (${offlineBytes(result.removed_bytes)}). Server files and reading progress are kept.`);
      if (current()) onClose();
    } catch (err) {
      if (!current()) return;
      setPreview(null);
      setError(err instanceof Error && err.name === "OfflineAudioBusyError" ? "Audio work is using these files. Nothing was removed. Wait for it to finish, then review cleanup again." : "Offline files changed or could not be removed. Review cleanup again; newer files are kept.");
    } finally { if (current()) setBusy(false); }
  }
  return <Dialog open title={preview ? "Review offline cleanup" : `Manage offline files for ${story.novel_title || `Story ${story.novel_id}`}`} onClose={() => { if (!busy) onClose(); }} actions={<>
    <Button disabled={busy} onClick={onClose}>Keep offline files</Button>
    {preview ? <Button disabled={busy || preview.records === 0 || preview.busy_chapters.length > 0} onClick={() => void remove()}>Remove reviewed offline files</Button> : <Button disabled={busy || !kinds.length} onClick={() => void review()}>Review cleanup</Button>}
  </>}>
    <p>Choose local files to remove for {story.novel_title || `Story ${story.novel_id}`}. Server originals, generated files on the server, annotations and pending progress writes are kept.</p>
    {error && <Banner tone="warning">{error}</Banner>}
    <div className="offline-library__cleanup-types">{(Object.keys(names) as OfflineCleanupKind[]).map(kind => <label key={kind}><input type="checkbox" checked={kinds.includes(kind)} disabled={busy || !available[kind]} onChange={event => { epoch.current += 1; setKinds(values => event.target.checked ? [...values, kind] : values.filter(value => value !== kind)); setPreview(null); setError(""); }} />{names[kind]}</label>)}</div>
    <p className="text-muted">Images are embedded in saved text and are removed with it. Removing browser audio also removes its unfinished local parts; it does not cancel server jobs.</p>
    {busy && <p role="status">{preview ? "Removing reviewed files…" : "Reviewing local files…"}</p>}
    {preview && <><p><strong>{preview.records} local records · {offlineBytes(preview.bytes)}</strong></p><p>Only the files in this review can be removed. New or replaced files require a new review.</p>
      {preview.busy_chapters.length > 0 && <Banner tone="warning">Live browser audio work is protected. Cleanup is paused for {preview.busy_chapters.map(row => `chapter ${row.chapter_number}`).join(", ")}. Wait for this work to finish or choose files it is not using.</Banner>}
      {preview.records === 0 && <p>No matching local files are available for removal.</p>}
    </>}
  </Dialog>;
}
