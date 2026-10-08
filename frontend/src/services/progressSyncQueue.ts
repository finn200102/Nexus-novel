import { isNetworkError } from "./networkErrors";

/** Reading progress that could not reach the server, kept until it can. */
export interface QueuedProgress {
  novelId: number;
  chapter: number;
  position: number;
  percent: number;
  /** Client time of the save; the newest save for a novel wins. */
  ts: number;
}

export const PROGRESS_QUEUE_KEY = "nexus-reader-progress-queue";

const isEntry = (value: unknown): value is QueuedProgress => {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return typeof entry.novelId === "number" && typeof entry.chapter === "number"
    && typeof entry.position === "number" && typeof entry.percent === "number" && typeof entry.ts === "number";
};

const readQueue = (): QueuedProgress[] => {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(PROGRESS_QUEUE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter(isEntry) : [];
  } catch {
    return [];
  }
};

/** Returns false when storage refuses the write, so the caller can keep failing loudly. */
const writeQueue = (entries: QueuedProgress[]): boolean => {
  try {
    localStorage.setItem(PROGRESS_QUEUE_KEY, JSON.stringify(entries));
    return true;
  } catch {
    return false;
  }
};

export const getQueuedProgress = (): QueuedProgress[] => readQueue();

/**
 * Queue one save. Per novel only the newest save (by ts) is kept, so an older
 * save can never overwrite a newer one when the queue is flushed.
 */
export const enqueueProgress = (entry: QueuedProgress): boolean => {
  const queue = readQueue();
  const existing = queue.find((item) => item.novelId === entry.novelId);
  if (existing && existing.ts > entry.ts) return true;
  return writeQueue([...queue.filter((item) => item.novelId !== entry.novelId), entry]);
};

/** Drop the queued save for a novel after a direct save reached the server. */
export const dropQueuedProgress = (novelId: number): void => {
  const queue = readQueue();
  if (queue.some((item) => item.novelId === novelId)) {
    writeQueue(queue.filter((item) => item.novelId !== novelId));
  }
};

let flushing: Promise<number> | null = null;

/**
 * Send queued saves oldest first. An entry is removed only after its send
 * succeeds and only if no newer save replaced it meanwhile. A network error
 * stops the flush; an HTTP error keeps that entry and moves on, so one bad
 * entry cannot block the others. Nothing is dropped on failure.
 */
export const flushProgressQueue = (send: (entry: QueuedProgress) => Promise<unknown>): Promise<number> => {
  if (flushing) return flushing;
  flushing = (async () => {
    let sent = 0;
    const pending = readQueue().sort((left, right) => left.ts - right.ts);
    for (const entry of pending) {
      try {
        await send(entry);
      } catch (error) {
        if (isNetworkError(error)) break;
        continue;
      }
      const current = readQueue().find((item) => item.novelId === entry.novelId);
      if (current && current.ts === entry.ts) {
        writeQueue(readQueue().filter((item) => item.novelId !== entry.novelId));
      }
      sent += 1;
    }
    return sent;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
};

/** Flush now and again whenever the browser reports it is back online. */
export const installProgressSync = (send: (entry: QueuedProgress) => Promise<unknown>): (() => void) => {
  const flush = () => {
    void flushProgressQueue(send);
  };
  window.addEventListener("online", flush);
  flush();
  return () => window.removeEventListener("online", flush);
};
