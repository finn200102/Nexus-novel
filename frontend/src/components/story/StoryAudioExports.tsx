import "./StoryAudioExports.css";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Banner, Button, Checkbox, Dialog, Input } from "../ui";
import { audioService, type StoryAudioOverview } from "../../services/audioService";
import { audioExportService, type AudioExportJob, type StoryPodcast, type PodcastEpisode } from "../../services/audioExportService";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";

type Props = { novelId: number; libraryId: number; selectedChapterNumbers?: number[] };
type Selection = { id: number; chapter: number; title: string; narrator: string };
const podcastStatus = (value: StoryPodcast): StoryPodcast => ({ ...value, feed_url: null,
  format: value.format === "mp3" ? "mp3" : undefined,
  ready: Number.isFinite(value.ready) ? Math.max(0, value.ready) : 0,
  pending: Number.isFinite(value.pending) ? Math.max(0, value.pending) : 0,
  failed: Number.isFinite(value.failed) ? Math.max(0, value.failed) : 0,
  episodes: Array.isArray(value.episodes) ? value.episodes : [],
  episodes_total: value.episodes_total ?? value.episodes?.length ?? 0,
  episodes_offset: value.episodes_offset ?? 0,
  episodes_limit: value.episodes_limit ?? 50,
});
const episodeBucket = (status: string): "ready" | "pending" | "failed" => status === "completed" ? "ready" : ["failed", "cancelled"].includes(status) ? "failed" : "pending";
const episodeLabels: Record<string, string> = { queued: "Queued", processing: "Preparing MP3", retry_wait: "Waiting to retry", completed: "Ready", failed: "Needs attention", cancelled: "Cancelled" };
const episodeLabel = (status: string) => episodeLabels[status] || "Preparing MP3";
const activeExport = (job: AudioExportJob) => ["queued", "processing", "retry_wait"].includes(job.status);
const byteLabel = (bytes: number | null) => bytes == null ? "" : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

