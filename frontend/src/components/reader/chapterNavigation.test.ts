import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { accountStorage, activateAccountStorage, storageGeneration } from "../../services/accountStorage";
import { cacheChapterIndex, cachedChapterIndex, cacheChapterNavigation, cachedChapterNavigation, chapterNeighbors, chooseChapterNavigation, ChapterIndexLimitError, loadChapterIndex, validNavigation } from "./chapterNavigation";
const entries = [-2, 0, 3, 20007].map((chapter_number, i) => ({ ...identity(42,chapter_number),id: i + 1, chapter_number, title: `Part ${chapter_number}` }));
const last = {...identity(42,3), novel_id: 42, chapter_id: 3, chapter_number: 3, previous: entries[1], next: null };
describe("actual chapter navigation", () => {
  beforeEach(() => { localStorage.clear(); activateAccountStorage(101); });
  it("finds signed, zero and gapped neighbors without inventing chapter numbers", () => {
    expect(chapterNeighbors([...entries].reverse(), 0)).toEqual({ previous: entries[0], next: entries[2], ordinal: 2 });
    expect(chapterNeighbors(entries, -2).previous).toBeNull();
    expect(chapterNeighbors(entries, 20007).next).toBeNull();
    expect(chapterNeighbors(entries, 2).ordinal).toBeNull();
  });
  it("prefers a live complete index over a cached endpoint that formerly ended the story", () => {
    const indexed = chapterNeighbors(entries, 3);
    expect(chooseChapterNavigation(indexed, "live", last, "cached")).toMatchObject({ next: entries[3], source: "live" });
    expect(chooseChapterNavigation(indexed, "cached", last, "live")).toMatchObject({ next: null, source: "live" });
    expect(chooseChapterNavigation(indexed, "partial", last, "cached")).toMatchObject({ next: null, source: "cached" });
    expect(chooseChapterNavigation(indexed, "partial", null, "none").source).toBe("none");
    expect(chooseChapterNavigation(chapterNeighbors([], 3), "live", null, "none").source).toBe("none");
  });
  it("loads every metadata page in order, including the final short page", async () => {
    const rows = Array.from({ length: 1003 }, (_, i) => ({ id: i + 1, chapter_number: i - 3, title: null, content: "not cached" }));
    const fetch = vi.fn(async (skip: number, limit: number) => rows.slice(skip, skip + limit));
    const result = await loadChapterIndex(fetch, () => true);
    expect(fetch.mock.calls).toEqual([[0, 1000], [1000, 1000]]);
    expect(result).toHaveLength(1003);
    expect(result[0]).toEqual({ id: 1, chapter_number: -3, title: "" });
  });
  it("bounds the drawer but reports a partial index rather than treating it as the end", async () => {
    const fetch = vi.fn(async (skip: number, limit: number) => Array.from({ length: limit }, (_, i) => ({ id: skip + i + 1, chapter_number: skip + i, title: "" })));
    try { await loadChapterIndex(fetch, () => true); throw new Error("Expected index limit"); }
    catch (error) { expect(error).toBeInstanceOf(ChapterIndexLimitError); expect((error as ChapterIndexLimitError).entries).toHaveLength(20_000); }
    expect(fetch.mock.calls[fetch.mock.calls.length - 1]).toEqual([20_000, 1]);
  });
  it("rejects repeated pages and late results after an account or route change", async () => {
    const page = Array.from({ length: 1000 }, (_, i) => ({ id: i + 1, chapter_number: i, title: "" }));
    await expect(loadChapterIndex(async () => page, () => true)).rejects.toThrow("changed during loading");
    let active = true;
    await expect(loadChapterIndex(async () => { active = false; return entries; }, () => active)).rejects.toMatchObject({ name: "AbortError" });
  });
  it("validates directional identity and isolates bounded metadata caches by account", () => {
    expect(validNavigation(last, 42, 3)).toBe(true);
    expect(validNavigation({ ...last, next: entries[0] }, 42, 3)).toBe(false);
    expect(validNavigation(last, 43, 3)).toBe(false);
    const generation = storageGeneration();
    cacheChapterIndex(42, entries, generation);
    cacheChapterNavigation(last, generation);
    activateAccountStorage(102);
    expect(cachedChapterIndex(42)).toBeNull(); expect(cachedChapterNavigation(42, 3)).toBeNull();
    cacheChapterNavigation(last, generation);
    expect(cachedChapterNavigation(42, 3)).toBeNull();
    activateAccountStorage(101);
    expect(cachedChapterIndex(42)).toEqual(entries); expect(cachedChapterNavigation(42, 3)).toEqual(last);
  });
  it("stores only bounded neighbor metadata, never unexpected response bodies", () => {
    const generation = storageGeneration();
    for (let chapter = 0; chapter < 105; chapter++) cacheChapterNavigation({ ...last,...identity(42,chapter), chapter_id: chapter + 1, chapter_number: chapter, previous: null, next: null }, generation);
    expect(cachedChapterNavigation(42, 0)).toBeNull();
    expect(cachedChapterNavigation(42, 104)).not.toBeNull();
    cacheChapterNavigation({ ...last, content: "private raw body" } as typeof last, generation);
    expect(accountStorage.getItem("reader-chapter-neighbors:42")).not.toContain("private raw body");
    expect(JSON.parse(accountStorage.getItem("reader-chapter-neighbors:42")!)).toHaveLength(100);
  });

});
