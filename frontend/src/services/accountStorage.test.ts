import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import { beforeEach, describe, expect, it } from "vitest";
import "fake-indexeddb/auto";
import { accountIdentity, accountStorage, activateAccountStorage, clearAccountStorage } from "./accountStorage";
import { enqueueProgress, flushProgressQueue, getQueuedProgress } from "./progressSyncQueue";
import { offlineReaderStore } from "./offlineReaderStore";

describe("private account browser storage", () => {
  beforeEach(() => { localStorage.clear(); activateAccountStorage(101); });

  it("isolates a fresh installation even when its numeric account id is reused", async () => {
    const previous = { id: 1, storage_id: "a42a4617-a64b-440e-83bf-e52f340409f0" };
    const replacement = { id: 1, storage_id: "6d62702d-e9e2-4a6d-97ee-9b2812a61d83" };
    activateAccountStorage(accountIdentity(previous));
    await offlineReaderStore.save({ ...identity(1,1),id: 1, novel_id: 1, chapter_number: 1, title: "Private", content: "Previous owner" });
    enqueueProgress({chapterIdentity:identity(1,1), novelId: 1, chapter: 1, position: 10, percent: 20, ts: 1 });
    activateAccountStorage(accountIdentity(replacement));
    expect(await offlineReaderStore.get(1, 1)).toBeNull();
    expect(getQueuedProgress()).toEqual([]);
  });

  it("does not expose another reader's chapter or progress", async () => {
    await offlineReaderStore.save({ ...identity(1,1),id: 1, novel_id: 1, chapter_number: 1, title: "Private", content: "Reader A" });
    enqueueProgress({chapterIdentity:identity(1,1), novelId: 1, chapter: 1, position: 10, percent: 20, ts: 1 });
    activateAccountStorage(102);
    expect(await offlineReaderStore.get(1, 1)).toBeNull();
    expect(getQueuedProgress()).toEqual([]);
    activateAccountStorage(101);
    expect((await offlineReaderStore.get(1, 1))?.content).toBe("Reader A");
    expect(getQueuedProgress()).toHaveLength(1);
  });

  it("abandons a flush when accounts change without touching the other queue", async () => {
    enqueueProgress({chapterIdentity:identity(1,1), novelId: 1, chapter: 1, position: 0, percent: 10, ts: 1 });
    enqueueProgress({chapterIdentity:identity(2,1), novelId: 2, chapter: 1, position: 0, percent: 10, ts: 2 });
    let sends = 0;
    await flushProgressQueue(async () => {
      sends += 1;
      activateAccountStorage(102);
      enqueueProgress({chapterIdentity:identity(1,5), novelId: 1, chapter: 5, position: 0, percent: 50, ts: 3 });
    });
    expect(sends).toBe(1);
    expect(getQueuedProgress()[0].chapter).toBe(5);
  });

  it("clears only the signing-out account and removes ownerless legacy data", async () => {
    accountStorage.setItem("reader-setting", "a");
    activateAccountStorage(102);
    accountStorage.setItem("reader-setting", "b");
    localStorage.setItem("nexus-reader-progress-queue", "legacy");
    activateAccountStorage(101);
    expect(localStorage.getItem("nexus-reader-progress-queue")).toBeNull();
    await clearAccountStorage();
    activateAccountStorage(101);
    expect(accountStorage.getItem("reader-setting")).toBeNull();
    activateAccountStorage(102);
    expect(accountStorage.getItem("reader-setting")).toBe("b");
  });
});
