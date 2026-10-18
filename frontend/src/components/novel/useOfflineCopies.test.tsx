import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useOfflineCopies } from "./useOfflineCopies";
import { offlineReaderStore, type OfflineChapterSummary } from "../../services/offlineReaderStore";
import { offlineDownloadService, type OfflineCopyPlan, type OfflineCopyResult } from "../../services/offlineDownloadService";
import { activateAccountStorage, storageGeneration } from "../../services/accountStorage";
vi.mock("../../services/offlineReaderStore", () => ({ offlineReaderStore: { listForNovel: vi.fn(), removeForNovel: vi.fn() } }));
vi.mock("../../services/offlineDownloadService", () => ({ offlineDownloadService: { plan: vi.fn(), copy: vi.fn() } }));
const chapter = (number = 3): OfflineChapterSummary => ({ novel_id: 42, chapter_number: number, title: `Chapter ${number}`, pinned: true, cached_at: 1, size_bytes: 100 });
const plan = (novelId = 42): OfflineCopyPlan => ({ generation: storageGeneration(), libraryId: 1, novelId, title: "Story", options: { audio: true, translations: true }, chapters: [{ ...identity(42,3),id: 3, chapter_number: 3, title: "Chapter", downloaded: true, source_version: "v1", text_bytes_estimate: 300, audio: { job_id: 8, bytes: 10, source_version: "v1" }, translations: [{ job_id: 9, language: "de", bytes_estimate: 100, source_version: "v1" }], translations_limited: false }], estimatedBytes: 410, audioCount: 1, translationCount: 1, unavailable: 0, unknownVersion: 0, translationsLimited: false, storage: { total_bytes: 0, limit_bytes: null, remaining_bytes: null } });
const copied: OfflineCopyResult = { text: 1, audio: 1, translations: 1, failed: 0 };
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: Error) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(1); vi.mocked(offlineReaderStore.listForNovel).mockResolvedValue([chapter()]); vi.mocked(offlineReaderStore.removeForNovel).mockResolvedValue(1); vi.mocked(offlineDownloadService.plan).mockImplementation(async (_lib, id, _wanted, _count, options) => ({ ...plan(id), options })); vi.mocked(offlineDownloadService.copy).mockResolvedValue(copied); });
const mount = () => renderHook(({ libraryId, novelId }) => useOfflineCopies(libraryId, novelId), { initialProps: { libraryId: 1, novelId: 42 } });
describe("offline-copy hook operation lifetimes", () => {
  it("preserves ordinary quick text-only saving while media options require a separate explicit confirmation", async () => {
    const { result } = mount(); await waitFor(() => expect(result.current.stored).toHaveLength(1));
    await act(async () => result.current.saveBatch("next", 10)); expect(offlineDownloadService.plan).toHaveBeenCalledWith(1, 42, "next", 10, { audio: false, translations: false }, expect.any(Function)); expect(offlineDownloadService.copy).toHaveBeenCalledOnce();
    await act(async () => result.current.reviewBatch("all", 0, { audio: true, translations: true })); expect(result.current.review?.audioCount).toBe(1); expect(offlineDownloadService.copy).toHaveBeenCalledOnce();
    await act(async () => result.current.confirmBatch()); expect(offlineDownloadService.copy).toHaveBeenCalledTimes(2); expect(result.current.message).toContain("1 recordings saved"); expect(result.current.message).toContain("1 translations saved");
  });
  it("invalidates a pending plan when its consumer unmounts without beginning a copy", async () => {
    const pending = deferred<OfflineCopyPlan>(); vi.mocked(offlineDownloadService.plan).mockReturnValueOnce(pending.promise); const { result, unmount } = mount(); let work!: Promise<void>;
    act(() => { work = result.current.reviewBatch("all", 0, { audio: true, translations: false }); }); const current = vi.mocked(offlineDownloadService.plan).mock.calls[0][5]; unmount(); expect(current()).toBe(false);
    await act(async () => { pending.resolve(plan()); await work; }); expect(offlineDownloadService.copy).not.toHaveBeenCalled();
  });
  it("cancels an in-flight copy, retains completed work and ignores late progress/results", async () => {
    const pending = deferred<OfflineCopyResult>(); vi.mocked(offlineDownloadService.copy).mockReturnValueOnce(pending.promise); const { result } = mount(); await act(async () => result.current.reviewBatch("all", 0, { audio: true, translations: true })); let work!: Promise<void>;
    act(() => { work = result.current.confirmBatch(); }); const [_, current, progress] = vi.mocked(offlineDownloadService.copy).mock.calls[0]; void _;
    act(() => progress(1, 3)); expect(result.current.progress).toEqual({ done: 1, total: 3 }); act(() => result.current.cancelBatch()); expect(current()).toBe(false); expect(result.current.busy).toBe(false); expect(result.current.message).toContain("Completed copies are retained");
    await act(async () => { progress(3, 3); pending.resolve(copied); await work; }); expect(result.current.progress).toBeNull(); expect(result.current.message).toContain("Offline copying stopped"); expect(offlineReaderStore.removeForNovel).not.toHaveBeenCalled();
  });
  it("cannot let an old canceled plan replace a newer review or release its busy state", async () => {
    const old = deferred<OfflineCopyPlan>(), fresh = deferred<OfflineCopyPlan>(); vi.mocked(offlineDownloadService.plan).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise); const { result } = mount(); let first!: Promise<void>, second!: Promise<void>;
    act(() => { first = result.current.reviewBatch("next", 10, { audio: false, translations: false }); }); act(() => result.current.cancelBatch()); act(() => { second = result.current.reviewBatch("all", 0, { audio: true, translations: true }); });
    await act(async () => { old.resolve(plan()); await first; }); expect(result.current.busy).toBe(true); expect(result.current.review).toBeNull();
    const latest = { ...plan(), title: "Latest review" }; await act(async () => { fresh.resolve(latest); await second; }); expect(result.current.review).toEqual(latest); expect(result.current.busy).toBe(false); expect(offlineDownloadService.copy).not.toHaveBeenCalled();
  });
  it("fences a delayed review when story props change and keeps only the new story's copies", async () => {
    const pending = deferred<OfflineCopyPlan>(); vi.mocked(offlineDownloadService.plan).mockReturnValueOnce(pending.promise); const { result, rerender } = mount(); let work!: Promise<void>;
    act(() => { work = result.current.reviewBatch("all", 0, { audio: true, translations: true }); }); const current = vi.mocked(offlineDownloadService.plan).mock.calls[0][5];
    vi.mocked(offlineReaderStore.listForNovel).mockResolvedValue([{ ...chapter(7), novel_id: 7 }]); rerender({ libraryId: 2, novelId: 7 }); await waitFor(() => expect(result.current.stored[0]?.novel_id).toBe(7));
    await act(async () => { pending.resolve(plan()); await work; }); expect(current()).toBe(false); expect(result.current.review).toBeNull(); expect(result.current.message).toBeNull(); expect(offlineDownloadService.copy).not.toHaveBeenCalled();
  });
  it("ignores late copy completion after switching accounts", async () => {
    const pending = deferred<OfflineCopyResult>(); vi.mocked(offlineDownloadService.copy).mockReturnValueOnce(pending.promise); const { result } = mount(); await act(async () => result.current.reviewBatch("all", 0, { audio: true, translations: true })); let work!: Promise<void>;
    act(() => { work = result.current.confirmBatch(); }); vi.mocked(offlineReaderStore.listForNovel).mockResolvedValue([]); act(() => activateAccountStorage(2)); await act(async () => { pending.resolve(copied); await work; });
    expect(result.current.stored).toEqual([]); expect(result.current.review).toBeNull(); expect(result.current.message).toBeNull(); expect(result.current.busy).toBe(false);
  });
  it("retains useful partial outcomes when some media cannot be saved", async () => {
    vi.mocked(offlineDownloadService.copy).mockResolvedValue({ text: 1, audio: 1, translations: 0, failed: 1 }); const { result } = mount(); await act(async () => result.current.reviewBatch("all", 0, { audio: true, translations: true })); await act(async () => result.current.confirmBatch());
    expect(result.current.message).toContain("Saved 1 chapter offline"); expect(result.current.message).toContain("1 recordings saved"); expect(result.current.message).toContain("1 items could not be saved. Existing copies are preserved"); expect(result.current.busy).toBe(false);
  });
  it("does not show an earlier story's late storage error in a newly loaded story", async () => {
    const old = deferred<OfflineChapterSummary[]>(); vi.mocked(offlineReaderStore.listForNovel).mockReturnValueOnce(old.promise); const { result, rerender } = mount();
    vi.mocked(offlineReaderStore.listForNovel).mockResolvedValue([{ ...chapter(7), novel_id: 7 }]); rerender({ libraryId: 1, novelId: 7 }); await waitFor(() => expect(result.current.stored[0]?.novel_id).toBe(7));
    await act(async () => old.reject(new Error("Old story storage unavailable"))); expect(result.current.message).toBeNull();
  });
  it("keeps saved outcomes truthful when only the post-copy list refresh fails", async () => {
    const { result } = mount(); await waitFor(() => expect(result.current.stored).toHaveLength(1));
    vi.mocked(offlineReaderStore.listForNovel).mockRejectedValueOnce(new Error("Refresh failed"));
    await act(async () => result.current.saveBatch("next", 10));
    expect(result.current.message).toContain("Saved 1 chapter offline."); expect(result.current.message).toContain("Could not refresh the local chapter list.");
    expect(result.current.message).not.toContain("Could not prepare offline copies"); expect(result.current.busy).toBe(false);
  });
  it("recovers existing saved counts when a review supersedes an unfinished initial inventory read", async () => {
    const old = deferred<OfflineChapterSummary[]>(); vi.mocked(offlineReaderStore.listForNovel).mockReturnValueOnce(old.promise); const { result } = mount();
    await act(async () => result.current.reviewBatch("next", 10, { audio: false, translations: false }));
    await act(async () => old.resolve([chapter()]));
    expect(result.current.review).not.toBeNull(); expect(result.current.stored).toEqual([chapter()]); expect(offlineDownloadService.copy).not.toHaveBeenCalled();
  });

});
