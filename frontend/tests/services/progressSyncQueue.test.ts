import {fixtureChapterIdentity as identity} from "../fixtures/chapterIdentity";
import { accountStorage } from "../../src/services/accountStorage";
import { AxiosError } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dropQueuedProgress,
  enqueueProgress,
  flushProgressQueue,
  getQueuedProgress,
  MAX_HTTP_ATTEMPTS,
  PROGRESS_QUEUE_KEY,
  QueuedProgress,
} from "../../src/services/progressSyncQueue";

const entry = (novelId: number, ts: number, chapter = 1): QueuedProgress => ({ chapterIdentity:identity(novelId,chapter),novelId, chapter, position: 10, percent: 5, ts });

const networkError = () => new AxiosError("Network Error", "ERR_NETWORK");
const httpError = (status: number) => new AxiosError(`HTTP ${status}`, String(status), undefined, null, {
  status, statusText: "", headers: {}, config: {} as never, data: {},
});

describe("progress sync queue", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("keeps only the newest save per novel (last write wins by ts)", () => {
    enqueueProgress(entry(1, 200, 5));
    enqueueProgress(entry(1, 100, 2));
    expect(getQueuedProgress()).toEqual([entry(1, 200, 5)]);
    enqueueProgress(entry(1, 300, 9));
    expect(getQueuedProgress()).toEqual([entry(1, 300, 9)]);
  });

  it("preserves separate unsynchronized positions for old and current reading runs", () => {
    const older = { ...entry(1, 100), readingRunKey: "old-run" };
    const current = { ...entry(1, 200, 2), readingRunKey: "new-run" };
    enqueueProgress(older); enqueueProgress(current);
    expect(getQueuedProgress()).toEqual([older, current]);
    dropQueuedProgress(1, "new-run");
    expect(getQueuedProgress()).toEqual([older]);
  });

  it("keeps a blocked old run while successfully flushing the current run of the same story", async () => {
    const older = { ...entry(1, 100), readingRunKey: "old-run" };
    const current = { ...entry(1, 200), readingRunKey: "new-run" };
    enqueueProgress(older); enqueueProgress(current);
    const rejected = new AxiosError("Different reading run", "409", undefined, null, {
      status: 409, statusText: "", headers: {}, config: {} as never, data: { detail: { code: "reading_run_changed" } },
    });
    expect(await flushProgressQueue(async row => { if (row.readingRunKey === "old-run") throw rejected; })).toBe(1);
    expect(getQueuedProgress()).toEqual([{ ...older, blocked: true, conflictCode: "reading_run_changed" }]);
  });

  it("does not remove newer queued progress when an older direct save is acknowledged", () => {
    const newer = { ...entry(1, 200), readingRunKey: "current-run" };
    enqueueProgress(newer);
    dropQueuedProgress(1, "current-run", 100);
    expect(getQueuedProgress()).toEqual([newer]);
  });

  it("distinguishes replacement operations saved in the same millisecond", async () => {
    const original = { ...entry(1, 200), readingRunKey: "current-run", operationId: "original" };
    const replacement = { ...original, chapter: 3, operationId: "replacement" };
    enqueueProgress(original);
    expect(await flushProgressQueue(async () => { enqueueProgress(replacement); })).toBe(1);
    expect(getQueuedProgress()).toEqual([replacement]);
    dropQueuedProgress(1, "current-run", 200, "original");
    expect(getQueuedProgress()).toEqual([replacement]);
  });

  it("flushes oldest first and empties the queue after success", async () => {
    enqueueProgress(entry(2, 20));
    enqueueProgress(entry(1, 10));
    const sent: number[] = [];
    const send = vi.fn(async (item: QueuedProgress) => {
      sent.push(item.novelId);
    });
    expect(await flushProgressQueue(send)).toBe(2);
    expect(sent).toEqual([1, 2]);
    expect(getQueuedProgress()).toEqual([]);
  });

  it("keeps everything when the network fails mid-flush", async () => {
    enqueueProgress(entry(1, 10));
    enqueueProgress(entry(2, 20));
    const send = vi.fn().mockRejectedValueOnce(networkError());
    expect(await flushProgressQueue(send)).toBe(0);
    expect(send).toHaveBeenCalledTimes(1);
    expect(getQueuedProgress().map((item) => item.novelId)).toEqual([1, 2]);
  });

  it("keeps an entry that the server rejects and still sends the others", async () => {
    enqueueProgress(entry(1, 10));
    enqueueProgress(entry(2, 20));
    const send = vi.fn(async (item: QueuedProgress) => {
      if (item.novelId === 1) throw httpError(500);
    });
    expect(await flushProgressQueue(send)).toBe(1);
    expect(getQueuedProgress()).toEqual([{ ...entry(1, 10), attempts: 1 }]);
  });

  it("does not remove a save that was replaced while it was being sent", async () => {
    enqueueProgress(entry(1, 10, 1));
    const send = vi.fn(async () => {
      enqueueProgress(entry(1, 50, 7));
    });
    await flushProgressQueue(send);
    expect(getQueuedProgress()).toEqual([entry(1, 50, 7)]);
  });

  it("drops the queued save once a direct save reached the server", () => {
    enqueueProgress(entry(1, 10));
    dropQueuedProgress(1);
    expect(getQueuedProgress()).toEqual([]);
  });

  it("ignores corrupt storage instead of crashing", () => {
    accountStorage.setItem(PROGRESS_QUEUE_KEY, "{not json");
    expect(getQueuedProgress()).toEqual([]);
  });
  it("pauses and retains an entry after MAX_HTTP_ATTEMPTS, with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    enqueueProgress(entry(1, 10));
    const send = vi.fn(async () => { throw httpError(400); });
    for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS; attempt += 1) {
      await flushProgressQueue(send);
    }
    expect(getQueuedProgress()).toEqual([{ ...entry(1, 10), attempts: MAX_HTTP_ATTEMPTS, blocked: true }]);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("keeps an entry below the retry cap", async () => {
    enqueueProgress(entry(1, 10));
    const send = vi.fn(async () => { throw httpError(500); });
    for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS - 1; attempt += 1) {
      await flushProgressQueue(send);
    }
    expect(getQueuedProgress()[0].attempts).toBe(MAX_HTTP_ATTEMPTS - 1);
  });

  it("never counts network errors toward the retry cap", async () => {
    enqueueProgress(entry(1, 10));
    const send = vi.fn(async () => { throw networkError(); });
    for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS + 2; attempt += 1) {
      await flushProgressQueue(send);
    }
    expect(getQueuedProgress()).toEqual([entry(1, 10)]);
  });

  it("retains the source revision conflict and quote for review instead of retrying", async () => {
    const anchored = { ...entry(1, 10), textOffset: 4096, textQuote: "Saved passage", contentVersion: "a".repeat(64) };
    enqueueProgress(anchored);
    const error = httpError(409);
    error.response!.data = { detail: { code: "content_changed", current: { revision: 2 } } };
    const send = vi.fn().mockRejectedValue(error);
    expect(await flushProgressQueue(send)).toBe(0);
    expect(getQueuedProgress()).toEqual([{ ...anchored, blocked: true, conflictCode: "content_changed" }]);
    await flushProgressQueue(send);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
