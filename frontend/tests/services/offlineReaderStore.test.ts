import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import { offlineReaderStore } from "../../src/services/offlineReaderStore";

const chapter = (novelId: number, chapterNumber: number, content = "text") => ({
  id: novelId * 1000 + chapterNumber,
  novel_id: novelId,
  chapter_number: chapterNumber,
  title: `Chapter ${chapterNumber}`,
  content,
});

const resetDatabase = () => new Promise<void>((resolve, reject) => {
  const request = indexedDB.deleteDatabase("nexus-reader");
  request.onsuccess = () => resolve();
  request.onerror = () => reject(request.error);
  request.onblocked = () => resolve();
});

describe("offlineReaderStore pinning", () => {
  beforeEach(async () => {
    await resetDatabase();
  });

  it("keeps the pinned flag when a chapter is opened again", async () => {
    await offlineReaderStore.save(chapter(1, 1), { pinned: true });
    await offlineReaderStore.save(chapter(1, 1, "reloaded"));
    const [summary] = await offlineReaderStore.listForNovel(1);
    expect(summary.pinned).toBe(true);
  });

  it("stores plain saves as unpinned", async () => {
    await offlineReaderStore.save(chapter(1, 1));
    const [summary] = await offlineReaderStore.listForNovel(1);
    expect(summary.pinned).toBe(false);
  });

  it("never evicts pinned chapters when over the limit", async () => {
    await offlineReaderStore.save(chapter(1, 1), { pinned: true });
    for (let number = 2; number <= 53; number += 1) {
      await offlineReaderStore.save(chapter(2, number));
    }
    const kept = await offlineReaderStore.listForNovel(1);
    const others = await offlineReaderStore.listForNovel(2);
    expect(kept.map((item) => item.chapter_number)).toEqual([1]);
    expect(others.length).toBe(49);
  });

  it("lets pinned chapters exceed the limit rather than drop them", async () => {
    for (let number = 1; number <= 52; number += 1) {
      await offlineReaderStore.save(chapter(1, number), { pinned: true });
    }
    expect((await offlineReaderStore.listForNovel(1)).length).toBe(52);
  });

  it("lists one novel in chapter order with a size estimate", async () => {
    await offlineReaderStore.save(chapter(3, 2, "abcd"));
    await offlineReaderStore.save(chapter(3, 1, "é"));
    await offlineReaderStore.save(chapter(4, 1, "other novel"));
    const list = await offlineReaderStore.listForNovel(3);
    expect(list.map((item) => item.chapter_number)).toEqual([1, 2]);
    expect(list[0].size_bytes).toBe(new TextEncoder().encode("Chapter 1é").length);
    expect(list[1].size_bytes).toBe(new TextEncoder().encode("Chapter 2abcd").length);
  });

  it("removes every chapter of one novel, pinned included", async () => {
    await offlineReaderStore.save(chapter(5, 1), { pinned: true });
    await offlineReaderStore.save(chapter(5, 2));
    await offlineReaderStore.save(chapter(6, 1));
    expect(await offlineReaderStore.removeForNovel(5)).toBe(2);
    expect(await offlineReaderStore.listForNovel(5)).toEqual([]);
    expect((await offlineReaderStore.listForNovel(6)).length).toBe(1);
  });
});
