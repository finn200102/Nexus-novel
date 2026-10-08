import React, { useCallback, useEffect, useState } from "react";
import { chapterService } from "../../services/chapterService";
import { offlineReaderStore, OfflineChapterSummary } from "../../services/offlineReaderStore";

interface OfflineControlProps {
  libraryId: number;
  novelId: number;
}

interface ServerChapter {
  chapter_number: number;
  content_status: string;
}

const BATCH_SIZES = [10, 25, 50] as const;

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * "Make available offline" for a novel. Chapters are fetched through the same
 * endpoint the reader uses and stored pinned, so eviction never drops them.
 */
const OfflineControl: React.FC<OfflineControlProps> = ({ libraryId, novelId }) => {
  const [stored, setStored] = useState<OfflineChapterSummary[]>([]);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStored(await offlineReaderStore.listForNovel(novelId).catch(() => []));
  }, [novelId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const downloadBatch = async (wanted: "next" | "all", count: number) => {
    setMessage(null);
    setProgress({ done: 0, total: 0 });
    try {
      const chapters = (await chapterService.getChapters(novelId)) as ServerChapter[];
      const available = chapters
        .filter((chapter) => chapter.content_status === "PRESENT")
        .sort((left, right) => left.chapter_number - right.chapter_number);

      let targets = available;
      if (wanted === "next") {
        // The reader's position, or the start of the novel when none is saved.
        const position = (await chapterService.getReadingProgress(novelId).catch(() => null) as { chapter_number?: number | null } | null)?.chapter_number ?? 0;
        targets = available.filter((chapter) => chapter.chapter_number >= position).slice(0, count);
      }
      const notDownloaded = chapters.length - available.length;

      setProgress({ done: 0, total: targets.length });
      let failed = 0;
      for (const [index, target] of targets.entries()) {
        try {
          const content = await chapterService.getChapterContentByNumber(target.chapter_number, libraryId, novelId);
          await offlineReaderStore.save(content, { pinned: true });
        } catch {
          failed += 1;
        }
        setProgress({ done: index + 1, total: targets.length });
      }
      const parts = [`Saved ${targets.length - failed} chapter${targets.length - failed === 1 ? "" : "s"} offline.`];
      if (failed) parts.push(`${failed} could not be fetched.`);
      if (wanted === "all" && notDownloaded) parts.push(`${notDownloaded} not downloaded on the server yet.`);
      setMessage(parts.join(" "));
    } catch {
      setMessage("Could not reach the server. Nothing new was saved.");
    } finally {
      setProgress(null);
      await refresh();
    }
  };

  const removeCopies = async () => {
    const removed = await offlineReaderStore.removeForNovel(novelId);
    setMessage(`Removed ${removed} offline chapter${removed === 1 ? "" : "s"}.`);
    await refresh();
  };

  const totalBytes = stored.reduce((sum, item) => sum + item.size_bytes, 0);
  const busy = progress !== null;

  return (
    <section className="offline-control" aria-label="Offline reading">
      <h3>Offline reading</h3>
      <p className="offline-control__summary">
        {stored.length} chapter{stored.length === 1 ? "" : "s"} saved · {formatBytes(totalBytes)}
      </p>
      <div className="offline-control__actions">
        {BATCH_SIZES.map((count) => (
          <button key={count} type="button" disabled={busy} onClick={() => void downloadBatch("next", count)}>
            Next {count} chapters
          </button>
        ))}
        <button type="button" disabled={busy} onClick={() => void downloadBatch("all", 0)}>
          All downloaded chapters
        </button>
        <button type="button" disabled={busy || stored.length === 0} onClick={() => void removeCopies()}>
          Remove offline copy
        </button>
      </div>
      {progress && (
        <p role="status" className="offline-control__progress">
          Downloading {progress.done} of {progress.total}…
        </p>
      )}
      {!progress && message && <p role="status" className="offline-control__message">{message}</p>}
    </section>
  );
};

export default OfflineControl;
