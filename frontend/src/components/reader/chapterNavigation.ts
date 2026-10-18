import { chapterIdentity, type ChapterIdentity } from "../../services/chapterIdentity";
import type { Chapter, ChapterNavigationResponse } from "../../generated/api";
import { accountStorage, activeStorageAccount, storageGeneration } from "../../services/accountStorage";
export type ReaderChapterEntry = Pick<Chapter, "id" | "chapter_number" | "category"> & Partial<ChapterIdentity> & { title: string;completed_checkpoint?:boolean };
export const READER_CHAPTER_LIMIT = 20_000;
export class ChapterIndexLimitError extends Error {
  constructor(public readonly entries: ReaderChapterEntry[]) { super("The chapter drawer is limited to 20,000 entries. Previous and next still use the full story list."); }
}
const normalize = (rows: unknown): ReaderChapterEntry[] => {
  if (!Array.isArray(rows)) throw new Error("Invalid chapter list");
  return rows.map(row => {
    if (!row || !Number.isSafeInteger(row.id) || row.id <= 0 || !Number.isSafeInteger(row.chapter_number)) throw new Error("Invalid chapter entry");
    return { ...(chapterIdentity(row) ?? {}),...(typeof row.completed_checkpoint==="boolean"?{completed_checkpoint:row.completed_checkpoint}:{}), id: row.id, chapter_number: row.chapter_number, title: typeof row.title === "string" ? row.title : "", ...(typeof row.category === "string" ? { category: row.category } : {}) };
  });
};
export function chapterNeighbors<T extends { chapter_number: number }>(entries: T[], current: number) {
  let previous: T | null = null, next: T | null = null, before = 0, found = false;
  for (const entry of entries) {
    if (entry.chapter_number < current) { before++; if (!previous || entry.chapter_number > previous.chapter_number) previous = entry; }
    else if (entry.chapter_number > current) { if (!next || entry.chapter_number < next.chapter_number) next = entry; }
    else found = true;
  }
  return { previous, next, ordinal: found ? before + 1 : null };
}
export function chooseChapterNavigation(indexed: ReturnType<typeof chapterNeighbors<ReaderChapterEntry>>, indexKind: string, data: ChapterNavigationResponse | null, dataKind: string | undefined) {
  const wireEntry = (entry: ChapterNavigationResponse["next"]): ReaderChapterEntry | null => entry ? { ...entry, title: entry.title ?? "" } : null;
  if (data && dataKind === "live") return { previous: wireEntry(data.previous), next: wireEntry(data.next), source: "live" as const };
  if (indexKind === "live" && indexed.ordinal !== null) return { previous: indexed.previous, next: indexed.next, source: "live" as const };
  if (data && dataKind === "cached") return { previous: wireEntry(data.previous), next: wireEntry(data.next), source: "cached" as const };
  if (indexKind === "cached" && indexed.ordinal !== null) return { previous: indexed.previous, next: indexed.next, source: "cached" as const };
  return { previous: null, next: null, source: "none" as const };
}
export async function loadChapterIndex(fetchPage: (skip: number, limit: number) => Promise<unknown>, current: () => boolean): Promise<ReaderChapterEntry[]> {
  const entries: ReaderChapterEntry[] = [], seen = new Set<number>();
  let manifest:ChapterIdentity|null=null;
  for (let skip = 0; skip <= READER_CHAPTER_LIMIT; skip += 1000) {
    if (!current()) throw new DOMException("Chapter navigation changed", "AbortError");
    const limit = skip === READER_CHAPTER_LIMIT ? 1 : 1000;
    const page = normalize(await fetchPage(skip, limit));
    if (!current()) throw new DOMException("Chapter navigation changed", "AbortError");
    if (skip === READER_CHAPTER_LIMIT && page.length) throw new ChapterIndexLimitError(entries);
    for (const row of page) { const identity=chapterIdentity(row);if(identity){if(manifest && (manifest.manifest_epoch!==identity.manifest_epoch || manifest.manifest_revision!==identity.manifest_revision))throw new Error("The chapter list changed during loading");manifest=identity;} if (seen.has(row.id)) throw new Error("The chapter list changed during loading"); seen.add(row.id); entries.push(row); }
    if (page.length < limit) return entries.sort((a, b) => a.chapter_number - b.chapter_number);
  }
  return entries;
}
const indexKey = (novelId: number) => `reader-chapter-index:${novelId}`;
const navigationKey = (novelId: number) => `reader-chapter-neighbors:${novelId}`;
export function cacheChapterIndex(novelId: number, entries: ReaderChapterEntry[], generation: number) {
  if (generation !== storageGeneration() || activeStorageAccount() === null) return;
  try { accountStorage.setItem(indexKey(novelId), JSON.stringify(normalize(entries))); } catch { /* Optional metadata cache cannot interrupt reading. */ }
}
export function cachedChapterIndex(novelId: number): ReaderChapterEntry[] | null {
  if (activeStorageAccount() === null) return null;
  try { const value = JSON.parse(accountStorage.getItem(indexKey(novelId)) || "null"); return Array.isArray(value) && value.length <= READER_CHAPTER_LIMIT && value.every(row=>{const identity=chapterIdentity(row),first=chapterIdentity(value[0]);return identity && first && identity.manifest_epoch===first.manifest_epoch && identity.manifest_revision===first.manifest_revision;}) ? normalize(value) : null; } catch { return null; }
}
export function validNavigation(value: unknown, novelId: number, chapter: number): value is ChapterNavigationResponse {
  if (!value || typeof value !== "object") return false;
  const row = value as ChapterNavigationResponse;
  if (row.novel_id !== novelId || row.chapter_number !== chapter || !Number.isSafeInteger(row.chapter_id) || row.chapter_id <= 0) return false;
  const header=chapterIdentity(row);
  const matching=(entry:ChapterNavigationResponse["next"])=>{const identity=chapterIdentity(entry);return !header || identity && identity.manifest_epoch===header.manifest_epoch && identity.manifest_revision===header.manifest_revision;};
  const valid = (entry: ChapterNavigationResponse["next"]) => entry === null || entry && matching(entry) && Number.isSafeInteger(entry.id) && entry.id > 0 && Number.isSafeInteger(entry.chapter_number) && (entry.title === null || typeof entry.title === "string");
  return !!valid(row.previous) && !!valid(row.next) && (row.previous === null || row.previous.chapter_number < chapter) && (row.next === null || row.next.chapter_number > chapter);
}
export function cacheChapterNavigation(value: ChapterNavigationResponse, generation: number) {
  if (generation !== storageGeneration() || activeStorageAccount() === null) return;
  try {
    const existing: unknown = JSON.parse(accountStorage.getItem(navigationKey(value.novel_id)) || "[]");
    const rows = Array.isArray(existing) ? existing.filter(row => validNavigation(row, value.novel_id, row?.chapter_number) && row.chapter_number !== value.chapter_number) : [];
    const entry=(row:ChapterNavigationResponse["next"])=>row?{...(chapterIdentity(row) ?? {}),id:row.id,chapter_number:row.chapter_number,title:row.title}:null;
    accountStorage.setItem(navigationKey(value.novel_id), JSON.stringify([...rows.slice(-99), {...(chapterIdentity(value) ?? {}),novel_id:value.novel_id,chapter_id:value.chapter_id,chapter_number:value.chapter_number,previous:entry(value.previous),next:entry(value.next)}]));
  } catch { /* Optional metadata cache cannot interrupt reading. */ }
}
export function cachedChapterNavigation(novelId: number, chapter: number): ChapterNavigationResponse | null {
  if (activeStorageAccount() === null) return null;
  try { const rows: unknown = JSON.parse(accountStorage.getItem(navigationKey(novelId)) || "[]"); return Array.isArray(rows) ? rows.find(row => chapterIdentity(row) && validNavigation(row, novelId, chapter)) ?? null : null; } catch { return null; }
}
