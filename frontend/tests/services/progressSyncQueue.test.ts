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

const entry = (novelId: number, ts: number, chapter = 1): QueuedProgress => ({ novelId, chapter, position: 10, percent: 5, ts });

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
    localStorage.setItem(PROGRESS_QUEUE_KEY, "{not json");
    expect(getQueuedProgress()).toEqual([]);
  });
  it("drops an entry the server keeps rejecting after MAX_HTTP_ATTEMPTS, with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    enqueueProgress(entry(1, 10));
    const send = vi.fn(async () => { throw httpError(400); });
    for (let attempt = 0; attempt < MAX_HTTP_ATTEMPTS; attempt += 1) {
      await flushProgressQueue(send);
    }
    expect(getQueuedProgress()).toEqual([]);
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
});
