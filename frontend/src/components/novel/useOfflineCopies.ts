import { useCallback, useEffect, useState } from "react";
import { chapterService } from "../../services/chapterService";
import { offlineReaderStore, OfflineChapterSummary } from "../../services/offlineReaderStore";

interface ServerChapter {
  chapter_number: number;
  content_status: string;
}

export const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export interface OfflineCopies {
  stored: OfflineChapterSummary[];
  totalBytes: number;
  progress: { done: number; total: number } | null;
  message: string | null;
  busy: boolean;
  saveBatch: (wanted: "next" | "all", count: number) => Promise<void>;
  removeAll: () => Promise<void>;
}

/**
 * "Make available offline" for a novel. Chapters are fetched through the same endpoint the
 * reader uses and stored pinned, so eviction never drops them.
 */
export function useOfflineCopies(libraryId: number, novelId: number): OfflineCopies {
  const [stored, setStored] = useState<OfflineChapterSummary[]>([]);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStored(await offlineReaderStore.listForNovel(novelId).catch(() => []));
  }, [novelId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveBatch = async (wanted: "next" | "all", count: number) => {
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

  const removeAll = async () => {
    const removed = await offlineReaderStore.removeForNovel(novelId);
    setMessage(`Removed ${removed} offline chapter${removed === 1 ? "" : "s"}.`);
    await refresh();
  };

  return {
    stored,
    totalBytes: stored.reduce((sum, item) => sum + item.size_bytes, 0),
    progress,
    message,
    busy: progress !== null,
    saveBatch,
    removeAll,
  };
}
