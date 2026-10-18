import { fixtureChapterIdentity as identity,fixtureChapterCacheKey as cacheKey } from "../fixtures/chapterIdentity";
import "fake-indexeddb/auto";
import { Blob as NativeBlob } from "node:buffer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accountDatabaseName, activateAccountStorage } from "../../src/services/accountStorage";
import { browserAudioLeaseStore, chapterAudioJobStore, chapterAudioStore, offlineReaderStore, type ChapterAudioJob } from "../../src/services/offlineReaderStore";
import type { AudioManifest } from "../../src/services/audioAlignment";

async function rawAudioRow(storeName:string,cacheKey:string,value?:unknown):Promise<unknown> {
  const database=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(accountDatabaseName());request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  try {
    return await new Promise((resolve,reject)=>{
      const transaction=database.transaction(storeName,value===undefined?"readonly":"readwrite");
      const store=transaction.objectStore(storeName),request=value===undefined?store.get(cacheKey):store.put(value);
      let result:unknown;request.onsuccess=()=>{result=request.result;};
      transaction.oncomplete=()=>resolve(result);transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);
    });
  }finally{database.close();}
}
async function bytes(audio:Blob):Promise<number[]> {
  const buffer=typeof audio.arrayBuffer==="function"?await audio.arrayBuffer():await new Promise<ArrayBuffer>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result as ArrayBuffer);reader.onerror=()=>reject(reader.error);reader.readAsArrayBuffer(audio);});
  return [...new Uint8Array(buffer)];
}

const chapter = (novelId: number, chapterNumber: number, content = "text") => ({
  ...identity(novelId,chapterNumber),id: novelId * 1000 + chapterNumber,
  novel_id: novelId,
  chapter_number: chapterNumber,
  title: `Chapter ${chapterNumber}`,
  content,
});

