import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { HardDriveDownload } from "lucide-react";
import { Banner, Button, EmptyState, PageHeader } from "../components/ui";
import { offlineLibraryStore, type OfflineChapterInventory, type OfflineLibraryInventory, type OfflineStoryInventory } from "../services/offlineLibraryStore";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import { usePageTitle } from "../hooks/usePageTitle";
import OfflineStorageStatus from "../components/offline/OfflineStorageStatus";
import OfflineCleanupDialog from "../components/offline/OfflineCleanupDialog";
import { offlineBytes } from "../components/offline/offlineLabels";
import "../components/offline/OfflineLibrary.css";
const sourceLabel = (state: "current" | "stale" | "unknown") => state === "stale" ? " · source changed" : state === "unknown" ? " · source version unverified" : " · matches saved text";
function Chapter({ chapter, story }: { chapter: OfflineChapterInventory; story: OfflineStoryInventory }) {
  const label = chapter.title || `Chapter ${chapter.chapter_number}`;
  return <li className="offline-library__chapter">{chapter.address_current === false && <p>Saved before the chapter list changed. Open the story to review its current chapters.</p>}<h3>{story.library_id != null && chapter.text.ready && !!chapter.chapter_key && chapter.address_current === true ? <Link to={`/library/${story.library_id}/novels/${story.novel_id}/${chapter.chapter_number}?chapter_key=${encodeURIComponent(chapter.chapter_key || "")}`}>{label}</Link> : label}</h3>
    <dl className="offline-library__readiness">
      <div><dt>Text</dt><dd>{chapter.text.ready ? `Saved${chapter.text.pinned ? " · pinned" : ""}` : "Not saved"}</dd></div>
      <div><dt>Images</dt><dd>{chapter.images.total === 0 ? chapter.text.ready ? "None listed" : "Not assessed" : `${chapter.images.ready} of ${chapter.images.total} saved${chapter.images.ready < chapter.images.total ? " · incomplete" : ""}`}{chapter.images.missing > 0 ? ` · ${chapter.images.missing} missing` : ""}</dd></div>
      <div><dt>Audio</dt><dd>{chapter.audio.ready ? `Saved${sourceLabel(chapter.audio.source_state)}` : chapter.audio.partial_bytes > 0 || chapter.audio.completed_parts > 0 ? `Incomplete · ${chapter.audio.completed_parts} parts saved` : "Not saved"}{chapter.audio.job_status && !chapter.audio.ready ? ` · ${chapter.audio.job_status}` : ""}{chapter.audio.busy ? " · live work protected" : ""}</dd></div>
      <div><dt>Translations</dt><dd>{chapter.translations.length ? <ul>{chapter.translations.map(row => <li key={row.id}>{row.language} · {row.ready ? `Saved${sourceLabel(row.source_state)}` : `Incomplete · ${row.status}`}</li>)}</ul> : "Not saved"}</dd></div>
    </dl><p className="text-muted">{offlineBytes(chapter.total_bytes)} on this device</p>
  </li>;
}
function Story({ story, manage }: { story: OfflineStoryInventory; manage: () => void }) {
  const [open, setOpen] = useState(false), [visible, setVisible] = useState(20);
  const readyText = story.chapters.filter(row => row.text.ready).length, readyAudio = story.chapters.filter(row => row.audio.ready).length;
  const translations = story.chapters.reduce((sum, row) => sum + row.translations.filter(value => value.ready).length, 0);
  const title = story.novel_title || `Story ${story.novel_id}`;
  return <section className="offline-library__story" aria-label={`Offline files for ${title}`}><h2>{title}</h2>
    <p>{story.chapters.length} chapters with local files · {offlineBytes(story.total_bytes)}</p><p>Text saved: {readyText} · audio saved: {readyAudio} · translated variants saved: {translations}</p>
    <details onToggle={event => { if (event.target === event.currentTarget) setOpen(event.currentTarget.open); }}><summary>Chapter readiness for {title}</summary>
      {open && <><ol className="offline-library__chapters">{story.chapters.slice(0, visible).map(chapter => <Chapter key={chapter.chapter_key || chapter.chapter_number} chapter={chapter} story={story} />)}</ol>
        {visible < story.chapters.length && <Button onClick={() => setVisible(value => value + 20)}>Show more chapters for {title}</Button>}</>}
    </details><Button onClick={manage}>Manage offline files for {title}</Button>
  </section>;
}
function Contents() {
  const generation = storageGeneration(), mounted = useRef(false), epoch = useRef(0);
  const [inventory, setInventory] = useState<OfflineLibraryInventory | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [cleanup, setCleanup] = useState<OfflineStoryInventory | null>(null);
  const current = () => mounted.current && generation === storageGeneration();
  async function load() {
    const version = ++epoch.current; setBusy(true); setError("");
    try { const result = await offlineLibraryStore.inventory(); if (current() && version === epoch.current) setInventory(result); }
    catch { if (current() && version === epoch.current) setError("This browser could not open your offline library. Your server library and reading progress are kept. Retry the storage check."); }
    finally { if (current() && version === epoch.current) setBusy(false); }
  }
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; epoch.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const chapters = inventory?.stories.flatMap(story => story.chapters) ?? [];
  const textBytes = chapters.reduce((sum, row) => sum + row.text.bytes, 0), imageBytes = chapters.reduce((sum, row) => sum + row.images.embedded_bytes, 0);
  const audioBytes = chapters.reduce((sum, row) => sum + row.audio.bytes + row.audio.partial_bytes, 0), translationBytes = chapters.reduce((sum, row) => sum + row.translations.reduce((count, value) => count + value.bytes, 0), 0);
  return <div className="offline-library">
    <PageHeader title="Offline library" description="Your text, images, audio and translations saved in this browser, private to your account. Opening this page does not download or generate content." />
    {error && <Banner tone="warning">{error}</Banner>}{notice && <p role="status">{notice}</p>}
    <Button disabled={busy} onClick={() => void load()}>Refresh offline library</Button>{busy && <p role="status">Checking local files…</p>}
    {inventory && <section aria-label="Your offline storage usage"><h2>Your offline files</h2><p>{inventory.stories.length} stories · {chapters.length} chapters · {offlineBytes(inventory.total_bytes)} total</p>
      <dl className="offline-library__usage"><div><dt>Text</dt><dd>{offlineBytes(textBytes)} including embedded images</dd></div><div><dt>Images</dt><dd>{offlineBytes(imageBytes)} within text; already included above</dd></div><div><dt>Audio</dt><dd>{offlineBytes(audioBytes)} including unfinished parts</dd></div><div><dt>Translations</dt><dd>{offlineBytes(translationBytes)}</dd></div></dl>
      <p className="text-muted">Readiness reflects files on this device. A saved derivative can be older than your saved text. Without local source text, its source version cannot be verified.</p>
    </section>}
    <OfflineStorageStatus usedBytes={inventory?.total_bytes ?? null} limitBytes={inventory?.limit_bytes ?? null} onBudget={async bytes => { await offlineLibraryStore.setBudget(bytes); if (current()) await load(); }} />
    {inventory?.stories.length === 0 && <EmptyState icon={<HardDriveDownload />} title="Nothing saved on this device yet" description="Open a downloaded chapter, or choose Make available offline on its story page. Audio and translations appear here when they are saved locally." />}
    {inventory?.stories.map(story => <Story key={story.novel_id} story={story} manage={() => setCleanup(story)} />)}
    {cleanup && <OfflineCleanupDialog key={cleanup.novel_id} story={cleanup} onClose={() => setCleanup(null)} onRemoved={async message => { if (!current()) return; setNotice(message); await load(); }} />}
  </div>;
}
export default function Offline() {
  usePageTitle("Offline library");
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={generation} />;
}
