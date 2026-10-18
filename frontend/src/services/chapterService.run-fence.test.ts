import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import {beforeEach,describe,expect,it,vi} from "vitest";
import {waitFor} from "@testing-library/react";
import apiClient from "./apiClient";
import {chapterService,type CachedReadingProgress} from "./chapterService";
import {activateAccountStorage} from "./accountStorage";
import {enqueueProgress,getQueuedProgress,type QueuedProgress} from "./progressSyncQueue";
vi.mock("./apiClient",()=>({default:{get:vi.fn(),put:vi.fn()}}));
vi.mock("./serverReachability",()=>({markServerReachable:vi.fn(),markServerUnreachable:vi.fn()}));
vi.mock("./progressSyncQueue",async()=>({...await vi.importActual<typeof import("./progressSyncQueue")>("./progressSyncQueue"),installProgressSync:vi.fn(()=>()=>undefined)}));
const oldKey="00000000-0000-4000-8000-000000000001",newKey="00000000-0000-4000-8000-000000000002";
const snapshot=(key:string,revision:number,chapter=1):CachedReadingProgress=>({reading_run_key:key,revision,chapter_number:chapter,position:0,percent:0});
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return{promise,resolve};}
let novelId=7000;
const queued=(key:string,ts:number,blocked=false):QueuedProgress=>({chapterIdentity:identity(novelId,2),novelId,readingRunKey:key,chapter:2,position:42,percent:70,ts,blocked});
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();activateAccountStorage(1);novelId++;});
describe("reading run identity across concurrent progress requests",()=>{
  it("normalizes nullable wire snapshots without making up a reading position",()=>{
    chapterService.acceptReadingRun(novelId,{revision:1,reading_run_key:newKey,chapter_number:null,position:null,percent:null,text_offset:null});
    expect(chapterService.getCachedReadingProgress(novelId)).toEqual({revision:1,reading_run_key:newKey,chapter_number:null,position:0,percent:0});
  });
  it("captures the loaded run before serialized writes and never labels an old position with a new run",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(oldKey,1));
    const pending=deferred<{data:CachedReadingProgress}>();vi.mocked(apiClient.put).mockReturnValueOnce(pending.promise);
    const first=chapterService.updateReadingProgress(novelId,2,100,90);
    await waitFor(()=>expect(apiClient.put).toHaveBeenCalledTimes(1));
    const serialized=chapterService.updateReadingProgress(novelId,2,200,100);
    chapterService.acceptReadingRun(novelId,snapshot(newKey,3));pending.resolve({data:snapshot(oldKey,2,2)});
    await Promise.all([first,serialized]);
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiClient.put).mock.calls[0][1]).toMatchObject({reading_run_key:oldKey});
    expect(chapterService.getCachedReadingProgress(novelId)).toEqual(snapshot(newKey,3));
    expect(getQueuedProgress()).toEqual([expect.objectContaining({readingRunKey:oldKey,blocked:true,conflictCode:"reading_run_changed",position:100})]);
  });
  it("keeps a newer same-run PUT when an earlier GET returns late",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(oldKey,1));
    const get=deferred<{data:CachedReadingProgress}>();vi.mocked(apiClient.get).mockReturnValueOnce(get.promise);
    const loading=chapterService.getReadingProgress(novelId);
    vi.mocked(apiClient.put).mockResolvedValueOnce({data:snapshot(oldKey,2,2)});
    await chapterService.updateReadingProgress(novelId,2,20,50,{readingRunKey:oldKey});
    get.resolve({data:snapshot(oldKey,1)});
    expect(await loading).toEqual(snapshot(oldKey,2,2));
    expect(chapterService.getCachedReadingProgress(novelId)).toEqual(snapshot(oldKey,2,2));
  });
  it("rejects a delayed old-run GET and an old start receipt after a newer run was accepted",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(oldKey,1));
    const get=deferred<{data:CachedReadingProgress}>();vi.mocked(apiClient.get).mockReturnValueOnce(get.promise);
    const loading=chapterService.getReadingProgress(novelId).catch(error=>error);
    chapterService.acceptReadingRun(novelId,snapshot(newKey,3));get.resolve({data:snapshot(oldKey,1)});
    expect(await loading).toMatchObject({response:{status:409,data:{detail:{code:"reading_run_changed"}}}});
    expect(()=>chapterService.acceptReadingRun(novelId,snapshot(oldKey,2))).toThrow(/different reading session/);
    expect(chapterService.getCachedReadingProgress(novelId)).toEqual(snapshot(newKey,3));
  });
  it("cannot adopt an old operation's successful receipt or drop either run's newer queued position",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(oldKey,5));
    const pending=deferred<{data:CachedReadingProgress}>();vi.mocked(apiClient.put).mockReturnValueOnce(pending.promise);
    const saving=chapterService.updateReadingProgress(novelId,2,10,20,{readingRunKey:oldKey});
    await waitFor(()=>expect(apiClient.put).toHaveBeenCalledTimes(1));
    const oldPending=queued(oldKey,Date.now()+10000),newPending=queued(newKey,Date.now()+20000);
    enqueueProgress(oldPending);enqueueProgress(newPending);
    chapterService.acceptReadingRun(novelId,snapshot(newKey,7));pending.resolve({data:snapshot(oldKey,6,2)});
    expect(await saving).toBeNull();
    expect(chapterService.getCachedReadingProgress(novelId)).toEqual(snapshot(newKey,7));
    expect(getQueuedProgress()).toEqual([oldPending,newPending]);
  });
  it("saves the current run while retaining an older run's blocked position for export",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(newKey,5));
    const oldPending=queued(oldKey,1,true);enqueueProgress(oldPending);enqueueProgress(queued(newKey,2));
    vi.mocked(apiClient.put).mockResolvedValueOnce({data:snapshot(newKey,6,1)});
    await chapterService.updateReadingProgress(novelId,1,20,25,{readingRunKey:newKey});
    expect(apiClient.put).toHaveBeenCalledTimes(1);expect(getQueuedProgress()).toEqual([oldPending]);
    vi.mocked(apiClient.get).mockResolvedValueOnce({data:snapshot(newKey,6,1)});
    await expect(chapterService.resolveProgressConflict(novelId,"device")).rejects.toMatchObject({response:{status:409,data:{detail:{code:"reading_run_changed"}}}});
    expect(apiClient.put).toHaveBeenCalledTimes(1);expect(getQueuedProgress()).toEqual([oldPending]);
  });
  it("does not cache or enqueue an in-flight response in the next account",async()=>{
    chapterService.acceptReadingRun(novelId,snapshot(oldKey,1));
    const pending=deferred<{data:CachedReadingProgress}>();vi.mocked(apiClient.put).mockReturnValueOnce(pending.promise);
    const saving=chapterService.updateReadingProgress(novelId,1,10,20,{readingRunKey:oldKey});
    await waitFor(()=>expect(apiClient.put).toHaveBeenCalledTimes(1));
    activateAccountStorage(2);pending.resolve({data:snapshot(oldKey,2)});await saving;
    expect(chapterService.getCachedReadingProgress(novelId)).toBeNull();expect(getQueuedProgress()).toEqual([]);
    activateAccountStorage(1);expect(chapterService.getCachedReadingProgress(novelId)).toEqual(snapshot(oldKey,1));
  });
});
