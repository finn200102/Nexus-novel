import apiClient from "./apiClient";
import { chapterIdentity, chapterManifestFence, expectedChapterIdentity, assertCurrentChapterIdentity, observeChapterIdentity, ChapterManifestChangedError, type ChapterIdentity } from "./chapterIdentity";
import axios, { AxiosError } from "axios";
import { logRequestFailure } from "./requestDiagnostics";
import { dropQueuedProgress, enqueueProgress, getQueuedProgress, installProgressSync, QueuedProgress } from "./progressSyncQueue";
import { isNetworkError } from "./networkErrors";
import { markServerReachable, markServerUnreachable } from "./serverReachability";
import { accountStorage, storageGeneration } from "./accountStorage";
import type { Chapter as ChapterResponse, ChapterNavigationResponse, ChapterDownloadCancelledResponse, ChapterDownloadJob, ChapterDownloadsCancelledResponse, ChapterRecapResponse, ChapterVersionSummary as WireChapterVersionSummary, ChapterVersionsPage as WireChapterVersionsPage, NovelDownloadStatusResponse, ReadingAnnotationCreate, ReadingAnnotationResponse, ReadingHistoryResponse, ReadingProgressResponse, ReadingProgressUpdate } from "../generated/api";
import { readerChapterContent, type ChapterContentResponse, type ReaderChapterContent } from "./chapterContracts";
export type ChapterVersionSummary = WireChapterVersionSummary;
export type ChapterVersionsPage = WireChapterVersionsPage;
export type SavedChapterVersion = ReaderChapterContent;

export type ChapterReadingSummary = import("../generated/api").ChapterReadingSummaryResponse;
export type ChapterReadingPage = import("../generated/api").ChapterReadingPageResponse;
export type ChapterReadingItem = import("../generated/api").ChapterReadingItemResponse;
export type ChapterReadingQuery = { offset?: number; limit?: number; q?: string; category_scope?: "all" | "followed" };

const revisionKey = (novelId: number) => `progress-revision:${novelId}`;
const revisionFor = (novelId: number) => Number(accountStorage.getItem(revisionKey(novelId)) || 0);
const snapshotKey = (novelId: number) => `progress-snapshot:${novelId}`;
const runEpochs = new Map<number, number>();
export interface CachedReadingProgress {
  chapter_key?: string | null; manifest_epoch?: string | null; manifest_revision?: string | null; furthest_chapter_key?: string | null;
  chapter_number: number | null; position: number; percent: number; revision: number; reading_run_key: string | null;
  block_id?: string | null; text_offset?: number; text_quote?: string | null; quote_prefix?: string | null;
  quote_suffix?: string | null; locator_content_version?: string | null; locator_variant?: string | null;
}
type ProgressSnapshotInput = Partial<CachedReadingProgress> | import("../generated/api").ReadingRunProgressResponse;
const cachedProgress = (novelId: number): CachedReadingProgress | null => {
  try {
    const value = JSON.parse(accountStorage.getItem(snapshotKey(novelId)) || "null");
    return value && typeof value.revision === "number" && typeof value.position === "number" && typeof value.percent === "number"
      && (value.chapter_number === null || typeof value.chapter_number === "number")
      && (value.reading_run_key === null || typeof value.reading_run_key === "string") ? value : null;
  } catch { return null; }
};
const rememberProgress = (novelId: number, value: ProgressSnapshotInput | null) => {
  accountStorage.setItem(revisionKey(novelId), String(value?.revision ?? 0));
  if (!value) { accountStorage.removeItem(snapshotKey(novelId)); return; }
  accountStorage.setItem(snapshotKey(novelId), JSON.stringify({ ...value, revision: value.revision ?? 0,
    reading_run_key: value.reading_run_key ?? null, chapter_number: value.chapter_number ?? null,
    position: value.position ?? 0, percent: value.percent ?? 0, text_offset: value.text_offset ?? undefined }));
};
const runConflict = (current: CachedReadingProgress | ReadingProgressResponse | null) => new AxiosError("A different reading session is active", "ERR_BAD_REQUEST", undefined, undefined, {
  status: 409, statusText: "Conflict", headers: {}, config: {} as never,
  data: { detail: { code: "reading_run_changed", current, message: "This position belongs to an earlier reading session. Keep it separately or use the current session." } },
});
const operationId = () => crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
const saves = new Map<string, Promise<unknown>>();
const deviceId = () => {
  let id = accountStorage.getItem("device-id");
  if (!id) { id = operationId(); accountStorage.setItem("device-id", id); }
  return id;
};

