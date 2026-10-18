import { chapterIdentity, ChapterManifestChangedError, type ChapterIdentity } from "./chapterIdentity";
import { stableOfflineChapterKey, registerOfflineChapterIdentity, resolveOfflineChapterIdentity } from "./offlineChapterIdentity";
import { accountDatabaseName, storageGeneration } from "./accountStorage";
import {openOfflineDatabase,offlineTransaction,putOfflineRecord,deleteOfflineRecord,transactionFailure,assertStorageGeneration,OfflineAudioBusyError} from './offlineStorageDatabase';
import type {PronunciationRule} from "./pronunciationService";
import type {AudioManifest,AudioPassage} from "./audioAlignment";
import type { ChapterDocument } from "../components/reader/chapterDocument";

export interface OfflineChapter {
  id: number;
  novel_id: number;
  chapter_number: number;
  chapter_key?: string; manifest_epoch?: string; manifest_revision?: string;
  title: string;
  content: string;
  document?: ChapterDocument;
  library_id?: number;
  novel_title?: string;
}

interface StoredChapter extends OfflineChapter {
  cache_key: string;
  cached_at: number;
  /** Saved explicitly by "Make available offline"; never evicted automatically. */
  pinned?: boolean;
}

export interface OfflineChapterSummary {
  chapter_key?: string; manifest_epoch?: string; manifest_revision?: string;
  novel_id: number;
  chapter_number: number;
  title: string;
  pinned: boolean;
  cached_at: number;
  size_bytes: number;
}

const encoder = new TextEncoder();
/** Approximate stored size: UTF-8 bytes of the text payload. */
const chapterSizeBytes = (chapter: Pick<OfflineChapter, "title" | "content"> & { document?: ChapterDocument }) =>
  encoder.encode(chapter.title + chapter.content + (chapter.document ? JSON.stringify(chapter.document) : "")).length;

const STORE_NAME = "chapters";
const AUDIO_STORE_NAME = "chapter_audio";
const AUDIO_JOB_STORE_NAME = "chapter_audio_jobs";
const AUDIO_SEGMENT_STORE_NAME = "chapter_audio_segments";
const MAX_CACHED_CHAPTERS = 50;

const chapterKey = (novelId: number, identity: ChapterIdentity) => stableOfflineChapterKey(novelId, identity);
export async function offlineChapterIdentity(novelId: number, chapterNumber: number, expected?: ChapterIdentity): Promise<ChapterIdentity | null> {
  if (!("indexedDB" in window)) return null;
  let result: ChapterIdentity | null = null;
  await runStoreTransaction("readonly", store => resolveOfflineChapterIdentity(store.transaction, novelId, chapterNumber, value => { result = value; }, expected));
  return result;
}
async function requiredOfflineIdentity(novelId: number, chapterNumber: number, captured?: ChapterIdentity): Promise<ChapterIdentity> {
  if (!captured || !chapterIdentity(captured)) throw new ChapterManifestChangedError();
  const generation=storageGeneration(),current = await offlineChapterIdentity(novelId, chapterNumber, captured);
  assertStorageGeneration(generation);
  if (!current) throw new ChapterManifestChangedError();
  return captured;
}

const openDatabase = openOfflineDatabase;

const readStore = async <T>(name:string,work:(store:IDBObjectStore)=>IDBRequest<T>):Promise<T> => {
  const generation=storageGeneration(),database=await openDatabase();
  try{return await new Promise<T>((resolve,reject)=>{
    const tx=offlineTransaction(database,name,"readonly"),request=work(tx.objectStore(name));
    tx.oncomplete=()=>{try{assertStorageGeneration(generation);resolve(request.result);}catch(error){reject(error);}};
    tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
  });}finally{database.close();}
};
const withStore = <T>(_mode:IDBTransactionMode,work:(store:IDBObjectStore)=>IDBRequest<T>)=>readStore(STORE_NAME,work);

const runStoreTransaction = async (mode: IDBTransactionMode, work: (store: IDBObjectStore) => void): Promise<void> => {
  const generation=storageGeneration(),database = await openDatabase();
  try {
    assertStorageGeneration(generation);
    await new Promise<void>((resolve, reject) => {
      const transaction = offlineTransaction(database,STORE_NAME, mode);
      work(transaction.objectStore(STORE_NAME));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => {};
      transaction.onabort = () => reject(transactionFailure(transaction));
    });
  } finally {
    database.close();
  }
};

