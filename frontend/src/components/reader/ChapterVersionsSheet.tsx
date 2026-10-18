import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { Banner, Button, Sheet } from "../ui";
import ChapterBody from "./ChapterBody";
import { restoreTextLocator, type TextLocator } from "./chapterDocument";
import { chapterService, type ChapterVersionsPage, type SavedChapterVersion } from "../../services/chapterService";
import { storageGeneration } from "../../services/accountStorage";

export default function ChapterVersionsSheet({ open, onClose, novelId, chapter, expectedChapterKey, requested }: {
  open: boolean; onClose: () => void; novelId: number; chapter: number; expectedChapterKey?: string;
  requested?: { version: string; locator: TextLocator } | null;
}) {
  const [page, setPage] = useState<ChapterVersionsPage | null>(null);
  const [selected, setSelected] = useState("");
  const [textAttempt, setTextAttempt] = useState(0);
  const [text, setText] = useState<SavedChapterVersion | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [passageMissing, setPassageMissing] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const requestEpoch = useRef(0);
  useEffect(() => {
    const lifecycle = requestEpoch;
    const epoch = ++requestEpoch.current, generation = storageGeneration();
    setPage(null); setText(null); setSelected(requested?.version || ""); setError(""); setMoreLoading(false);
    if (!open) return;
    setLoading(true);
    void chapterService.getChapterVersions(novelId, chapter, undefined, expectedChapterKey).then(value => {
      if (epoch !== requestEpoch.current || generation !== storageGeneration()) return;
      setPage(value);
    }).catch(() => {
      if (epoch === requestEpoch.current && generation === storageGeneration()) setError("Couldn’t load saved versions. Connect to Nexus and try again.");
    }).finally(() => { if (epoch === requestEpoch.current) setLoading(false); });
    return () => { lifecycle.current++; };
  }, [open, novelId, chapter, expectedChapterKey, requested]);
  useEffect(() => {
    let cancelled = false;
    const generation = storageGeneration();
    setText(null); setPassageMissing(false);
    if (!open || !selected) return;
    setError("");
    void chapterService.getChapterVersion(novelId, chapter, selected, expectedChapterKey).then(value => {
      if (!cancelled && generation === storageGeneration()) { setText(value); setError(""); }
    }).catch(error => {
      if (!cancelled && generation === storageGeneration()) setError(axios.isAxiosError(error) && error.response?.status === 404
        ? "This original is unavailable. Earlier text cannot be recovered if it was replaced before Nexus retained versions."
        : "Couldn’t load this original. Connect to Nexus and try again.");
    });
    return () => { cancelled = true; };
  }, [open, selected, novelId, chapter, expectedChapterKey, textAttempt]);
  useEffect(() => {
    const container = body.current;
    if (!container || !text) return;
    container.scrollTop = 0;
    if (requested?.version === selected) setPassageMissing(!restoreTextLocator(container, requested.locator).matched);
  }, [text, selected, requested]);
  const loadMore = async () => {
    if (!page?.next_cursor || moreLoading) return;
    const epoch = requestEpoch.current, generation = storageGeneration();
    setMoreLoading(true);
    try {
      const next = await chapterService.getChapterVersions(novelId, chapter, page.next_cursor, expectedChapterKey);
      if (epoch !== requestEpoch.current || generation !== storageGeneration()) return;
      setPage(current => current ? { ...next, versions: [...current.versions, ...next.versions.filter(value => !current.versions.some(row => row.content_version === value.content_version))] } : next);
    } catch { if (epoch === requestEpoch.current && generation === storageGeneration()) setError("Couldn’t load more versions. Try again."); }
    finally { if (epoch === requestEpoch.current) setMoreLoading(false); }
  };
  return <Sheet open={open} onClose={onClose} title="Chapter versions" closeLabel="Close chapter versions">
    <p>Saved originals belong to your library. Viewing earlier text leaves your reading position and completion unchanged.</p>
    {error && <Banner tone="warning">{error}</Banner>}
    {error && selected && !text && <Button onClick={() => setTextAttempt(value => value + 1)}>Retry original</Button>}
    {loading && <p role="status">Loading versions…</p>}
    <ul className="reader-version-list">{page?.versions.map(value => <li key={value.content_version}>
      <Button aria-pressed={selected === value.content_version} variant={selected === value.content_version ? "primary" : "secondary"} onClick={() => { setSelected(value.content_version); setTextAttempt(value => value + 1); }}>
        {value.current ? "Current original" : "Earlier original"}{value.saved_at ? ` · ${new Date(value.saved_at).toLocaleString()}` : ""}
      </Button><span className="text-muted"> {Math.ceil(value.byte_count / 1024)} KB</span>
    </li>)}</ul>
    {page?.next_cursor && <Button disabled={moreLoading} onClick={() => void loadMore()}>{moreLoading ? "Loading…" : "More saved versions"}</Button>}
    {selected && !text && !error && <p role="status">Loading original…</p>}
    {passageMissing && <Banner tone="warning">The saved quote could not be located in this original. Your note is preserved.</Banner>}
    {text && <><h3>{text.title}</h3><div ref={body} className="reader-version-text" tabIndex={0} role="region" aria-label="Saved original text">
      <ChapterBody content={text.content} document={text.document} authorNotes="shown" />
    </div></>}
  </Sheet>;
}