const sendProgress = async (entry: QueuedProgress) => {
  const generation = storageGeneration();
  const epoch = runEpochs.get(entry.novelId) || 0;
  try {
    const cached = cachedProgress(entry.novelId);
    if (entry.readingRunKey && cached?.reading_run_key && entry.readingRunKey !== cached.reading_run_key) throw runConflict(cached);
    if (entry.chapterIdentity) assertCurrentChapterIdentity(entry.novelId, entry.chapterIdentity);
    const response = await apiClient.put<ReadingProgressResponse>(`/chapter/progress/${entry.novelId}`, {
      ...(entry.chapterIdentity ? expectedChapterIdentity(entry.chapterIdentity, entry.expectedContentVersion) : {}),
      reading_run_key: entry.readingRunKey ?? null,
      chapter_number: entry.chapter,
      position: entry.position,
      percent: entry.percent,
      expected_revision: entry.expectedRevision ?? revisionFor(entry.novelId),
      operation_id: entry.operationId,
      device_id: entry.deviceId,
      block_id: entry.blockId,
      content_version: entry.contentVersion,
      text_offset: entry.textOffset ?? 0,
      text_quote: entry.textQuote,
      quote_prefix: entry.quotePrefix,
      quote_suffix: entry.quoteSuffix,
      locator_variant: entry.locatorVariant,
      intent: entry.intent ?? "automatic",
    } satisfies ReadingProgressUpdate);
    if (generation !== storageGeneration()) throw new Error("Reading account changed during save");
    const receiptIdentity=chapterIdentity(response.data);
    try { if(receiptIdentity)assertCurrentChapterIdentity(entry.novelId,receiptIdentity);else if(entry.chapterIdentity)assertCurrentChapterIdentity(entry.novelId,entry.chapterIdentity); }
    catch(error){
      if(!(error instanceof ChapterManifestChangedError))throw error;
      // A replay acknowledges the operation, not its historical numeric address.
      // Do not requeue acknowledged work or adopt its obsolete snapshot.
      const authoritative=await chapterService.getReadingProgress(entry.novelId).catch(()=>null);
      return {...response,data:authoritative};
    }
    const latest = cachedProgress(entry.novelId);
    if (((runEpochs.get(entry.novelId) || 0) !== epoch || (latest?.revision ?? 0) > (response.data.revision ?? 0))
        && latest?.reading_run_key !== (response.data.reading_run_key ?? null)) throw runConflict(latest);
    if ((latest?.revision ?? 0) <= (response.data.revision ?? 0)) rememberProgress(entry.novelId, response.data);
    markServerReachable();
    return response;
  } catch (error) {
    if (isNetworkError(error)) markServerUnreachable();
    throw error;
  }
};