const withAudioStore = <T>(_mode:IDBTransactionMode,work:(store:IDBObjectStore)=>IDBRequest<T>)=>readStore(AUDIO_STORE_NAME,work);

export type BrowserAudioLease = {
  cache_key:string; novelId:number; chapterNumber:number; chapter_key:string; manifest_epoch:string; manifest_revision:string; owner:string; token:string;
  databaseName:string; expiresAt:number;
};
export class BrowserAudioLeaseLostError extends Error {
  constructor(){super("Another tab now owns this chapter's audio. Completed parts were preserved; retry after it finishes.");this.name="BrowserAudioLeaseLostError";}
}
export const randomAudioToken=()=>[...crypto.getRandomValues(new Uint8Array(16))].map(byte=>byte.toString(16).padStart(2,"0")).join("");
const leaseKey=(novelId:number,identity:ChapterIdentity)=>`lease:${chapterKey(novelId,identity)}`;
const leaseMatches=(row:BrowserAudioLease|undefined,lease:BrowserAudioLease,requireLive=true)=>Boolean(row && row.owner===lease.owner && row.token===lease.token && row.databaseName===lease.databaseName && row.cache_key===lease.cache_key && (!requireLive || row.expiresAt>Date.now()));
const validateLeaseTarget=(lease:BrowserAudioLease|undefined,novelId:number,chapterNumber:number)=>{
  if(lease && (lease.cache_key!==leaseKey(novelId,lease)||lease.novelId!==novelId||lease.chapterNumber!==chapterNumber))throw new BrowserAudioLeaseLostError();
};
/** Lease validation and the mutation share one transaction, so takeover cannot
 * interleave between checking ownership and committing audio or a deletion. */
const audioMutation=async<T>(names:string[],shouldWrite:(()=>boolean)|undefined,lease:BrowserAudioLease|undefined,work:(transaction:IDBTransaction,done:(value:T)=>void)=>void,target?:string):Promise<T>=>{
  const generation=storageGeneration();
  if(lease && lease.databaseName!==accountDatabaseName())throw new BrowserAudioLeaseLostError();
  const database=await openDatabase();
  try {
    if(generation!==storageGeneration() || shouldWrite && !shouldWrite())throw new DOMException("Audio operation cancelled","AbortError");
    return await new Promise<T>((resolve,reject)=>{
      const transaction=offlineTransaction(database,[...new Set([...names,...(lease||target?[AUDIO_JOB_STORE_NAME]:[])])],"readwrite");
      let result:T,failure:unknown;
      const fail=(error:unknown)=>{failure=error;transaction.abort();};
      const run=()=>{try{
        if(generation!==storageGeneration() || shouldWrite && !shouldWrite())throw new DOMException("Audio operation cancelled","AbortError");
        if(lease)registerOfflineChapterIdentity(transaction,lease.novelId,lease.chapterNumber,lease,()=>work(transaction,value=>{result=value;}));
        else work(transaction,value=>{result=value;});
      }catch(error){fail(error);}};
      transaction.oncomplete=()=>resolve(result);
      transaction.onabort=()=>reject(failure || transactionFailure(transaction));
      transaction.onerror=()=>{failure ||= transaction.error;};
      if(lease){
        const request=transaction.objectStore(AUDIO_JOB_STORE_NAME).get(lease.cache_key);
        request.onsuccess=()=>{if(leaseMatches(request.result,lease))run();else fail(new BrowserAudioLeaseLostError());};
      }else if(target){
        const request=transaction.objectStore(AUDIO_JOB_STORE_NAME).get(`lease:${target}`);
        request.onsuccess=()=>{if(request.result?.expiresAt>Date.now())fail(new OfflineAudioBusyError());else run();};
      }else run();
    });
  }finally{database.close();}
};
const withNamedStore = async <T>(name:string,mode:IDBTransactionMode,work:(store:IDBObjectStore)=>IDBRequest<T>,shouldWrite?:()=>boolean,lease?:BrowserAudioLease,target?:string):Promise<T>=>{
  if(mode==="readwrite")return audioMutation<T>([name],shouldWrite,lease,(transaction,done)=>{
    const request=work(transaction.objectStore(name));request.onsuccess=()=>done(request.result);
  },target);
  return readStore(name,work);
};