describe("private recording cache", () => {
  const manifest = (jobId: number): AudioManifest => ({
    ...identity(1,2),job_id: jobId, source_version: "source-a", rendition: "original", include_author_notes: false,
    precision: "segment", duration_seconds: 1,
    segments: [{ part_index: 0, block_id: "p1", text_offset: 0, text_length: 4, start_seconds: 0, end_seconds: 1 }],
  });
  beforeEach(async () => {
    activateAccountStorage(201);
    await resetDatabase();await offlineReaderStore.save(chapter(1,2));await offlineReaderStore.save(chapter(1,3));
    activateAccountStorage(202);
    await resetDatabase();await offlineReaderStore.save(chapter(1,2));await offlineReaderStore.save(chapter(1,3));
    activateAccountStorage(201);
  });
  afterEach(() => {activateAccountStorage(null);vi.restoreAllMocks();});

  it("claims a chapter atomically across concurrent tabs and renews only its live token",async()=>{
    let now=1000;vi.spyOn(Date,"now").mockImplementation(()=>now);
    const results=await Promise.all([browserAudioLeaseStore.claim(1,2,"tab-a",100,identity(1,2)),browserAudioLeaseStore.claim(1,2,"tab-b",100,identity(1,2))]);
    expect(results.filter(Boolean)).toHaveLength(1);const lease=results.find(Boolean)!;
    now=1050;expect(await browserAudioLeaseStore.renew(lease,100)).toBe(true);
    now=1110;expect(await browserAudioLeaseStore.claim(1,2,"other",100,identity(1,2))).toBeNull();
    now=1160;expect(await browserAudioLeaseStore.renew(lease,100)).toBe(false);
    const successor=(await browserAudioLeaseStore.claim(1,2,"other",100,identity(1,2)))!;
    expect(successor.token).not.toBe(lease.token);expect(await browserAudioLeaseStore.release(lease)).toBe(false);
    expect((await browserAudioLeaseStore.get(1,2))?.token).toBe(successor.token);
    expect(await browserAudioLeaseStore.release(successor)).toBe(true);
  });
  it("fences stale provider completions, cleanup and deletion after expired takeover",async()=>{
    let now=1000;vi.spyOn(Date,"now").mockImplementation(()=>now);
    const predecessor=(await browserAudioLeaseStore.claim(1,2,"old-tab",100,identity(1,2)))!;
    const job:ChapterAudioJob={...identity(1,2),cache_key:cacheKey(1,2),novel_id:1,chapter_number:2,status:"generating",chunks:["One"],completed_chunks:0,created_at:1,updated_at:1};
    await chapterAudioJobStore.save(job,undefined,predecessor);
    now=1101;const successor=(await browserAudioLeaseStore.claim(1,2,"new-tab",100,identity(1,2)))!;
    await chapterAudioJobStore.save({...job,status:"ready",completed_chunks:1},undefined,successor);
    await chapterAudioJobStore.saveSegment(1,2,0,new Blob(["new"]),undefined,successor,identity(1,2));
    const browserManifest={...manifest(10),job_id:undefined};
    await chapterAudioStore.saveBrowser(1,2,new Blob(["new recording"]),browserManifest,undefined,successor);
    for(const operation of [
      ()=>chapterAudioJobStore.save({...job,status:"failed"},undefined,predecessor),
      ()=>chapterAudioJobStore.saveSegment(1,2,0,new Blob(["old"]),undefined,predecessor,identity(1,2)),
      ()=>chapterAudioJobStore.clearSegments(1,2,undefined,predecessor,identity(1,2)),
      ()=>chapterAudioStore.saveBrowser(1,2,new Blob(["old recording"]),browserManifest,undefined,predecessor),
      ()=>chapterAudioStore.save(1,2,new Blob(["old"]),browserManifest,undefined,predecessor),
      ()=>chapterAudioStore.remove(1,2,predecessor),
      ()=>chapterAudioStore.removeForJob(1,2,10,predecessor),
      ()=>chapterAudioJobStore.remove(1,2,undefined,predecessor),
      ()=>chapterAudioStore.removeBrowser(1,2,undefined,predecessor),
    ])await expect(operation()).rejects.toMatchObject({name:"BrowserAudioLeaseLostError"});
    expect((await chapterAudioJobStore.get(1,2))?.status).toBe("ready");expect(await bytes((await chapterAudioJobStore.segments(1,2))[0])).toEqual([...new TextEncoder().encode("new")]);
    expect(await bytes((await chapterAudioStore.get(1,2))!)).toEqual([...new TextEncoder().encode("new recording")]);
    await chapterAudioJobStore.remove(1,2,undefined,successor);await chapterAudioStore.removeBrowser(1,2,undefined,successor);
    expect(await chapterAudioJobStore.get(1,2)).toBeNull();expect(await chapterAudioStore.get(1,2)).toBeNull();
  });
  it("keeps lease ownership within the immutable account database and chapter",async()=>{
    const first=(await browserAudioLeaseStore.claim(1,2,"same-tab",undefined,identity(1,2)))!;
    await expect(chapterAudioJobStore.saveSegment(1,3,0,new Blob(["wrong chapter"]),undefined,first,identity(1,3))).rejects.toMatchObject({name:"BrowserAudioLeaseLostError"});
    activateAccountStorage(202);expect(await browserAudioLeaseStore.get(1,2)).toBeNull();
    const second=(await browserAudioLeaseStore.claim(1,2,"same-tab",undefined,identity(1,2)))!;
    expect(second.databaseName).not.toBe(first.databaseName);expect(await browserAudioLeaseStore.renew(first)).toBe(false);expect(await browserAudioLeaseStore.release(first)).toBe(false);
    await expect(chapterAudioStore.removeBrowser(1,2,undefined,first)).rejects.toMatchObject({name:"BrowserAudioLeaseLostError"});
    expect((await browserAudioLeaseStore.get(1,2))?.token).toBe(second.token);
    activateAccountStorage(201);expect((await browserAudioLeaseStore.get(1,2))?.token).toBe(first.token);
  });
  it("stores audio and resumable parts as bytes while returning their exact Blob content and MIME",async()=>{
    const audio=new Blob([new Uint8Array([82,73,70,70,0,255])],{type:"audio/wav"});
    await chapterAudioStore.save(1,2,audio,manifest(10));
    const raw=await rawAudioRow("chapter_audio",cacheKey(1,2)) as {audio?:Blob;audio_data:ArrayBuffer;audio_type:string};
    expect(raw.audio).toBeUndefined();expect([...new Uint8Array(raw.audio_data)]).toEqual([82,73,70,70,0,255]);expect(raw.audio_type).toBe("audio/wav");
    const cached=(await chapterAudioStore.recording(1,2))!;
    expect(cached.audio.type).toBe("audio/wav");expect(await bytes(cached.audio)).toEqual([82,73,70,70,0,255]);expect(cached.manifest?.job_id).toBe(10);
    await chapterAudioJobStore.saveSegment(1,2,1,new Blob([new Uint8Array([9])],{type:"audio/mpeg"}),undefined,undefined,identity(1,2));
    await chapterAudioJobStore.saveSegment(1,2,0,audio,undefined,undefined,identity(1,2));
    const segments=await chapterAudioJobStore.segments(1,2);
    expect(await bytes(segments[0])).toEqual([82,73,70,70,0,255]);expect(await bytes(segments[1])).toEqual([9]);expect(segments[1].type).toBe("audio/mpeg");
    const rawPart=await rawAudioRow("chapter_audio_segments",`${cacheKey(1,2)}:0`) as {audio?:Blob;audio_data:ArrayBuffer};
    expect(rawPart.audio).toBeUndefined();expect(rawPart.audio_data.byteLength).toBe(6);
  });
  it("reads identity-bound Blob recordings and segments without rewriting their manifests",async()=>{
    await chapterAudioStore.save(1,2,new Blob(["initialize"]),{...manifest(10),job_id:undefined});
    const legacy=new NativeBlob([new Uint8Array([1,2,3])],{type:"audio/wav"});
    await rawAudioRow("chapter_audio",cacheKey(1,2),{...identity(1,2),novel_id:1,chapter_number:2,cache_key:cacheKey(1,2),audio:legacy,manifest:manifest(10)});
    await rawAudioRow("chapter_audio_segments",`${cacheKey(1,2)}:0`,{...identity(1,2),novel_id:1,chapter_number:2,segment_key:`${cacheKey(1,2)}:0`,cache_key:cacheKey(1,2),index:0,audio:legacy});
    const cached=(await chapterAudioStore.recording(1,2))!;
    expect(await bytes(cached.audio)).toEqual([1,2,3]);expect(cached.audio.type).toBe("audio/wav");expect(cached.manifest?.job_id).toBe(10);
    expect(await bytes((await chapterAudioJobStore.segments(1,2))[0])).toEqual([1,2,3]);
  });
  it("discards audio encoded after an account change instead of writing into the new account",async()=>{
    let complete!:(value:ArrayBuffer)=>void;
    const pending=new Promise<ArrayBuffer>(resolve=>{complete=resolve;});
    const audio=new Blob(["private"]);Object.defineProperty(audio,"arrayBuffer",{value:()=>pending});
    const writes=[chapterAudioStore.save(1,2,audio,manifest(10)),chapterAudioStore.saveBrowser(1,3,audio,{...manifest(10),...identity(1,3),job_id:undefined}),chapterAudioJobStore.saveSegment(1,2,0,audio,undefined,undefined,identity(1,2))];
    activateAccountStorage(202);complete(new ArrayBuffer(4));
    const results=await Promise.allSettled(writes);
    expect(results.every(result=>result.status==="rejected" && result.reason.name==="AbortError")).toBe(true);
    expect(await chapterAudioStore.get(1,2)).toBeNull();expect(await chapterAudioStore.get(1,3)).toBeNull();expect(await chapterAudioJobStore.segments(1,2)).toEqual([]);
    activateAccountStorage(201);expect(await chapterAudioStore.get(1,2)).toBeNull();expect(await chapterAudioJobStore.segments(1,2)).toEqual([]);
  });
  it("deletes a server job's recording and its manifest together", async () => {
    await chapterAudioStore.save(1, 2, new Blob(["audio"]), manifest(10));
    await chapterAudioStore.removeForJob(1, 2, 10);
    expect(await chapterAudioStore.get(1, 2)).toBeNull();
    expect(await chapterAudioStore.manifest(1, 2)).toBeNull();
    await expect(chapterAudioStore.removeForJob(1, 2, 10)).resolves.toBeUndefined();
  });

  it("preserves a newer job or browser-generated recording", async () => {
    await chapterAudioStore.save(1, 2, new Blob(["new"]), manifest(11));
    await chapterAudioStore.removeForJob(1, 2, 10);
    expect(await chapterAudioStore.get(1, 2)).not.toBeNull();
    expect((await chapterAudioStore.manifest(1, 2))?.job_id).toBe(11);
    await chapterAudioStore.save(1, 2, new Blob(["local"]),{...manifest(10),job_id:undefined});
    await chapterAudioStore.removeForJob(1, 2, 11);
    expect(await chapterAudioStore.get(1, 2)).not.toBeNull();
  });

  it("checks cancellation after opening storage and does not resurrect a deleted recording", async () => {
    await chapterAudioStore.save(1, 2, new Blob(["old"]), manifest(10));
    await chapterAudioStore.removeForJob(1, 2, 10);
    let active = true;
    let checks = 0;
    const pending = chapterAudioStore.save(1, 2, new Blob(["late"]), manifest(10), () => {
      checks += 1;
      return active;
    });
    expect(checks).toBe(0);
    active = false;
    await pending;
    expect(checks).toBe(1);
    expect(await chapterAudioStore.get(1, 2)).toBeNull();
    expect(await chapterAudioStore.manifest(1, 2)).toBeNull();
  });

  it("cannot remove a matching job ID from another account", async () => {
    await chapterAudioStore.save(1, 2, new Blob(["first"]), manifest(10));
    activateAccountStorage(202);
    expect(await chapterAudioStore.get(1, 2)).toBeNull();
    await chapterAudioStore.save(1, 2, new Blob(["second"]), manifest(10));
    await chapterAudioStore.removeForJob(1, 2, 10);
    expect(await chapterAudioStore.get(1, 2)).toBeNull();
    activateAccountStorage(201);
    expect(await chapterAudioStore.get(1, 2)).not.toBeNull();
    expect((await chapterAudioStore.manifest(1, 2))?.job_id).toBe(10);
  });

  it("prevents cancelled job and segment writes after storage opens and preserves saved work", async()=>{
    const job:ChapterAudioJob={...identity(1,2),cache_key:cacheKey(1,2),novel_id:1,chapter_number:2,chunks:["First","Second"],completed_chunks:1,status:"cancelled",created_at:1,updated_at:1};
    await chapterAudioJobStore.save(job);
    await chapterAudioJobStore.saveSegment(1,2,0,new Blob(["completed"]),undefined,undefined,identity(1,2));
    let active=true;
    const pending=chapterAudioJobStore.save({...job,status:"generating"},()=>active);
    active=false;
    await expect(pending).rejects.toMatchObject({name:"AbortError"});
    await expect(chapterAudioJobStore.saveSegment(1,2,1,new Blob(["late"]),()=>false,undefined,identity(1,2))).rejects.toMatchObject({name:"AbortError"});
    await expect(chapterAudioJobStore.clearSegments(1,2,()=>false,undefined,identity(1,2))).rejects.toMatchObject({name:"AbortError"});
    expect((await chapterAudioJobStore.get(1,2))?.status).toBe("cancelled");
    expect(await chapterAudioJobStore.segments(1,2)).toHaveLength(1);
  });
  it("removes browser recordings without deleting server-owned cached audio",async()=>{
    await chapterAudioStore.save(1,2,new Blob(["server"]),manifest(10));
    await chapterAudioStore.removeBrowser(1,2);
    expect((await chapterAudioStore.manifest(1,2))?.job_id).toBe(10);
    await chapterAudioStore.save(1,2,new Blob(["browser"]),{...manifest(10),job_id:undefined});
    await expect(chapterAudioStore.removeBrowser(1,2,()=>false)).rejects.toMatchObject({name:"AbortError"});
    expect(await chapterAudioStore.get(1,2)).not.toBeNull();
    await chapterAudioStore.removeBrowser(1,2);
    expect(await chapterAudioStore.get(1,2)).toBeNull();
  });
  it("atomically refuses browser output over a cached server recording",async()=>{
    const browserManifest={...manifest(10),job_id:undefined};
    await chapterAudioStore.save(1,2,new Blob(["server"]),manifest(10));
    await expect(chapterAudioStore.saveBrowser(1,2,new Blob(["browser"]),browserManifest)).rejects.toThrow("server recording");
    expect((await chapterAudioStore.manifest(1,2))?.job_id).toBe(10);
    await chapterAudioStore.removeForJob(1,2,10);
    await chapterAudioStore.saveBrowser(1,2,new Blob(["browser"]),browserManifest);
    expect((await chapterAudioStore.manifest(1,2))?.job_id).toBeUndefined();
    await expect(chapterAudioStore.saveBrowser(1,2,new Blob(["late"]),browserManifest,()=>false)).rejects.toMatchObject({name:"AbortError"});
  });
});

const resetDatabase = () => new Promise<void>((resolve, reject) => {
  const request = indexedDB.deleteDatabase(accountDatabaseName());
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
