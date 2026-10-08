import { isNetworkError } from "./networkErrors";

/** Reading progress that could not reach the server, kept until it can. */
export interface QueuedProgress {
  novelId: number;
  chapter: number;
  position: number;
  percent: number;
  /** Client time of the save; the newest save for a novel wins. */
  ts: number;
  /** Failed sends that returned an HTTP error so far. */
  attempts?: number;
}

/** An entry the server rejects this many times is dropped so it cannot retry forever. */
export const MAX_HTTP_ATTEMPTS = 5;

export const PROGRESS_QUEUE_KEY = "nexus-reader-progress-queue";

const isEntry = (value: unknown): value is QueuedProgress => {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return typeof entry.novelId === "number" && typeof entry.chapter === "number"
    && typeof entry.position === "number" && typeof entry.percent === "number" && typeof entry.ts === "number"
    && (entry.attempts === undefined || typeof entry.attempts === "number");
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

/** Count an HTTP failure for this entry; drop it after MAX_HTTP_ATTEMPTS. Newer saves are left alone. */
const recordHttpFailure = (entry: QueuedProgress): void => {
  const queue = readQueue();
  const current = queue.find((item) => item.novelId === entry.novelId);
  if (!current || current.ts !== entry.ts) return;
  const attempts = (current.attempts ?? 0) + 1;
  if (attempts >= MAX_HTTP_ATTEMPTS) {
    console.warn(`Dropping queued progress for novel ${entry.novelId} after ${attempts} rejected attempts`);
    writeQueue(queue.filter((item) => item.novelId !== entry.novelId));
    return;
  }
  writeQueue(queue.map((item) => (item.novelId === entry.novelId ? { ...item, attempts } : item)));
};

let flushing: Promise<number> | null = null;

/**
 * Send queued saves oldest first. An entry is removed only after its send
 * succeeds and only if no newer save replaced it meanwhile. A network error
 * stops the flush and keeps every entry. An HTTP error moves on so one bad
 * entry cannot block the others; after MAX_HTTP_ATTEMPTS such errors the
 * entry is dropped with a console warning.
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
        recordHttpFailure(entry);
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