export const browserAudioLeaseStore={
  async claim(novelId:number,chapterNumber:number,owner:string,ttlMs=120_000,captured?:ChapterIdentity):Promise<BrowserAudioLease|null>{
    const databaseName=accountDatabaseName(),generation=storageGeneration();
    const identity=await requiredOfflineIdentity(novelId,chapterNumber,captured);
    const candidate:BrowserAudioLease={...identity,cache_key:leaseKey(novelId,identity),novelId,chapterNumber,owner,token:randomAudioToken(),databaseName,expiresAt:Date.now()+ttlMs};
    return audioMutation<BrowserAudioLease|null>([AUDIO_JOB_STORE_NAME],()=>generation===storageGeneration() && databaseName===accountDatabaseName(),undefined,(transaction,done)=>{
      registerOfflineChapterIdentity(transaction,novelId,chapterNumber,identity,()=>{
      const store=transaction.objectStore(AUDIO_JOB_STORE_NAME),request=store.get(candidate.cache_key);
      request.onsuccess=()=>{
        if(generation!==storageGeneration() || databaseName!==accountDatabaseName()){done(null);return;}
        if(request.result && request.result.expiresAt>Date.now()){done(null);return;}
        candidate.expiresAt=Date.now()+ttlMs;putOfflineRecord(store,candidate);done(candidate);
      };
      });
    });
  },
  async renew(lease:BrowserAudioLease,ttlMs=120_000):Promise<boolean>{
    if(lease.databaseName!==accountDatabaseName())return false;
    const generation=storageGeneration();
    return audioMutation<boolean>([AUDIO_JOB_STORE_NAME],()=>generation===storageGeneration(),undefined,(transaction,done)=>{
      registerOfflineChapterIdentity(transaction,lease.novelId,lease.chapterNumber,lease,()=>{
      const store=transaction.objectStore(AUDIO_JOB_STORE_NAME),request=store.get(lease.cache_key);
      request.onsuccess=()=>{
        const row=request.result as BrowserAudioLease|undefined;
        if(generation!==storageGeneration() || lease.databaseName!==accountDatabaseName()){done(false);return;}
        if(!leaseMatches(row,lease)){done(false);return;}
        putOfflineRecord(store,{...row,expiresAt:Date.now()+ttlMs});done(true);
      };
      });
    });
  },
  async release(lease:BrowserAudioLease):Promise<boolean>{
    if(lease.databaseName!==accountDatabaseName())return false;
    const generation=storageGeneration();
    return audioMutation<boolean>([AUDIO_JOB_STORE_NAME],()=>generation===storageGeneration(),undefined,(transaction,done)=>{
      const store=transaction.objectStore(AUDIO_JOB_STORE_NAME),request=store.get(lease.cache_key);
      request.onsuccess=()=>{if(generation!==storageGeneration() || lease.databaseName!==accountDatabaseName()){done(false);return;}if(!leaseMatches(request.result,lease,false)){done(false);return;}deleteOfflineRecord(store,lease.cache_key);done(true);};
    });
  },
  async get(novelId:number,chapterNumber:number):Promise<BrowserAudioLease|null>{
    const identity=await offlineChapterIdentity(novelId,chapterNumber); if(!identity)return null;
    return await withNamedStore<BrowserAudioLease|undefined>(AUDIO_JOB_STORE_NAME,"readonly",store=>store.get(leaseKey(novelId,identity))) || null;
  },
};

export type ChapterAudioJobStatus = "queued" | "generating" | "ready" | "failed" | "cancelled";

/**
 * Snapshot the synthesis route at job creation. A resumable job must never
 * silently join chunks produced by two providers or voices.
 */
export interface ChapterAudioProviderSnapshot {
  base_url: string;
  model: string;
  voice: string;
  language_code?: string;
}

