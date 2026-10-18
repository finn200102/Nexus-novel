import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import type { BrowserAudioQueue } from "../src/services/browserAudioQueue";
import { test, expect } from "./fixtures";
import { authUser, installMockApi } from "./mockApi";

type LeaseWindow=Window & {leaseTestQueue:BrowserAudioQueue};
const novelId=96;
const text="The keeper reached the harbour before sunrise.";
const html=`<p>${text}</p>`;
const document={schema_version:1,source_format:"html",content_version:createHash("sha256").update(html).digest("hex"),plain_text:text,blocks:[{id:"harbour",kind:"p",text,html}]};
function wave(){
  const body=Buffer.alloc(44+24000*2);body.write("RIFF");body.writeUInt32LE(body.length-8,4);body.write("WAVEfmt ",8);body.writeUInt32LE(16,16);body.writeUInt16LE(1,20);body.writeUInt16LE(1,22);body.writeUInt32LE(24000,24);body.writeUInt32LE(48000,28);body.writeUInt16LE(2,32);body.writeUInt16LE(16,34);body.write("data",36);body.writeUInt32LE(body.length-44,40);return body;
}
async function attach(page:Page){
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,"");
    if(path===`/chapter/content/library/1/${novelId}/1`)return route.fulfill({json:{id:9601,novel_id:novelId,chapter_number:1,title:"Arrival",content:text,document}});
    return route.fallback();
  });
  await page.evaluate(async()=>{
    Object.defineProperty(navigator,"locks",{value:undefined,configurable:true});
    Object.defineProperty(crypto,"randomUUID",{value:undefined,configurable:true});
    const module=await import("/src/services/browserAudioQueue.ts");
    (window as LeaseWindow).leaseTestQueue=module.browserAudioQueue;
  });
}
async function enqueue(page:Page){
  return page.evaluate(novelId=>(window as LeaseWindow).leaseTestQueue.enqueue({libraryId:1,novelId,chapterNumbers:[1],presetId:"custom",provider:{baseUrl:"http://127.0.0.1:18981/v1",model:"synthetic-fixture",voice:"fixture",apiKey:"lease-private-fixture-key"}}),novelId);
}
async function row(page:Page){return page.evaluate(()=>(window as LeaseWindow).leaseTestQueue.getSnapshot().rows[0] || null);}
async function state(page:Page,expire=false){
  return page.evaluate(async({novelId,expire})=>{
    const storage=await import("/src/services/accountStorage.ts");
    const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(storage.accountDatabaseName());request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
    try{return await new Promise<{job:unknown;lease:unknown;audioBytes:number;manifest:unknown;parts:number;serialized:string}>((resolve,reject)=>{
      const tx=db.transaction(["chapter_audio_jobs","chapter_audio","chapter_audio_segments"],expire?"readwrite":"readonly");
      const jobs=tx.objectStore("chapter_audio_jobs"),leaseRequest=jobs.get(`lease:${novelId}:1`),jobRequest=jobs.get(`${novelId}:1`),audioRequest=tx.objectStore("chapter_audio").get(`${novelId}:1`),partsRequest=tx.objectStore("chapter_audio_segments").index("cache_key").count(`${novelId}:1`);
      leaseRequest.onsuccess=()=>{if(expire && leaseRequest.result)jobs.put({...leaseRequest.result,expiresAt:Date.now()-1});};
      tx.oncomplete=()=>resolve({job:jobRequest.result,lease:leaseRequest.result,audioBytes:audioRequest.result?.audio_data?.byteLength || 0,manifest:audioRequest.result?.manifest,parts:partsRequest.result,serialized:JSON.stringify([jobRequest.result,leaseRequest.result])});
      tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
    });}finally{db.close();}
  },{novelId,expire});
}

test("LAN HTTP fallback atomically excludes a second tab and fences an expired predecessor",async({signedInPage:first,context})=>{
  test.setTimeout(60_000);
  let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});
  let firstRequests=0,secondRequests=0;
  const second=await context.newPage();
  await installMockApi(second,{admin:true});
  await second.goto("/login");await second.getByLabel(/username/i).fill(authUser.username);await second.getByLabel(/password/i).fill(authUser.password);await second.getByRole("button",{name:/login|sign in/i}).click();await expect(second).not.toHaveURL(/login/);
  const routeProvider=async(page:Page,predecessor:boolean)=>page.route("http://127.0.0.1:18981/v1/audio/speech",async route=>{
    const headers={"access-control-allow-origin":"*","access-control-allow-headers":"authorization,content-type","access-control-allow-methods":"POST,OPTIONS"};
    if(route.request().method()==="OPTIONS")return route.fulfill({status:204,headers});
    expect(route.request().headers().authorization).toBe("Bearer lease-private-fixture-key");
    if(predecessor){firstRequests++;if(firstRequests===2)await held;}else secondRequests++;
    await route.fulfill({contentType:"audio/wav",body:wave(),headers}).catch(()=>undefined);
  });
  await routeProvider(first,true);await routeProvider(second,false);await attach(first);await attach(second);
  try{
    expect(await first.evaluate(()=>navigator.locks)).toBeUndefined();expect(await first.evaluate(()=>crypto.randomUUID)).toBeUndefined();expect(await second.evaluate(()=>navigator.locks)).toBeUndefined();
    await enqueue(first);await expect.poll(()=>firstRequests).toBe(2);
    await enqueue(second);await expect.poll(async()=>(await row(second))?.status).toBe("failed");
    expect((await row(second))?.error).toContain("another browser tab");expect(secondRequests).toBe(0);
    const removalError=await second.evaluate(async novelId=>{try{await(window as LeaseWindow).leaseTestQueue.remove(novelId,1);return "removed";}catch(error){return String(error);}},novelId);
    expect(removalError).toContain("another browser tab");
    const before=await state(first);expect(before.job).toMatchObject({status:"generating",completed_chunks:1});expect(before.parts).toBe(1);
    // Simulate a suspended/crashed predecessor's expired heartbeat. Only this
    // test-owned chapter lease is edited; production timers remain unchanged.
    await state(second,true);
    await enqueue(second);await expect.poll(async()=>(await row(second))?.status,{timeout:15000}).toBe("ready");
    expect(secondRequests).toBe(1);
    const completed=await state(second);expect(completed.job).toMatchObject({status:"ready",completed_chunks:2});expect(completed.audioBytes).toBeGreaterThan(44);expect(completed.manifest).toMatchObject({source_version:document.content_version,precision:"segment",duration_seconds:2});expect(completed.parts).toBe(0);
    release();await expect.poll(async()=>(await row(first))?.status).toBe("failed");
    const after=await state(first);expect(after.job).toMatchObject({status:"ready",completed_chunks:2});expect(after.manifest).toEqual(completed.manifest);expect(after.audioBytes).toBe(completed.audioBytes);expect(after.parts).toBe(0);expect(after.serialized).not.toContain("lease-private-fixture-key");expect(firstRequests).toBe(2);
  }finally{release();await second.close();}
});