export const chapterService = {
  async getReadingSummary(novelId: number): Promise<ChapterReadingSummary> {
    return (await apiClient.get<ChapterReadingSummary>(`/chapter/reading-summary/${novelId}`)).data;
  },
  async getReadingChapters(novelId: number, params: ChapterReadingQuery = {}): Promise<ChapterReadingPage> {
    return (await apiClient.get<ChapterReadingPage>(`/chapter/reading-chapters/${novelId}`, { params })).data;
  },
  async getNavigation(novelId: number, chapterNumber: number, expected?: ChapterIdentity | string): Promise<ChapterNavigationResponse> {
    const generation=storageGeneration(),fence=chapterManifestFence(novelId);
    const value=(await apiClient.get<ChapterNavigationResponse>(`/chapter/navigation/${novelId}/${chapterNumber}`,expected?{params:typeof expected==="string"?{expected_chapter_key:expected}:expectedChapterIdentity(expected)}:undefined)).data;
    if(generation!==storageGeneration())throw new DOMException("Reading account changed","AbortError");
    const identity=chapterIdentity(value);if(identity)observeChapterIdentity(novelId,identity,generation,fence);
    return value;
  },
  async getChapters(novelId: number, pagination?: { skip: number; limit: number }): Promise<ChapterResponse[]> {
    try {
      const response = await apiClient.get(`/chapter/${novelId}`, pagination ? { params: pagination } : undefined);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapter(
    library_id: number,
    novelId: number,
    chapterNumber: number,
    identity?:ChapterIdentity,
    sourceVersion?:string
  ): Promise<ChapterResponse> {
    try {
      const response = await apiClient.get(
        `/chapter/download/${library_id}/${novelId}/${chapterNumber}`,
        {params:identity ? expectedChapterIdentity(identity,sourceVersion) : undefined}
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async downloadChapters(
    library_id: number,
    novelId: number,
    chapterNumbers: number[]
  ): Promise<ChapterResponse[]> {
    try {
      const downloadPromises = chapterNumbers.map((chapterNumber) =>
        this.downloadChapter(library_id, novelId, chapterNumber)
      );

      return await Promise.all(downloadPromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error downloading chapters");
      }
      throw error;
    }
  },
  async queueChapterDownloads(libraryId: number, novelId: number, count: number): Promise<ChapterDownloadJob[]> {
    const response = await apiClient.post(`/chapter/queue/${libraryId}/${novelId}`, { count });
    return response.data;
  },

  async getChapterContentByNumber(
    chapterNumber: number,
    libraryId: number,
    novelId: number,
    expectedIdentity?: ChapterIdentity | string
  ): Promise<ReaderChapterContent> {
    const generation = storageGeneration(), manifestFence = chapterManifestFence(novelId);
    try {
      const response = await apiClient.get<ChapterContentResponse>(
        `/chapter/content/library/${libraryId}/${novelId}/${chapterNumber}`,
        expectedIdentity ? { params: typeof expectedIdentity === "string" ? { expected_chapter_key:expectedIdentity } : expectedChapterIdentity(expectedIdentity) } : undefined
      );
      if (generation !== storageGeneration()) throw new Error("Reading account changed");
      const identity = chapterIdentity(response.data);
      if (identity) observeChapterIdentity(novelId, identity, generation, manifestFence);
      markServerReachable();
      return readerChapterContent(response.data);
    } catch (error) {
      if (isNetworkError(error)) markServerUnreachable();
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching chapters");
      }
      throw error;
    }
  },
  async getReadingProgress(novelId: number): Promise<ReadingProgressResponse | CachedReadingProgress | null> {
    const generation = storageGeneration();
    const epoch = runEpochs.get(novelId) || 0, before = cachedProgress(novelId), manifestFence=chapterManifestFence(novelId);
    const response = await apiClient.get<ReadingProgressResponse | null>(`/chapter/progress/${novelId}`);
    if (generation !== storageGeneration()) throw new Error("Reading account changed");
    const latest = cachedProgress(novelId);
    if (((runEpochs.get(novelId) || 0) !== epoch || before?.reading_run_key !== latest?.reading_run_key)
        && latest?.reading_run_key !== (response.data?.reading_run_key ?? null)) throw runConflict(latest);
    if (latest && latest.reading_run_key === (response.data?.reading_run_key ?? null)
        && latest.revision > (before?.revision ?? 0) && latest.revision > (response.data?.revision ?? 0)) return latest;
    const identity=chapterIdentity(response.data);if(identity)observeChapterIdentity(novelId,identity,generation,manifestFence);
    rememberProgress(novelId, response.data);
    return response.data;
  },
  getCachedReadingProgress: cachedProgress,
  acceptReadingRun(novelId: number, progress: ProgressSnapshotInput | null) {
    const identity=chapterIdentity(progress);if(identity)assertCurrentChapterIdentity(novelId,identity);
    const latest = cachedProgress(novelId);
    if (progress && latest && (progress.revision ?? 0) < latest.revision) throw runConflict(latest);
    runEpochs.set(novelId, (runEpochs.get(novelId) || 0) + 1);
    rememberProgress(novelId, progress);
  },
  async exportNovelEpub(novelId: number): Promise<Blob> {
    const response = await apiClient.get(`/chapter/novel/${novelId}/export.epub`, { responseType: "blob" });
    return response.data;
  },
  async getChapterVersions(novelId: number, chapter: number, cursor?: number, expectedChapterKey?: string): Promise<ChapterVersionsPage> {
    const generation=storageGeneration(), fence=chapterManifestFence(novelId);
    const result=(await apiClient.get<ChapterVersionsPage>(`/chapter/versions/${novelId}/${chapter}`, { params: { cursor, expected_chapter_key:expectedChapterKey } })).data;
    if(generation!==storageGeneration())throw new Error("Reading account changed");
    const identity=chapterIdentity(result);
    if(expectedChapterKey && identity?.chapter_key!==expectedChapterKey)throw new ChapterManifestChangedError();
    if(identity)observeChapterIdentity(novelId,identity,generation,fence);
    return result;
  },
  async getChapterVersion(novelId: number, chapter: number, version: string, expectedChapterKey?: string): Promise<SavedChapterVersion> {
    const generation=storageGeneration(), fence=chapterManifestFence(novelId);
    const result=(await apiClient.get<ChapterContentResponse>(`/chapter/versions/${novelId}/${chapter}/${version}`,{params:{expected_chapter_key:expectedChapterKey}})).data;
    if(generation!==storageGeneration())throw new Error("Reading account changed");
    const identity=chapterIdentity(result);
    if(expectedChapterKey && identity?.chapter_key!==expectedChapterKey)throw new ChapterManifestChangedError();
    if(identity)observeChapterIdentity(novelId,identity,generation,fence);
    return readerChapterContent(result);
  },
  /**
   * Save progress. When the network is down the save is queued locally and
   * sent later (see progressSyncQueue); the call then resolves to null.
   */
  async updateReadingProgress(
    novelId: number,
    chapterNumber: number,
    position: number,
    percent: number,
    locator?: { chapterIdentity?: ChapterIdentity; expectedContentVersion?: string; readingRunKey?: string | null; blockId?: string; textOffset?: number; textQuote?: string; quotePrefix?: string; quoteSuffix?: string; locatorVariant?: string; contentVersion?: string; intent?: "automatic" | "rewind" | "reconcile" | "confirm_read" }
  ) {
    const generation = storageGeneration();
    const readingRunKey = locator && "readingRunKey" in locator ? locator.readingRunKey : cachedProgress(novelId)?.reading_run_key;
    const key = `${generation}:${novelId}`;
    const run = async () => {
      if (generation !== storageGeneration()) return null;
      const entry: QueuedProgress = { novelId, chapter: chapterNumber, position, percent, ts: Date.now(),
        expectedRevision: revisionFor(novelId), operationId: operationId(), deviceId: deviceId(), ...locator, readingRunKey: readingRunKey ?? null };
      const blocked = getQueuedProgress().find((item) => item.novelId === novelId && item.blocked && (item.readingRunKey ?? null) === (entry.readingRunKey ?? null));
      if (blocked && locator?.intent !== "reconcile") {
        // Preserve the original rejected anchor until the reader chooses a
        // position; later automatic ticks must not replace its evidence.
        return null;
      }
      try {
        const response = await sendProgress(entry);
        dropQueuedProgress(novelId, entry.readingRunKey ?? null, entry.ts, entry.operationId);
        return response.data;
      } catch (error) {
        if (generation !== storageGeneration()) return null;
        if (error instanceof ChapterManifestChangedError || axios.isAxiosError(error) && error.response?.status === 409) {
          const detail = error instanceof ChapterManifestChangedError ? { code: "chapter_manifest_changed" } : error.response?.data?.detail;
          enqueueProgress({ ...entry, blocked: true, conflictCode: detail?.code });
          window.dispatchEvent(new CustomEvent("nexus-progress-conflict", { detail: { novelId, code: detail?.code, current: detail?.current } }));
          return null;
        }
        if (isNetworkError(error) && enqueueProgress(entry)) return null;
        throw error;
      }
    };
    const pending = (saves.get(key) || Promise.resolve()).catch(() => undefined).then(run);
    saves.set(key, pending);
    try { return await pending; }
    finally { if (saves.get(key) === pending) saves.delete(key); }
  },
  async resolveProgressConflict(novelId: number, choice: "server" | "device") {
    const pending = getQueuedProgress().find((item) => item.novelId === novelId && item.blocked) || getQueuedProgress().find(item => item.novelId === novelId);
    const current = await this.getReadingProgress(novelId);
    if (choice === "server" || !pending) {
      if (pending) dropQueuedProgress(novelId, pending.readingRunKey ?? null, pending.ts, pending.operationId);
      return current;
    }
    if (pending.readingRunKey && pending.readingRunKey !== (current?.reading_run_key ?? null)) throw runConflict(current);
    // Reconciliation is an explicit position choice, never permission to move
    // an old queued write onto a different chapter at the same numeric address.
    if (!pending.chapterIdentity) throw new Error("This saved place has no verified chapter identity. Open the original chapter and review the location before accepting it.");
    assertCurrentChapterIdentity(novelId, pending.chapterIdentity);
    return this.updateReadingProgress(novelId, pending.chapter, pending.position, pending.percent,
      { chapterIdentity: pending.chapterIdentity, expectedContentVersion: pending.expectedContentVersion, readingRunKey: pending.readingRunKey, blockId: pending.blockId, textOffset: pending.textOffset, textQuote: pending.textQuote,
        quotePrefix: pending.quotePrefix, quoteSuffix: pending.quoteSuffix, locatorVariant: pending.locatorVariant,
        contentVersion: pending.contentVersion, intent: "reconcile" });
  },
  async getReadingAnnotations(novelId: number): Promise<ReadingAnnotationResponse[]> {
    const response = await apiClient.get(`/chapter/annotations/${novelId}`);
    return response.data;
  },
  async getReadingHistory(novelId: number): Promise<ReadingHistoryResponse> {
    return (await apiClient.get(`/chapter/history/${novelId}`)).data;
  },
  async getSpoilerSafeRecap(novelId: number): Promise<ChapterRecapResponse> {
    return (await apiClient.get(`/chapter/recap/${novelId}`)).data;
  },
  async createReadingAnnotation(novelId: number, annotation: ReadingAnnotationCreate): Promise<ReadingAnnotationResponse> {
    const response = await apiClient.post(`/chapter/annotations/${novelId}`, annotation);
    return response.data;
  },
  async deleteReadingAnnotation(annotationId: number) {
    await apiClient.delete(`/chapter/annotations/${annotationId}`);
  },

  async deleteChapterById(chapterId: number): Promise<ChapterResponse> {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error deleting chapter");
      }
      throw error;
    }
  },
  async deleteChaptersByIds(chapterIds: number[]) {
    try {
      const deletePromises = chapterIds.map((chapterId) =>
        this.deleteChapterById(chapterId)
      );

      return await Promise.all(deletePromises);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error delete chapters");
      }
      throw error;
    }
  },

  async resetChapterStatus(chapterId: number, status: string): Promise<ChapterResponse> {
    try {
      const response = await apiClient.patch(
        `/chapter/${chapterId}/status?content_status=${status}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error resetting chapter status");
      }
      throw error;
    }
  },

  async getDownloadStatus(novelId: number): Promise<NovelDownloadStatusResponse> {
    try {
      const response = await apiClient.get(`/chapter/novel/${novelId}/download-status`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error fetching download status");
      }
      throw error;
    }
  },

  async cancelChapterDownload(chapterId: number): Promise<ChapterDownloadCancelledResponse> {
    try {
      const response = await apiClient.delete(`/chapter/${chapterId}/download`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling chapter download");
      }
      throw error;
    }
  },

  async cancelAllDownloads(novelId: number): Promise<ChapterDownloadsCancelledResponse> {
    try {
      const response = await apiClient.post(`/chapter/novel/${novelId}/cancel-all-downloads`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status !== 401) {
        this.handleError(error, "Error cancelling all downloads");
      }
      throw error;
    }
  },

  handleError(error: unknown, message: string) {
    logRequestFailure(error,message);
  },
};

// Send saves queued while offline, on start and whenever the network returns.
installProgressSync(sendProgress);