export interface ChapterAudioJob {
  chapter_key?: string; manifest_epoch?: string; manifest_revision?: string;
  cache_key: string;
  novel_id: number;
  chapter_number: number;
  status: ChapterAudioJobStatus;
  chunks: string[];
  source_version?: string;
  alignment_plan?: AudioPassage[];
  pronunciation_version?: string | null;
  pronunciation_rules?: PronunciationRule[];
  include_author_notes?: boolean;
  completed_chunks: number;
  provider?: ChapterAudioProviderSnapshot;
  error?: string;
  created_at: number;
  updated_at: number;
}

export const offlineReaderStore = {
  async listAll(): Promise<(OfflineChapter & { pinned?: boolean; size_bytes: number })[]> {
    if (!("indexedDB" in window)) return [];
    const records = await withStore<StoredChapter[]>("readonly", (store) => store.getAll());
    return records.map((record) => ({ ...record, size_bytes: chapterSizeBytes(record) }));
  },
  /**
   * Store a chapter. A re-save keeps the existing pinned flag unless
   * `options.pinned` is given, so opening a pinned chapter never unpins it.
   */
  async save(chapter: OfflineChapter, options: { pinned?: boolean } = {}): Promise<void> {
    if (!("indexedDB" in window)) return;
    const identity = chapterIdentity(chapter);
    if (!identity) throw new ChapterManifestChangedError();
    const generation=storageGeneration(),key = stableOfflineChapterKey(chapter.novel_id, identity);
    await runStoreTransaction("readwrite", (store) => {
      registerOfflineChapterIdentity(store.transaction, chapter.novel_id, chapter.chapter_number, identity, () => {
      const existing = store.get(key);
      existing.onsuccess = () => {
        const previous = existing.result as StoredChapter | undefined;
        putOfflineRecord(store,{
          ...chapter,
          cache_key: key,
          cached_at: Date.now(),
          pinned: options.pinned ?? previous?.pinned ?? false,
        } satisfies StoredChapter);
      };
      });
    });
    assertStorageGeneration(generation);
    await this.evictExcess();
  },

  /** Every stored chapter of one novel, in chapter order, with its size. */
  async listForNovel(novelId: number): Promise<OfflineChapterSummary[]> {
    if (!("indexedDB" in window)) return [];
    const records = await withStore<StoredChapter[]>("readonly", (store) => store.index("novel_id").getAll(novelId));
    return records
      .map((record) => ({
        ...(chapterIdentity(record) ?? {}),novel_id: record.novel_id,
        chapter_number: record.chapter_number,
        title: record.title,
        pinned: Boolean(record.pinned),
        cached_at: record.cached_at,
        size_bytes: chapterSizeBytes(record),
      }))
      .sort((left, right) => left.chapter_number - right.chapter_number);
  },

  /** Delete every stored chapter of one novel, pinned or not. Returns the count removed. */
  async removeForNovel(novelId: number): Promise<number> {
    if (!("indexedDB" in window)) return 0;
    let removed = 0;
    await runStoreTransaction("readwrite", (store) => {
      const request = store.index("novel_id").openCursor(IDBKeyRange.only(novelId));
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        deleteOfflineRecord(store,cursor.primaryKey);
        removed += 1;
        cursor.continue();
      };
    });
    return removed;
  },

  /** Keep at most `maximum` chapters by evicting the oldest unpinned ones. Pinned chapters are never evicted, so they may exceed the limit. */
  async evictExcess(maximum = MAX_CACHED_CHAPTERS): Promise<void> {
    if (!("indexedDB" in window)) return;
    await runStoreTransaction("readwrite", (store) => {
      const countRequest = store.count();
      countRequest.onsuccess = () => {
        let overflow = Math.max(0, countRequest.result - maximum);
        if (overflow === 0) return;
        const cursorRequest = store.index("cached_at").openCursor();
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result;
          if (!cursor || overflow <= 0) return;
          if (!(cursor.value as StoredChapter).pinned) {
            deleteOfflineRecord(store,cursor.primaryKey);
            overflow -= 1;
          }
          cursor.continue();
        };
      };
    });
  },

  async get(novelId: number, chapterNumber: number, expected?: ChapterIdentity): Promise<OfflineChapter | null> {
    if (!("indexedDB" in window)) return null;
    let value: OfflineChapter | null = null;
    await runStoreTransaction("readonly", store => resolveOfflineChapterIdentity(store.transaction, novelId, chapterNumber, identity => {
      if (!identity) return;
      const request = store.get(stableOfflineChapterKey(novelId, identity));
      request.onsuccess = () => {
        const row = request.result as StoredChapter | undefined;
        if (row?.chapter_key === identity.chapter_key) value = { ...row, ...identity, chapter_number: chapterNumber };
      };
    }, expected));
    return value;
  },

  async has(novelId: number, chapterNumber: number): Promise<boolean> {
    return Boolean(await this.get(novelId, chapterNumber));
  },

  async countForNovel(novelId: number): Promise<number> {
    if (!("indexedDB" in window)) return 0;
    return readStore(STORE_NAME,store=>store.index("novel_id").count(novelId));
  },
};