function Contents({ novelId, libraryId, selectedChapterNumbers }: Props) {
  const generation = storageGeneration();
  const mounted = useRef(false);
  const responseEpoch = useRef(0);
  const [chapters, setChapters] = useState<StoryAudioOverview | null>(null);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Selection[]>([]);
  const [jobs, setJobs] = useState<AudioExportJob[]>([]);
  const [episodePage, setEpisodePage] = useState(0);
  const [feed, setFeed] = useState<StoryPodcast | null>(null);
  const [feedUrl, setFeedUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState<{ type: "rotate" | "revoke" | "remove"; job?: AudioExportJob } | null>(null);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true, pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      const epoch = responseEpoch.current;
      const results = await Promise.allSettled([audioService.story(novelId, page * 50, 50), audioExportService.list(novelId), audioExportService.podcast(novelId, episodePage * 50, 50)]);
      if (active && generation === storageGeneration() && epoch === responseEpoch.current) {
        const messages: string[] = [];
        if (results[0].status === "fulfilled") setChapters(results[0].value); else messages.push("Chapter audio could not be loaded.");
        if (results[1].status === "fulfilled") setJobs(results[1].value); else messages.push("Exports could not be refreshed.");
        if (results[2].status === "fulfilled") {
          setFeed(podcastStatus(results[2].value));
          if (!results[2].value.active) setFeedUrl(null);
        } else messages.push("Podcast status could not be refreshed.");
        setLoadError(messages.join(" "));
      }
      pending = false;
    };
    void load(); const timer = window.setInterval(() => void load(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [novelId, page, episodePage, generation, refresh]);

  const add = (items: Selection[]) => {
    const merged = new Map(selected.map(item => [item.chapter, item]));
    for (const item of items) merged.set(item.chapter, item);
    if (merged.size > 200) { setError("Select at most 200 completed chapter recordings for one audiobook."); return; }
    setSelected([...merged.values()].sort((a, b) => a.chapter - b.chapter)); setError("");
  };
  const readySelections = (data: StoryAudioOverview): Selection[] => data.chapters.flatMap(chapter => chapter.latest_job?.status === "completed" && chapter.latest_job.audio_ready ? [{ id: chapter.latest_job.id, chapter: chapter.chapter_number, title: chapter.title || `Chapter ${chapter.chapter_number}`, narrator: chapter.latest_job.provider_voice }] : []);
  const importSelection = async () => {
    if (!selectedChapterNumbers?.length || selectedChapterNumbers.length > 200 || busy) return;
    setBusy(true); responseEpoch.current++; setError("");
    try {
      const wanted = new Set(selectedChapterNumbers), matches: Selection[] = [];
      let offset = 0, total = Infinity;
      while (offset < total && wanted.size) {
        const data = await audioService.story(novelId, offset, 200);
        if (!current()) return;
        total = data.total;
        matches.push(...readySelections(data).filter(row => wanted.has(row.chapter)));
        for (const chapter of data.chapters) wanted.delete(chapter.chapter_number);
        if (!data.chapters.length || !wanted.size || data.chapters[data.chapters.length - 1].chapter_number >= Math.max(...wanted)) break;
        offset += data.chapters.length;
      }
      if (current()) { add(matches); setNotice(`${matches.length} completed recordings added from your chapter selection. Chapters without completed server audio were skipped.`); }
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t load the selected chapter recordings.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const create = async () => {
    if (!selected.length || busy) return;
    setBusy(true); responseEpoch.current++; setError(""); setNotice("");
    try {
      const job = await audioExportService.create(novelId, selected.map(item => item.id));
      if (current()) { setJobs(rows => [job, ...rows.filter(row => row.id !== job.id)]); setSelected([]); setNotice("Audiobook export queued. It uses the selected completed recordings and generates no new narration."); setRefresh(value => value + 1); }
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t queue this audiobook. Your selected recordings are preserved.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const update = async (job: AudioExportJob, cancel: boolean) => {
    if (busy) return;
    setBusy(true); responseEpoch.current++; setError("");
    try {
      const changed = cancel ? await audioExportService.cancel(job.id) : await audioExportService.retry(job.id);
      if (current()) setJobs(rows => rows.map(row => row.id === changed.id ? changed : row));
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t update this export. Try again.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const download = async (job: AudioExportJob) => {
    if (busy) return;
    setBusy(true); responseEpoch.current++; setError("");
    try {
      const { url } = await audioExportService.download(job.id);
      if (!current()) return;
      const target = new URL(url, window.location.origin);
      if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) throw new Error("Invalid audiobook download URL");
      const link = document.createElement("a");
      link.href = target.href; link.download = `nexus-story-${novelId}-audiobook-${job.id}.m4b`;
      document.body.appendChild(link); link.click(); link.remove();
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t download this audiobook. Connect to Nexus and retry.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const createFeed = async () => {
    if (busy) return;
    setBusy(true); responseEpoch.current++; setError("");
    try {
      setFeedUrl(null);
      const result = await audioExportService.createPodcast(novelId);
      if (current()) { setEpisodePage(0); setFeed(podcastStatus(result)); setFeedUrl(result.feed_url); setConfirm(null); setNotice("Copy this private podcast URL now. Closing this panel or leaving the page hides it."); }
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t create the private podcast feed.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const confirmAction = async () => {
    if (!confirm || busy) return;
    if (confirm.type === "rotate") { await createFeed(); return; }
    setBusy(true); responseEpoch.current++; setError("");
    try {
      if (confirm.type === "remove" && confirm.job) {
        await audioExportService.remove(confirm.job.id);
        if (current()) setJobs(rows => rows.filter(row => row.id !== confirm.job!.id));
      } else {
        await audioExportService.revokePodcast(novelId);
        if (current()) { setFeed(previous => previous ? { ...previous, active: false, feed_url: null, ready: 0, pending: 0, failed: 0, episodes: [], episodes_total: 0, episodes_offset: 0, episodes_limit: 50 } : null); setEpisodePage(0); setFeedUrl(null); setNotice("The podcast URL has been revoked. Files already downloaded to a device remain on that device."); }
      }
      if (current()) setConfirm(null);
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t complete this action. Try again.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const retryEpisode = async (episode: PodcastEpisode) => {
    if (busy || !feed?.active || episode.id === null) return;
    setBusy(true); responseEpoch.current++; setError("");
    try {
      const changed = await audioExportService.retryPodcastEpisode(novelId, episode.id);
      if (current()) {
        setFeed(previous => {
          if (!previous?.active) return previous;
          const before = previous.episodes.find(row => row.id === changed.id);
          const counts = { ready: previous.ready, pending: previous.pending, failed: previous.failed };
          if (before && episodeBucket(before.status) !== episodeBucket(changed.status)) {
            counts[episodeBucket(before.status)] = Math.max(0, counts[episodeBucket(before.status)] - 1);
            counts[episodeBucket(changed.status)]++;
          }
          return { ...previous, ...counts, feed_url: null, episodes: previous.episodes.map(row => row.id === changed.id ? changed : row) };
        });
        setNotice(`Chapter ${episode.chapter_number} queued for MP3 preparation. The original narration is preserved.`);
      }
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t retry this podcast episode. The original narration is preserved.")); }
    finally { responseEpoch.current++; if (current()) setBusy(false); }
  };
  const copyFeed = async () => {
    if (!feedUrl) return;
    try { await navigator.clipboard.writeText(feedUrl); if (current()) setNotice("Private podcast URL copied."); }
    catch { if (current()) setNotice("Select and copy the private URL from the field below."); }
  };

  return <section className="story-audio-exports" aria-label="Exports and podcast">
    <h3>Exports &amp; podcast</h3>
    {error && <Banner tone="warning">{error}</Banner>}
    {loadError && <Banner tone="warning">{loadError}</Banner>}
    {notice && <p role="status">{notice}</p>}
    <section aria-label="M4B audiobooks">
      <h4>M4B audiobook</h4>
      <p>Combine completed server recordings into one audiobook with chapter markers. No new narration is generated. This device’s browser recordings stay in the reader.</p>
      {selectedChapterNumbers && selectedChapterNumbers.length > 0 && <Button disabled={busy || selectedChapterNumbers.length > 200} onClick={() => void importSelection()}>Use selected chapters for audiobook</Button>}
      {!chapters && <p role="status">Loading completed chapter recordings…</p>}
      {chapters && <>
        <div className="story-audio-exports__actions"><Button disabled={busy || !readySelections(chapters).length} onClick={() => add(readySelections(chapters))}>Select ready recordings on this page</Button><Button disabled={busy || !selected.length} onClick={() => setSelected([])}>Clear audiobook selection</Button></div>
        <ul className="story-audio-exports__chapters">{chapters.chapters.map(chapter => {
          const job = chapter.latest_job, ready = Boolean(job?.status === "completed" && job.audio_ready);
          return <li key={chapter.id}><Checkbox disabled={busy || !ready} checked={Boolean(job && selected.some(row => row.id === job.id))} label={`Export chapter ${chapter.chapter_number}: ${chapter.title || "Untitled chapter"}`} onChange={event => {
            if (!job || !ready) return;
            if (event.target.checked) add([{ id: job.id, chapter: chapter.chapter_number, title: chapter.title || `Chapter ${chapter.chapter_number}`, narrator: job.provider_voice }]);
            else setSelected(rows => rows.filter(row => row.id !== job.id));
          }} /><p>{ready ? `Ready · ${job!.provider_voice}` : "Completed server audio required"}</p></li>;
        })}</ul>
        <nav className="story-audio-exports__actions" aria-label="Audiobook chapter pages"><Button disabled={busy || page === 0} onClick={() => setPage(value => value - 1)}>Previous recordings</Button><span>{chapters.total ? chapters.offset + 1 : 0}–{Math.min(chapters.offset + chapters.chapters.length, chapters.total)} of {chapters.total}</span><Button disabled={busy || (page + 1) * 50 >= chapters.total} onClick={() => setPage(value => value + 1)}>Next recordings</Button></nav>
      </>}
      <p aria-live="polite">{selected.length} recordings selected for audiobook{selected.length ? `: ${selected.map(row => `${row.chapter} (${row.narrator})`).join(", ")}` : "."}</p>
      <Button variant="primary" disabled={busy || !selected.length} onClick={() => void create()}>Create M4B audiobook</Button>
      <ul className="story-audio-exports__jobs">{jobs.map(job => <li key={job.id}><h5>Audiobook export {job.id}</h5><p>{{ queued: "Queued", processing: "Preparing audiobook", retry_wait: "Waiting to retry", completed: "Ready", failed: "Needs attention", cancelled: "Cancelled" }[job.status]} · {job.completed_chapters} of {job.total_chapters} chapters{job.audio_bytes ? ` · ${byteLabel(job.audio_bytes)}` : ""}</p>{job.error && <p>{job.error}</p>}{job.chapters.length > 0 && <details><summary>Included chapters</summary><ol>{job.chapters.map(chapter => <li key={chapter.audio_job_id}>Chapter {chapter.chapter_number}: {chapter.title || "Untitled chapter"}</li>)}</ol></details>}{activeExport(job) && <progress aria-label={`Audiobook export ${job.id} progress`} value={job.completed_chapters} max={Math.max(1, job.total_chapters)} />}<div className="story-audio-exports__actions">
        {job.file_ready && <Button disabled={busy} onClick={() => void download(job)}>Download audiobook {job.id}</Button>}
        {activeExport(job) && <Button disabled={busy} onClick={() => void update(job, true)}>Cancel export {job.id}</Button>}
        {["failed", "cancelled"].includes(job.status) && <Button disabled={busy} onClick={() => void update(job, false)}>Retry export {job.id}</Button>}
        {!activeExport(job) && <Button variant="danger" disabled={busy} onClick={() => setConfirm({ type: "remove", job })}>Delete export {job.id}</Button>}
      </div></li>)}</ul>
      <Link to={`/library/${libraryId}/novels/${novelId}`}>Back to story</Link>
    </section>
    <section aria-label="Private story podcast"><h4>Private podcast</h4><p>Subscribe in a podcast app to the latest completed server audio for this story. {feed?.format === "mp3" ? "Nexus prepares MP3 copies in the background from your completed recordings. Only ready MP3 episodes appear in the feed; your original audio is kept and no new narration is generated." : "The feed uses your completed chapter recordings."} Check playback in your chosen podcast app. Anyone with the URL can access it, so keep it private. Rotating or revoking the URL stops future access; files already downloaded to a device cannot be revoked.</p>
      {feed && <p role="status">{feed.active ? "Private podcast is active." : "Private podcast is disabled."}</p>}
      {feed?.active && feed.format !== "mp3" && <p role="status">Episode preparation status is unavailable from this Nexus server. Upgrade the server to see MP3 preparation and retries.</p>}
      {feed?.active && feed.format === "mp3" && <section aria-label="Podcast episode preparation">
        <p role="status">MP3 episodes: {feed.ready} ready · {feed.pending} queued or preparing · {feed.failed} need attention</p>
        {feed.ready + feed.pending + feed.failed > 0 ? <progress aria-label="Podcast MP3 preparation" value={feed.ready} max={feed.ready + feed.pending + feed.failed} /> : <p>Completed server recordings will appear here as MP3 episodes.</p>}
        <ul className="story-audio-exports__episodes">{feed.episodes.map(episode => <li key={episode.source_audio_job_id}>
          <p>Chapter {episode.chapter_number}: {episodeLabel(episode.status)}{episode.audio_bytes && episode.status === "completed" ? ` · ${byteLabel(episode.audio_bytes)}` : ""}</p>
          {episode.error && <p>{episode.error}</p>}
          {episode.id !== null && ["failed", "cancelled", "retry_wait"].includes(episode.status) && <Button disabled={busy} onClick={() => void retryEpisode(episode)}>Retry podcast chapter {episode.chapter_number}</Button>}
        </li>)}</ul>
        {(feed.episodes_total ?? 0) > 0 && <nav className="story-audio-exports__actions" aria-label="Podcast episode pages">
          <Button disabled={busy || episodePage === 0 || feed.episodes_offset !== episodePage * 50} onClick={() => setEpisodePage(value => value - 1)}>Previous podcast episodes</Button>
          <span>{(feed.episodes_offset ?? 0) + 1}–{Math.min((feed.episodes_offset ?? 0) + feed.episodes.length, feed.episodes_total ?? 0)} of {feed.episodes_total} episodes</span>
          <Button disabled={busy || feed.episodes_offset !== episodePage * 50 || (episodePage + 1) * 50 >= (feed.episodes_total ?? 0)} onClick={() => setEpisodePage(value => value + 1)}>Next podcast episodes</Button>
        </nav>}
        <p>The preparation counts include all chapters.</p>
      </section>}
      {!feed?.active && <Button disabled={busy || !feed} onClick={() => void createFeed()}>Create private podcast</Button>}
      {feed?.active && <div className="story-audio-exports__actions"><Button disabled={busy} onClick={() => setConfirm({ type: "rotate" })}>Rotate podcast URL</Button><Button variant="danger" disabled={busy} onClick={() => setConfirm({ type: "revoke" })}>Revoke podcast URL</Button></div>}
      {feedUrl && <><Input label="Private podcast URL" readOnly value={feedUrl} onFocus={event => event.target.select()} /><Button onClick={() => void copyFeed()}>Copy podcast URL</Button><p>Save this URL before closing the panel. Nexus stores only its secret hash and cannot show it again.</p></>}
    </section>
    <Dialog open={confirm !== null} onClose={() => { if (!busy) setConfirm(null); }} title={confirm?.type === "remove" ? `Delete audiobook export ${confirm.job?.id}?` : confirm?.type === "rotate" ? "Rotate the private podcast URL?" : "Revoke the private podcast URL?"} description={confirm?.type === "remove" ? "The exported M4B file is removed. Chapter recordings and text are kept." : "The current URL will stop working in every subscribed podcast app. Files already downloaded remain on those devices."} actions={<><Button disabled={busy} onClick={() => setConfirm(null)}>Keep current</Button><Button variant="danger" loading={busy} onClick={() => void confirmAction()}>{confirm?.type === "remove" ? "Delete audiobook" : confirm?.type === "rotate" ? "Rotate URL" : "Revoke URL"}</Button></>} />
  </section>;
}

export default function StoryAudioExports(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props} />;
}
