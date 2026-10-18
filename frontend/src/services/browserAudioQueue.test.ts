import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { activateAccountStorage } from "./accountStorage";
import { BrowserAudioQueue, type BrowserAudioBatchInput } from "./browserAudioQueue";
import { chapterService } from "./chapterService";
import { browserAudioLeaseStore, chapterAudioJobStore, chapterAudioStore, type BrowserAudioLease, type ChapterAudioJob } from "./offlineReaderStore";
import { mergeAudioSegments, ttsService } from "./ttsService";
import type { AudioManifest } from "./audioAlignment";
import type { ChapterDocument } from "../components/reader/chapterDocument";
vi.mock("./chapterService",()=>({chapterService:{getChapterContentByNumber:vi.fn()}}));
vi.mock("./offlineReaderStore",()=>({randomAudioToken:()=>"test-owner",offlineReaderStore:{save:vi.fn()},browserAudioLeaseStore:{claim:vi.fn(),renew:vi.fn(),release:vi.fn(),get:vi.fn()},chapterAudioStore:{get:vi.fn(),manifest:vi.fn(),recording:vi.fn(),saveBrowser:vi.fn(),removeBrowser:vi.fn()},chapterAudioJobStore:{get:vi.fn(),save:vi.fn(),saveSegment:vi.fn(),segments:vi.fn(),clearSegments:vi.fn(),remove:vi.fn()}}));
vi.mock("./ttsService",()=>({ttsService:{synthesize:vi.fn()},mergeAudioSegments:vi.fn()}));
const document:ChapterDocument={schema_version:1,source_format:"html",content_version:"source-a",plain_text:"😀 First story passage.\nLast story passage.\nAn author note.",blocks:[
  {id:"first",kind:"p",html:"<p>😀 <em>First</em> story passage.</p>",text:"😀 First story passage."},
  {id:"last",kind:"p",html:"<p>Last story passage.</p>",text:"Last story passage."},
  {id:"note",kind:"p",html:"<p>An author note.</p>",text:"An author note.",role:"author_note"},
]};
const identityFor=(chapter:number)=>({chapter_key:`11111111-1111-4111-8111-${String(chapter+10000).padStart(12,"0")}`,manifest_epoch:"22222222-2222-4222-8222-222222222222",manifest_revision:"1"});
const input=():BrowserAudioBatchInput=>({libraryId:1,novelId:2,chapterNumbers:[1],chapterIdentities:Object.fromEntries(Array.from({length:205},(_,index)=>[index-2,identityFor(index-2)])),provider:{baseUrl:"http://localhost:8880/v1",model:"fixture",voice:"voice",apiKey:"private-key"},presetId:"kokoro_mps"});
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}
let queue:BrowserAudioQueue,account=1;
const leases=new Map<string,BrowserAudioLease>();
const jobs=new Map<string,ChapterAudioJob>(),parts=new Map<string,Blob[]>(),recordings=new Map<string,Blob>(),manifests=new Map<string,AudioManifest|null|undefined>();
const key=(novel:number,chapter:number)=>`${account}:${novel}:${chapter}`;
const selectAccount=(id:number)=>{activateAccountStorage(id);account=id;};
const idle=()=>waitFor(()=>expect(queue.getSnapshot().running).toBe(false));
const row=()=>queue.getSnapshot().rows[0];
beforeEach(()=>{
  vi.resetAllMocks();leases.clear();jobs.clear();parts.clear();recordings.clear();manifests.clear();selectAccount(1);
  vi.mocked(browserAudioLeaseStore.claim).mockImplementation(async(n,c,owner,ttl=120000,captured)=>{const existing=leases.get(key(n,c));if(existing && existing.expiresAt>Date.now())return null;const lease={...(captured || identityFor(c)),cache_key:`lease:${n}:${c}`,novelId:n,chapterNumber:c,owner,token:crypto.randomUUID(),databaseName:String(account),expiresAt:Date.now()+ttl};leases.set(key(n,c),lease);return lease;});
  vi.mocked(browserAudioLeaseStore.renew).mockImplementation(async(lease,ttl=120000)=>{const existing=leases.get(key(lease.novelId,lease.chapterNumber));if(existing?.token!==lease.token || existing.expiresAt<=Date.now())return false;leases.set(key(lease.novelId,lease.chapterNumber),{...existing,expiresAt:Date.now()+ttl});return true;});
  vi.mocked(browserAudioLeaseStore.release).mockImplementation(async lease=>{const existing=leases.get(key(lease.novelId,lease.chapterNumber));if(existing?.token!==lease.token)return false;leases.delete(key(lease.novelId,lease.chapterNumber));return true;});
  vi.mocked(chapterService.getChapterContentByNumber).mockImplementation(async(number)=>({...identityFor(number),source_version:document.content_version,current_content_version:document.content_version,id:9+number,novel_id:2,chapter_number:number,title:"Title",document,content:document.plain_text}));
  vi.mocked(chapterAudioJobStore.get).mockImplementation(async(n,c)=>jobs.get(key(n,c)) || null);
  vi.mocked(chapterAudioJobStore.save).mockImplementation(async(job,guard,lease)=>{if(lease && leases.get(key(job.novel_id,job.chapter_number))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())throw new DOMException("stale","AbortError");jobs.set(key(job.novel_id,job.chapter_number),structuredClone(job));});
  vi.mocked(chapterAudioJobStore.saveSegment).mockImplementation(async(n,c,index,audio,guard,lease)=>{if(lease && leases.get(key(n,c))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())throw new DOMException("stale","AbortError");const list=parts.get(key(n,c)) || [];list[index]=audio;parts.set(key(n,c),list);});
  vi.mocked(chapterAudioJobStore.segments).mockImplementation(async(n,c)=>[...(parts.get(key(n,c)) || [])]);
  vi.mocked(chapterAudioJobStore.clearSegments).mockImplementation(async(n,c,guard,lease)=>{if(lease && leases.get(key(n,c))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())throw new DOMException("stale","AbortError");parts.delete(key(n,c));});
  vi.mocked(chapterAudioStore.get).mockImplementation(async(n,c)=>recordings.get(key(n,c)) || null);
  vi.mocked(chapterAudioStore.manifest).mockImplementation(async(n,c)=>manifests.get(key(n,c)) || null);
  vi.mocked(chapterAudioStore.recording).mockImplementation(async(n,c)=>{const audio=recordings.get(key(n,c));return audio?{audio,manifest:manifests.get(key(n,c)) || null}:null;});
  vi.mocked(chapterAudioStore.saveBrowser).mockImplementation(async(n,c,blob,manifest,guard,lease)=>{if(lease && leases.get(key(n,c))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())return;if(manifests.get(key(n,c))?.job_id!==undefined)throw new Error("Server audio is cached for this chapter.");recordings.set(key(n,c),blob);manifests.set(key(n,c),manifest);});
  vi.mocked(chapterAudioJobStore.remove).mockImplementation(async(n,c,guard,lease)=>{if(lease && leases.get(key(n,c))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())throw new DOMException("stale","AbortError");jobs.delete(key(n,c));parts.delete(key(n,c));});
  vi.mocked(chapterAudioStore.removeBrowser).mockImplementation(async(n,c,guard,lease)=>{if(lease && leases.get(key(n,c))?.token!==lease.token)throw new Error("Lease lost");if(guard && !guard())throw new DOMException("stale","AbortError");if(manifests.get(key(n,c))?.job_id===undefined){recordings.delete(key(n,c));manifests.delete(key(n,c));}});
  vi.mocked(ttsService.synthesize).mockResolvedValue(new Blob(["segment"]));
  vi.mocked(mergeAudioSegments).mockImplementation(async(segments,onDurations)=>{onDurations?.(segments.map(()=>1.25));return new Blob(["canonical WAV"]);});
  queue=new BrowserAudioQueue();
});
afterEach(()=>{queue.dispose();activateAccountStorage(null);});
describe("explicit browser chapter narration queue",()=>{
  it("uses rich blocks, measured durations and UTF16 offsets without persisting provider keys",async()=>{
    queue.enqueue(input());await idle();
    expect(chapterService.getChapterContentByNumber).toHaveBeenCalledWith(1,1,2,identityFor(1));
    expect(vi.mocked(ttsService.synthesize).mock.calls.map(call=>call[0])).toEqual(["Title","😀 First story passage.","Last story passage."]);
    expect(row()).toMatchObject({status:"ready",completedParts:3,totalParts:3,sourceVersion:"source-a"});
    const manifest=manifests.get(key(2,1))!;
    expect(manifest).toMatchObject({source_version:"source-a",include_author_notes:false,duration_seconds:3.75});
    expect(manifest?.segments[1]).toMatchObject({block_id:"first",text_offset:0,text_length:document.blocks[0].text.length,start_seconds:1.25,end_seconds:2.5});
    expect(manifest?.job_id).toBeUndefined();expect(parts.has(key(2,1))).toBe(false);
    expect(JSON.stringify([...jobs.values()])).not.toContain("private-key");expect(JSON.stringify(queue.getSnapshot())).not.toContain("private-key");
    expect(vi.mocked(chapterAudioStore.saveBrowser).mock.calls[0][4]).toEqual(expect.any(Function));
  });
  it("includes author notes only after explicit selection",async()=>{
    queue.enqueue({...input(),includeAuthorNotes:true});await idle();
    expect(vi.mocked(ttsService.synthesize).mock.calls.map(call=>call[0])).toContain("An author note.");expect(manifests.get(key(2,1))?.include_author_notes).toBe(true);
  });
  it("runs chapters sequentially and reports unavailable items without downloading them",async()=>{
    const first=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(first.promise);
    vi.mocked(chapterService.getChapterContentByNumber).mockImplementation(async(number)=>number===3?{...identityFor(number),source_version:document.content_version,current_content_version:document.content_version,id:11,novel_id:2,chapter_number:3,title:"Unavailable",content:"",document:undefined}:{...identityFor(number),source_version:document.content_version,current_content_version:document.content_version,id:8+number,novel_id:2,chapter_number:number,title:`Chapter ${number}`,content:document.plain_text,document});
    queue.enqueue({...input(),chapterNumbers:[1,2,3]});await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));
    expect(chapterService.getChapterContentByNumber).toHaveBeenCalledTimes(1);
    first.resolve(new Blob(["first"]));await idle();
    expect(queue.getSnapshot().rows.map(r=>r.status)).toEqual(["ready","ready","failed"]);expect(queue.getSnapshot().rows[2].error).toContain("Download this chapter");
  });
  it("resumes committed segments after failure without regenerating them",async()=>{
    vi.mocked(ttsService.synthesize).mockResolvedValueOnce(new Blob(["title"])).mockRejectedValueOnce(new Error("Provider unavailable"));
    queue.enqueue(input());await idle();expect(row()).toMatchObject({status:"failed",completedParts:1});expect(parts.get(key(2,1))).toHaveLength(1);
    queue.retry(input());await idle();expect(row().status).toBe("ready");
    expect(vi.mocked(ttsService.synthesize).mock.calls.filter(call=>call[0]==="Title")).toHaveLength(1);expect(ttsService.synthesize).toHaveBeenCalledTimes(4);
  });
  it("cancels promptly, retains completed parts and discards a late provider result",async()=>{
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockResolvedValueOnce(new Blob(["title"])).mockReturnValueOnce(pending.promise);
    queue.enqueue(input());await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(2));
    queue.cancel(2,1);await waitFor(()=>expect(jobs.get(key(2,1))?.status).toBe("cancelled"));
    pending.resolve(new Blob(["late"]));await Promise.resolve();expect(parts.get(key(2,1))).toHaveLength(1);expect(recordings.size).toBe(0);
    queue.retry(input());await idle();expect(row().status).toBe("ready");expect(vi.mocked(ttsService.synthesize).mock.calls.filter(call=>call[0]==="Title")).toHaveLength(1);
  });
  it("aborts on account switch and never writes the old result into either account",async()=>{
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);
    queue.enqueue(input());await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));const signal=vi.mocked(ttsService.synthesize).mock.calls[0][2]!;
    selectAccount(2);expect(signal.aborted).toBe(true);expect(queue.getSnapshot().rows).toEqual([]);
    queue.enqueue(input());await idle();expect(row().status).toBe("ready");pending.resolve(new Blob(["other account"]));await Promise.resolve();
    expect([...recordings.keys()]).toEqual(["2:2:1"]);expect(parts.has("1:2:1")).toBe(false);
  });
  it("hydrates a persisted failed job without silently starting it",async()=>{
    vi.mocked(ttsService.synthesize).mockRejectedValueOnce(new Error("offline"));queue.enqueue(input());await idle();const count=vi.mocked(ttsService.synthesize).mock.calls.length;
    queue.dispose();queue=new BrowserAudioQueue();await queue.hydrate(2,1,[1]);expect(row().status).toBe("failed");expect(ttsService.synthesize).toHaveBeenCalledTimes(count);
  });
  it("rejects changed sources, voices and note settings while preserving partial audio",async()=>{
    vi.mocked(ttsService.synthesize).mockResolvedValueOnce(new Blob(["title"])).mockRejectedValueOnce(new Error("offline"));queue.enqueue(input());await idle();const original=structuredClone(jobs.get(key(2,1))!);
    queue.retry({...input(),provider:{...input().provider,voice:"different"}});await idle();expect(row().error).toContain("another text version, voice");expect(jobs.get(key(2,1))).toEqual(original);expect(parts.get(key(2,1))).toHaveLength(1);
    queue.retry({...input(),includeAuthorNotes:true});await idle();expect(row().status).toBe("failed");
    vi.mocked(chapterService.getChapterContentByNumber).mockResolvedValue({...identityFor(1),source_version:document.content_version,current_content_version:document.content_version,id:9,novel_id:2,chapter_number:1,title:"Revised",content:document.plain_text,document:{...document,content_version:"source-b"}});queue.retry(input());await idle();expect(row().status).toBe("failed");expect(ttsService.synthesize).toHaveBeenCalledTimes(2);
  });
  it("preserves cached server audio instead of mixing or overwriting it",async()=>{
    recordings.set(key(2,1),new Blob(["server"]));manifests.set(key(2,1),{job_id:99} as AudioManifest);queue.enqueue(input());await idle();
    expect(row().status).toBe("failed");expect(row().error).toContain("server audio");expect(ttsService.synthesize).not.toHaveBeenCalled();expect(manifests.get(key(2,1))?.job_id).toBe(99);
  });
  it("rejects oversized spoken expansion before provider calls or persisted jobs",async()=>{
    const text="x".repeat(12501),large={...document,plain_text:text,blocks:[{id:"large",kind:"p" as const,html:`<p>${text}</p>`,text}]},before=JSON.stringify(large);
    vi.mocked(chapterService.getChapterContentByNumber).mockResolvedValue({...identityFor(1),source_version:document.content_version,current_content_version:document.content_version,id:9,novel_id:2,chapter_number:1,title:"",document:large,content:text});
    queue.enqueue({...input(),pronunciation:{version:"expansion",rules:[{source:"x",spoken:"y".repeat(160)}]}});await idle();
    expect(row()).toMatchObject({status:"failed",error:expect.stringContaining("Shorten or disable")});
    expect(ttsService.synthesize).not.toHaveBeenCalled();expect(chapterAudioJobStore.save).not.toHaveBeenCalled();expect(chapterAudioJobStore.saveSegment).not.toHaveBeenCalled();expect(chapterAudioStore.saveBrowser).not.toHaveBeenCalled();
    expect(JSON.stringify(large)).toBe(before);
  });
  it("bounds batches, suppresses active duplicates and rejects URL credentials",async()=>{
    expect(()=>queue.enqueue({...input(),chapterNumbers:Array.from({length:201},(_,i)=>i+1)})).toThrow(/200/);
    expect(()=>queue.enqueue({...input(),provider:{...input().provider,baseUrl:"http://user:secret@localhost/v1"}})).toThrow(/embedded credentials/);
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);expect(queue.enqueue({...input(),chapterNumbers:[1,1]})).toBe(1);expect(queue.enqueue(input())).toBe(0);
    queue.cancel(2);await idle();pending.resolve(new Blob(["discarded"]));
  });
  it("reuses verified ready recordings and recreates explicitly requested evicted audio",async()=>{
    queue.enqueue(input());await idle();queue.dispose();queue=new BrowserAudioQueue();await queue.hydrate(2,1,[1]);expect(row().status).toBe("ready");
    queue.enqueue(input());await idle();expect(ttsService.synthesize).toHaveBeenCalledTimes(3);
    recordings.clear();manifests.clear();await queue.hydrate(2,1,[1]);expect(row().status).toBe("failed");queue.retry(input());await idle();expect(row().status).toBe("ready");expect(ttsService.synthesize).toHaveBeenCalledTimes(6);
  });
  it("removes a paused browser job safely and cannot resurrect its late result",async()=>{
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);
    queue.enqueue(input());await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));
    const removing=queue.remove(2,1);
    expect(()=>queue.enqueue(input())).toThrow(/finish being removed/);
    await removing;
    pending.resolve(new Blob(["late"]));await Promise.resolve();expect(jobs.size).toBe(0);expect(parts.size).toBe(0);expect(recordings.size).toBe(0);expect(queue.getSnapshot().rows).toEqual([]);
    queue.enqueue({...input(),provider:{...input().provider,voice:"new narrator"}});await idle();expect(row().status).toBe("ready");
  });
  it("removes a queued chapter without waiting for another chapter's provider request",async()=>{
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);
    queue.enqueue({...input(),chapterNumbers:[1,2]});await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));
    await queue.remove(2,2);expect(queue.getSnapshot().rows.map(r=>r.chapterNumber)).toEqual([1]);
    pending.resolve(new Blob(["first"]));await idle();expect(chapterService.getChapterContentByNumber).toHaveBeenCalledTimes(1);
  });
  it("removes browser progress while preserving a server recording that later replaced its cache",async()=>{
    queue.enqueue(input());await idle();manifests.set(key(2,1),{job_id:99,source_version:"source-a"} as AudioManifest);recordings.set(key(2,1),new Blob(["server"]));
    await queue.hydrate(2,1,[1]);expect(row().status).toBe("failed");expect(row().error).toContain("server audio");
    await queue.remove(2,1);expect(jobs.size).toBe(0);expect(manifests.get(key(2,1))?.job_id).toBe(99);expect(recordings.size).toBe(1);
  });
  it("does not overwrite server audio cached while browser synthesis was in progress",async()=>{
    const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);queue.enqueue(input());
    await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));manifests.set(key(2,1),{job_id:99} as AudioManifest);recordings.set(key(2,1),new Blob(["server"]));
    pending.resolve(new Blob(["part"]));await idle();expect(row().status).toBe("failed");expect(manifests.get(key(2,1))?.job_id).toBe(99);
  });
  it("excludes another tab controller and blocks its removal while the first owns the chapter lock",async()=>{
    const held=new Set<string>();
    const request=vi.fn(async(name:string,_options:unknown,run:(lock:object|null)=>Promise<unknown>)=>{
      if(held.has(name))return run(null);
      held.add(name);try{return await run({name});}finally{held.delete(name);}
    });
    vi.stubGlobal("navigator",{locks:{request}});
    const other=new BrowserAudioQueue();
    try{
      const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);queue.enqueue(input());await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));
      const writes=vi.mocked(chapterAudioJobStore.save).mock.calls.length;
      other.enqueue(input());await waitFor(()=>expect(other.getSnapshot().rows[0]?.status).toBe("failed"));
      expect(other.getSnapshot().rows[0].error).toContain("another browser tab");expect(chapterAudioJobStore.save).toHaveBeenCalledTimes(writes);
      await expect(other.remove(2,1)).rejects.toThrow(/another browser tab/);
      pending.resolve(new Blob(["part"]));await idle();expect(row().status).toBe("ready");
      await other.remove(2,1);expect(jobs.size).toBe(0);
    }finally{other.dispose();vi.unstubAllGlobals();}
  });

  it("claims IndexedDB ownership without Web Locks and renews it during a pending provider call",async()=>{
    vi.stubGlobal("navigator",{});
    let heartbeat:(()=>void)|undefined;
    const original=window.setInterval.bind(window);
    const timer=vi.spyOn(window,"setInterval").mockImplementation(((handler:TimerHandler,timeout?:number,...args:unknown[])=>{
      if(timeout===20000 && typeof handler==="function")heartbeat=handler as ()=>void;
      return original(handler,timeout,...args);
    }) as typeof window.setInterval);
    try{
      const pending=deferred<Blob>();vi.mocked(ttsService.synthesize).mockReturnValueOnce(pending.promise);
      queue.enqueue(input());await waitFor(()=>expect(ttsService.synthesize).toHaveBeenCalledTimes(1));
      expect(browserAudioLeaseStore.claim).toHaveBeenCalled();expect(heartbeat).toBeTypeOf("function");
      heartbeat!();await waitFor(()=>expect(browserAudioLeaseStore.renew).toHaveBeenCalledTimes(1));
      const token=leases.get(key(2,1))?.token;
      leases.set(key(2,1),{...leases.get(key(2,1))!,token:"successor"});
      heartbeat!();await waitFor(()=>expect(row().status).toBe("failed"));
      expect(row().error).toContain("Another tab");pending.resolve(new Blob(["late"]));await Promise.resolve();
      expect(recordings.size).toBe(0);expect(leases.get(key(2,1))?.token).toBe("successor");expect(token).not.toBe("successor");
    }finally{timer.mockRestore();vi.unstubAllGlobals();}
  });

  it("snapshots pronunciation changes without modifying original anchors or ready recordings",async()=>{
    const pronunciation={version:"pronunciation-a",rules:[{source:"First",spoken:"FERST"}]};
    queue.enqueue({...input(),pronunciation});await idle();
    expect(vi.mocked(ttsService.synthesize).mock.calls[1][0]).toBe("😀 FERST story passage.");
    expect(jobs.get(key(2,1))?.pronunciation_version).toBe("pronunciation-a");
    const manifest=structuredClone(manifests.get(key(2,1))!);
    expect(manifest?.pronunciation_version).toBe("pronunciation-a");expect(manifest?.segments[1].text_length).toBe(document.blocks[0].text.length);
    const count=vi.mocked(ttsService.synthesize).mock.calls.length;
    queue.enqueue({...input(),pronunciation:{version:"pronunciation-b",rules:[{source:"First",spoken:"other"}]}});await idle();
    expect(row().error).toContain("pronunciation");expect(ttsService.synthesize).toHaveBeenCalledTimes(count);expect(manifests.get(key(2,1))).toEqual(manifest);
    expect(document.blocks[0].text).toBe("😀 First story passage.");
  });
  it("resumes partial pronunciation snapshots only with their original rules and version",async()=>{
    const pronunciation={version:"pronunciation-a",rules:[{source:"First",spoken:"FERST"}]};
    vi.mocked(ttsService.synthesize).mockResolvedValueOnce(new Blob(["title"])).mockRejectedValueOnce(new Error("offline"));
    queue.enqueue({...input(),pronunciation});await idle();expect(parts.get(key(2,1))).toHaveLength(1);
    queue.retry({...input(),pronunciation:{version:"pronunciation-b",rules:pronunciation.rules}});await idle();expect(row().status).toBe("failed");expect(ttsService.synthesize).toHaveBeenCalledTimes(2);
    queue.retry({...input(),pronunciation});await idle();expect(row().status).toBe("ready");expect(ttsService.synthesize).toHaveBeenCalledTimes(4);
  });

});