interface StoredAudioPayload { audio?: Blob; audio_data?: ArrayBuffer; audio_type?: string }
// WebKit can reject file-backed response Blobs during IndexedDB cloning.
// Persist their bytes instead; public callers still receive ordinary Blobs.
async function audioPayload(audio:Blob):Promise<StoredAudioPayload> {
  const audio_data=typeof audio.arrayBuffer==="function" ? await audio.arrayBuffer() : await new Promise<ArrayBuffer>((resolve,reject)=>{
    const reader=new FileReader();reader.onload=()=>resolve(reader.result as ArrayBuffer);reader.onerror=()=>reject(reader.error);reader.readAsArrayBuffer(audio);
  });
  return {audio_data,audio_type:audio.type};
}
function audioBlob(value:StoredAudioPayload|undefined):Blob|null {
  if(!value)return null;
  if(value.audio_data!==undefined)return new Blob([value.audio_data],{type:value.audio_type || "application/octet-stream"});
  return value.audio || null;
}

export const chapterAudioStore = {
  async recording(novelId:number,chapterNumber:number):Promise<{audio:Blob;manifest:AudioManifest|null}|null> {
    if (!("indexedDB" in window)) return null;
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return null;
    const value=await withAudioStore<(StoredAudioPayload & {manifest?:AudioManifest})|undefined>("readonly",store=>store.get(chapterKey(novelId,identity)));
    assertStorageGeneration(ownerGeneration);const audio=audioBlob(value);
    return audio ? {audio,manifest:value?.manifest || null} : null;
  },
  async manifest(novelId:number,chapterNumber:number):Promise<AudioManifest|null> {
    if (!("indexedDB" in window)) return null;
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return null;
    const value=await withAudioStore<{manifest?:AudioManifest}|undefined>("readonly",store=>store.get(chapterKey(novelId,identity)));
    assertStorageGeneration(ownerGeneration);return value?.manifest || null;
  },
  async save(novelId: number, chapterNumber: number, audio: Blob, manifest?: AudioManifest | null, shouldWrite?: () => boolean,lease?:BrowserAudioLease): Promise<void> {
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const identity=chapterIdentity(manifest);if(!identity)throw new ChapterManifestChangedError();
    const generation=storageGeneration(),payload=await audioPayload(audio);let cancelled=false;
    const guard=()=>{if(generation!==storageGeneration())return false;const allowed=!shouldWrite || shouldWrite();cancelled ||= !allowed;return allowed;};
    await audioMutation<void>([AUDIO_STORE_NAME],guard,lease,(transaction,done)=>{
      registerOfflineChapterIdentity(transaction,novelId,chapterNumber,identity,()=>{
      putOfflineRecord(transaction.objectStore(AUDIO_STORE_NAME),{...identity,novel_id:novelId,chapter_number:chapterNumber,cache_key:chapterKey(novelId,identity),...payload,manifest,created_at:Date.now()});done();
      });
    },chapterKey(novelId,identity)).catch(error=>{
      if(!lease && generation===storageGeneration() && cancelled && error instanceof DOMException && error.name==='AbortError')return;
      throw error;
    });
  },

  async removeForJob(novelId:number,chapterNumber:number,jobId:number,lease?:BrowserAudioLease):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return;
    await audioMutation<void>([AUDIO_STORE_NAME],()=>ownerGeneration===storageGeneration(),lease,(transaction,done)=>{
      const store=transaction.objectStore(AUDIO_STORE_NAME),request=store.get(chapterKey(novelId,identity));
      request.onsuccess=()=>{if(request.result?.manifest?.job_id===jobId)deleteOfflineRecord(store,chapterKey(novelId,identity));done();};
    },chapterKey(novelId,identity));
  },

  async removeBrowser(novelId:number,chapterNumber:number,shouldWrite?:()=>boolean,lease?:BrowserAudioLease):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return;
    await audioMutation<void>([AUDIO_STORE_NAME],()=>ownerGeneration===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(transaction,done)=>{
      const store=transaction.objectStore(AUDIO_STORE_NAME),request=store.get(chapterKey(novelId,identity));
      request.onsuccess=()=>{if(request.result?.manifest?.job_id===undefined)deleteOfflineRecord(store,chapterKey(novelId,identity));done();};
    },chapterKey(novelId,identity));
  },
  async saveBrowser(novelId:number,chapterNumber:number,audio:Blob,manifest:AudioManifest,shouldWrite?:()=>boolean,lease?:BrowserAudioLease):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const identity=chapterIdentity(manifest);if(!identity)throw new ChapterManifestChangedError();
    if(manifest.job_id!==undefined)throw new Error("Browser audio cannot claim a server job identity.");
    const generation=storageGeneration(),payload=await audioPayload(audio);
    await audioMutation<void>([AUDIO_STORE_NAME],()=>generation===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(transaction,done)=>{
      registerOfflineChapterIdentity(transaction,novelId,chapterNumber,identity,()=>{
      const store=transaction.objectStore(AUDIO_STORE_NAME),request=store.get(chapterKey(novelId,identity));
      request.onsuccess=()=>{
        if(request.result?.manifest?.job_id!==undefined){transaction.abort();return;}
        putOfflineRecord(store,{...identity,novel_id:novelId,chapter_number:chapterNumber,cache_key:chapterKey(novelId,identity),...payload,manifest,created_at:Date.now()});done();
      };
      });
    },chapterKey(novelId,identity)).catch(error=>{if(error instanceof DOMException && error.name==="AbortError" && (!shouldWrite || shouldWrite()) && generation===storageGeneration())throw new Error("A server recording is cached for this chapter. Remove it before saving browser audio.");throw error;});
  },

  async get(novelId: number, chapterNumber: number): Promise<Blob | null> {
    if (!("indexedDB" in window)) return null;
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return null;
    const value = await withAudioStore<StoredAudioPayload | undefined>("readonly", (store) => store.get(chapterKey(novelId,identity)));
    assertStorageGeneration(ownerGeneration);return audioBlob(value);
  },

  async remove(novelId:number,chapterNumber:number,lease?:BrowserAudioLease):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return;
    await audioMutation<void>([AUDIO_STORE_NAME],()=>ownerGeneration===storageGeneration(),lease,(transaction,done)=>{deleteOfflineRecord(transaction.objectStore(AUDIO_STORE_NAME),chapterKey(novelId,identity));done();},chapterKey(novelId,identity));
  },
};

