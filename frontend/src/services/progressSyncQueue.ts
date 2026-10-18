import { chapterIdentity, ChapterManifestChangedError, type ChapterIdentity } from "./chapterIdentity";
import { isNetworkError } from "./networkErrors";
import axios from "axios";
import { accountStorage, onAccountStorageChange, storageGeneration, activeStorageAccount } from "./accountStorage";

/** Reading progress that could not reach the server, kept until it can. */
export interface QueuedProgress {
  /** Identity captured when reading, never resolved again from the chapter number. */
  chapterIdentity?: ChapterIdentity;
  expectedContentVersion?: string;
  novelId: number;
  readingRunKey?: string | null;
  chapter: number;
  position: number;
  percent: number;
  /** Client time of the save; the newest save for a novel wins. */
  ts: number;
  /** Failed sends that returned an HTTP error so far. */
  attempts?: number;
  expectedRevision?: number;
  operationId?: string;
  deviceId?: string;
  blockId?: string;
  contentVersion?: string;
  textOffset?: number;
  textQuote?: string;
  quotePrefix?: string;
  quoteSuffix?: string;
  locatorVariant?: string;
  intent?: "automatic" | "rewind" | "reconcile" | "confirm_read";
  blocked?: boolean;
  conflictCode?: string;
}

/** Pause rejected writes without deleting the user's unsynchronized position. */
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
    const parsed: unknown = JSON.parse(accountStorage.getItem(PROGRESS_QUEUE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    const entries = parsed.filter(isEntry);
    // Old devices know an address but cannot prove which chapter occupied it.
    // Keep their unsynchronized anchor for review; never guess its new identity.
    const migrated = entries.map(entry => chapterIdentity(entry.chapterIdentity) || entry.blocked ? entry
      : { ...entry, blocked: true, conflictCode: "chapter_identity_required" });
    if (migrated.some((entry, index) => entry !== entries[index])) accountStorage.setItem(PROGRESS_QUEUE_KEY, JSON.stringify(migrated));
    return migrated;
  } catch {
    return [];
  }
};

const sameRun = (left: QueuedProgress, right: QueuedProgress) => left.novelId === right.novelId && (left.readingRunKey ?? null) === (right.readingRunKey ?? null);
const sameSave = (left: QueuedProgress, right: QueuedProgress) => sameRun(left, right) && left.ts === right.ts
  && (left.operationId !== undefined || right.operationId !== undefined ? left.operationId === right.operationId
    : (["chapter", "position", "percent", "expectedContentVersion", "blockId", "textOffset", "textQuote", "contentVersion", "locatorVariant"] as const).every(key => left[key] === right[key]));

/** Returns false when storage refuses the write, so the caller can keep failing loudly. */
const writeQueue = (entries: QueuedProgress[]): boolean => {
  try {
    accountStorage.setItem(PROGRESS_QUEUE_KEY, JSON.stringify(entries));
    return true;
  } catch {
    return false;
  }
};

export const getQueuedProgress = (): QueuedProgress[] => readQueue();

/**
 * Keep the newest save per novel and reading run. A new run never replaces
 * unsynchronized evidence belonging to an earlier run.
 */
export const enqueueProgress = (entry: QueuedProgress): boolean => {
  const queue = readQueue();
  const existing = queue.find((item) => sameRun(item, entry));
  if (existing && existing.ts > entry.ts) return true;
  return writeQueue([...queue.filter((item) => !sameRun(item, entry)), entry]);
};

/** Drop the queued save for a novel after a direct save reached the server. */
export const dropQueuedProgress = (novelId: number, readingRunKey?: string | null, throughTimestamp?: number, operationId?: string): void => {
  const queue = readQueue();
  const matches = (item: QueuedProgress) => item.novelId === novelId && (readingRunKey === undefined || (item.readingRunKey ?? null) === readingRunKey)
    && (throughTimestamp === undefined || item.ts < throughTimestamp || (item.ts === throughTimestamp && (operationId === undefined || item.operationId === operationId)));
  if (queue.some(matches)) {
    writeQueue(queue.filter(item => !matches(item)));
  }
};

/** Count an HTTP failure and preserve the write for manual reconciliation. */
const recordHttpFailure = (entry: QueuedProgress): void => {
  const queue = readQueue();
  const current = queue.find((item) => sameRun(item, entry));
  if (!current || !sameSave(current, entry)) return;
  const attempts = (current.attempts ?? 0) + 1;
  if (attempts >= MAX_HTTP_ATTEMPTS) {
    console.warn(`Paused queued progress for novel ${entry.novelId}; the saved position is retained`);
    writeQueue(queue.map((item) => sameSave(item, entry) ? { ...item, attempts, blocked: true } : item));
    return;
  }
  writeQueue(queue.map((item) => (sameSave(item, entry) ? { ...item, attempts } : item)));
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
    const ownerGeneration = storageGeneration();
    let sent = 0;
    const pending = readQueue().sort((left, right) => left.ts - right.ts);
    for (const entry of pending) {
      if (ownerGeneration !== storageGeneration()) break;
      if (entry.blocked) continue;
      try {
        await send(entry);
      } catch (error) {
        if (ownerGeneration !== storageGeneration()) break;
        if (isNetworkError(error)) break;
        if (axios.isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)) break;
        if (error instanceof ChapterManifestChangedError || axios.isAxiosError(error) && error.response?.status === 409) {
          const detail = error instanceof ChapterManifestChangedError ? { code: "chapter_manifest_changed" } : error.response?.data?.detail;
          writeQueue(readQueue().map((item) => sameSave(item, entry)
            ? { ...item, blocked: true, conflictCode: detail?.code } : item));
          window.dispatchEvent(new CustomEvent("nexus-progress-conflict", { detail: { novelId: entry.novelId, code: detail?.code, current: detail?.current } }));
          continue;
        }
        recordHttpFailure(entry);
        continue;
      }
      if (ownerGeneration !== storageGeneration()) break;
      const current = readQueue().find((item) => sameRun(item, entry));
      if (current && sameSave(current, entry)) {
        writeQueue(readQueue().filter((item) => !sameRun(item, entry)));
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
    if (activeStorageAccount() === null) return;
    void flushProgressQueue(send);
  };
  window.addEventListener("online", flush);
  window.addEventListener("focus", flush);
  const unsubscribe = onAccountStorageChange(flush);
  flush();
  return () => {
    unsubscribe();
    window.removeEventListener("online", flush);
    window.removeEventListener("focus", flush);
  };
};