const segmentKey = (novelId: number, identity: ChapterIdentity, index: number) => `${chapterKey(novelId,identity)}:${index}`;

export const chapterAudioJobStore = {
  async get(novelId: number, chapterNumber: number): Promise<ChapterAudioJob | null> {
    if (!("indexedDB" in window)) return null;
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return null;
    const value = await withNamedStore<ChapterAudioJob | undefined>(AUDIO_JOB_STORE_NAME, "readonly", (store) => store.get(chapterKey(novelId,identity)));
    assertStorageGeneration(ownerGeneration);return value || null;
  },

  async save(job: ChapterAudioJob, shouldWrite?: () => boolean, lease?:BrowserAudioLease): Promise<void> {
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,job.novel_id,job.chapter_number);
    const ownerGeneration=storageGeneration(),identity=chapterIdentity(job);if(!identity)throw new ChapterManifestChangedError();
    await audioMutation<void>([AUDIO_JOB_STORE_NAME],()=>ownerGeneration===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(tx,done)=>registerOfflineChapterIdentity(tx,job.novel_id,job.chapter_number,identity,()=>{
      putOfflineRecord(tx.objectStore(AUDIO_JOB_STORE_NAME),{...job,cache_key:chapterKey(job.novel_id,identity),updated_at:Date.now()});done();
    }),chapterKey(job.novel_id,identity));
  },

  async saveSegment(novelId: number, chapterNumber: number, index: number, audio: Blob, shouldWrite?: () => boolean,lease?:BrowserAudioLease,captured?:ChapterIdentity): Promise<void> {
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const generation=storageGeneration(),identity=await requiredOfflineIdentity(novelId,chapterNumber,lease || captured);
    assertStorageGeneration(generation);
    const payload=await audioPayload(audio);
    await audioMutation<void>([AUDIO_SEGMENT_STORE_NAME],()=>generation===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(tx,done)=>registerOfflineChapterIdentity(tx,novelId,chapterNumber,identity,()=>{
      putOfflineRecord(tx.objectStore(AUDIO_SEGMENT_STORE_NAME),{...identity,novel_id:novelId,chapter_number:chapterNumber,segment_key:segmentKey(novelId,identity,index),cache_key:chapterKey(novelId,identity),index,...payload});done();
    }),chapterKey(novelId,identity));
  },

  async segments(novelId: number, chapterNumber: number): Promise<Blob[]> {
    if (!("indexedDB" in window)) return [];
    const ownerGeneration=storageGeneration(),identity=await offlineChapterIdentity(novelId,chapterNumber);assertStorageGeneration(ownerGeneration);if(!identity)return [];
    const rows=await readStore<Array<StoredAudioPayload & {index:number}>>(AUDIO_SEGMENT_STORE_NAME,store=>store.index("cache_key").getAll(chapterKey(novelId,identity)));
    assertStorageGeneration(ownerGeneration);return rows.sort((a,b)=>a.index-b.index).map(audioBlob).filter((audio):audio is Blob=>audio!==null);
  },

  async clearSegments(novelId:number,chapterNumber:number,shouldWrite?:()=>boolean,lease?:BrowserAudioLease,captured?:ChapterIdentity):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const ownerGeneration=storageGeneration(),identity=await requiredOfflineIdentity(novelId,chapterNumber,lease || captured);
    assertStorageGeneration(ownerGeneration);
    await audioMutation<void>([AUDIO_SEGMENT_STORE_NAME],()=>ownerGeneration===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(transaction,done)=>{
      const request=transaction.objectStore(AUDIO_SEGMENT_STORE_NAME).index("cache_key").openCursor(IDBKeyRange.only(chapterKey(novelId,identity)));
      request.onsuccess=()=>{const cursor=request.result;if(cursor){deleteOfflineRecord(transaction.objectStore(AUDIO_SEGMENT_STORE_NAME),cursor.primaryKey);cursor.continue();}else done();};
    },chapterKey(novelId,identity));
  },
  async remove(novelId:number,chapterNumber:number,shouldWrite?:()=>boolean,lease?:BrowserAudioLease,captured?:ChapterIdentity):Promise<void>{
    if (!("indexedDB" in window)) return;
    validateLeaseTarget(lease,novelId,chapterNumber);
    const ownerGeneration=storageGeneration(),identity=await requiredOfflineIdentity(novelId,chapterNumber,lease || captured);
    // Job and all segments are removed under the same fencing check.
    assertStorageGeneration(ownerGeneration);
    await audioMutation<void>([AUDIO_JOB_STORE_NAME,AUDIO_SEGMENT_STORE_NAME],()=>ownerGeneration===storageGeneration() && (!shouldWrite || shouldWrite()),lease,(transaction,done)=>{
      deleteOfflineRecord(transaction.objectStore(AUDIO_JOB_STORE_NAME),chapterKey(novelId,identity));
      const request=transaction.objectStore(AUDIO_SEGMENT_STORE_NAME).index("cache_key").openCursor(IDBKeyRange.only(chapterKey(novelId,identity)));
      request.onsuccess=()=>{const cursor=request.result;if(cursor){deleteOfflineRecord(transaction.objectStore(AUDIO_SEGMENT_STORE_NAME),cursor.primaryKey);cursor.continue();}else done();};
    },chapterKey(novelId,identity));
  },
};
