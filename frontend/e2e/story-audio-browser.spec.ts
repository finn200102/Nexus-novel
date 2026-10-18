import { createHash } from "node:crypto";
import { test, expect } from "./fixtures";

const novelId=95;
const docs=[1,2].map(number=>{
  const text=`Chapter ${number} prose. The keeper arrives at the harbour.`;
  const html=`<p>${text}</p>`;
  return {schema_version:1,source_format:"html",content_version:createHash("sha256").update(html).digest("hex"),plain_text:text,blocks:[{id:`b-${createHash("sha256").update(html).digest("hex").slice(0,24)}-0`,kind:"p",text,html}]};
});
function wave(){
  const body=Buffer.alloc(44+24000*2);body.write("RIFF");body.writeUInt32LE(body.length-8,4);body.write("WAVEfmt ",8);
  body.writeUInt32LE(16,16);body.writeUInt16LE(1,20);body.writeUInt16LE(1,22);body.writeUInt32LE(24000,24);
  body.writeUInt32LE(48000,28);body.writeUInt16LE(2,32);body.writeUInt16LE(16,34);body.write("data",36);body.writeUInt32LE(body.length-44,40);return body;
}

for(const pronunciation of [false,true]) {
const pronunciationRules=pronunciation?[{source:"keeper",spoken:"KEEP er"}]:[];
const pronunciationVersion=pronunciation?createHash("sha256").update(JSON.stringify({pipeline:"literal-pronunciation-v1",rules:pronunciationRules})).digest("hex"):null;
test(pronunciation?"saved pronunciations change only spoken browser audio while preserving original passage links":"browser narration prepares several chapters beyond its panel and keeps private aligned audio",async({signedInPage:page})=>{
  test.setTimeout(90_000);
  let release!:()=>void;
  const firstRequest=new Promise<void>(resolve=>{release=resolve;});
  let requested=0,serverCreates=0;
  const spokenRequests:string[]=[];
  const chapters=docs.map((doc,index)=>({id:9501+index,chapter_number:index+1,title:`Chapter ${index+1}`,content_status:"PRESENT",downloaded:true,source_version:doc.content_version,latest_job:null}));
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,"");
    if(path===`/novel/${novelId}`)return route.fulfill({json:{id:novelId,library_id:1,title:"Browser audio queue",author:"Fixture",metadata_id:null,url:"nexus-local:audio-queue",novel_site:"local",chapter_count:2,num_chapters:2,scrape_status:"completed"}});
    if(path===`/chapter/${novelId}`)return route.fulfill({json:chapters});
    if(path===`/chapter/annotations/${novelId}`)return route.fulfill({json:[]});
    if(path===`/chapter/progress/${novelId}`)return route.fulfill({json:null});
    const content=path.match(new RegExp(`^/chapter/content/library/1/${novelId}/([12])$`));
    if(content){const number=Number(content[1]);return route.fulfill({json:{...chapters[number-1],novel_id:novelId,content:docs[number-1].plain_text,document:docs[number-1]}});}
    if(path===`/audio/pronunciation/stories/${novelId}`)return route.fulfill({json:{scope:`pronunciation:${novelId}`,revision:pronunciation?1:0,rules:pronunciationRules,account_rules:[],inherit_account:true,effective_rules:pronunciationRules,effective_version:pronunciationVersion}});
    if(path===`/audio/stories/${novelId}`)return route.fulfill({json:{novel_id:novelId,total:2,offset:0,limit:50,summary:{chapters:2,downloaded:2,ready:0,queued:0,needs_retry:0},chapters}});
    if(path===`/audio/stories/${novelId}/jobs`){serverCreates++;return route.fulfill({status:400,json:{detail:"Browser audio must not be sent here"}});}
    if(path==="/audio/voices/default")return route.fulfill({json:{voice_profile_id:null,revision:0}});
    if(path==="/audio/voices"||path==="/audio/jobs")return route.fulfill({json:[]});
    return route.fallback();
  });
  await page.route("http://127.0.0.1:18980/v1/audio/speech",async route=>{
    const headers={"access-control-allow-origin":"*","access-control-allow-headers":"authorization,content-type","access-control-allow-methods":"POST,OPTIONS"};
    if(route.request().method()==="OPTIONS")return route.fulfill({status:204,headers});
    requested++;spokenRequests.push(route.request().postDataJSON().input);
    expect(route.request().headers().authorization).toBe("Bearer fixture-browser-key");
    if(requested===1)await firstRequest;
    return route.fulfill({contentType:"audio/wav",headers,body:wave()});
  });
  await page.goto(`/library/1/novels/${novelId}?tab=audio`);
  const audio=page.getByRole("region",{name:"Story audio",exact:true});
  await audio.getByRole("combobox",{name:"Voice provider",exact:true}).selectOption("custom");
  await audio.getByRole("combobox",{name:"Generate audio",exact:true}).selectOption("browser");
  await audio.getByLabel("API base URL",{exact:true}).fill("http://127.0.0.1:18980/v1");
  await audio.getByLabel("API key",{exact:true}).fill("fixture-browser-key");
  await audio.getByLabel("Model",{exact:true}).fill("fixture");
  await audio.getByLabel("Voice",{exact:true}).fill("fixture");
  await audio.getByLabel("Through chapter",{exact:true}).fill("2");
  await audio.getByRole("button",{name:"Add chapter range",exact:true}).click();
  await audio.getByRole("button",{name:"Create selected audio",exact:true}).click();
  await expect.poll(()=>requested).toBe(1);
  await page.getByRole("tab",{name:"About",exact:true}).click();
  release();
  await expect.poll(()=>requested,{timeout:20_000}).toBe(4).catch(async error=>{
    await page.getByRole("tab",{name:"Audio",exact:true}).click();
    throw new Error(`${String(error)}\nQueue state: ${await audio.innerText()}`);
  });
  await page.getByRole("tab",{name:"Audio",exact:true}).click();
  await expect(audio.getByRole("button",{name:"Listen to local chapter 1",exact:true})).toBeVisible();
  await expect(audio.getByRole("button",{name:"Listen to local chapter 2",exact:true})).toBeVisible();
  expect(serverCreates).toBe(0);
  expect(spokenRequests.some(value=>value.includes(pronunciation?"KEEP er":"keeper"))).toBe(true);
  if(pronunciation)expect(spokenRequests.some(value=>value.includes("keeper"))).toBe(false);
  await page.reload();
  await expect(audio.getByRole("button",{name:"Listen to local chapter 2",exact:true})).toBeVisible();
  const persisted=await page.evaluate(async()=>{
    const name=(await indexedDB.databases()).find(row=>row.name?.endsWith(":7:reader-db"))?.name;
    if(!name)throw new Error("Account audio database missing");
    const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(name);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
    try{return await new Promise<string>((resolve,reject)=>{const request=db.transaction("chapter_audio_jobs","readonly").objectStore("chapter_audio_jobs").getAll();request.onsuccess=()=>resolve(JSON.stringify(request.result));request.onerror=()=>reject(request.error);});}finally{db.close();}
  });
  expect(persisted).not.toContain("fixture-browser-key");
  if(pronunciation)expect(persisted).toContain(pronunciationVersion);
  await audio.getByRole("link",{name:"Open chapter 1",exact:true}).click();
  await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy","false");
  await expect(page.locator(`[data-block-id="${docs[0].blocks[0].id}"]`)).toHaveText(docs[0].plain_text);
  await page.getByRole("button",{name:"Listen",exact:true}).click();
  await page.getByRole("button",{name:"Play",exact:true}).click();
  await expect(page.getByRole("button",{name:"Pause",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Listen from this passage",exact:true}).click();
  await expect(page.getByRole("button",{name:"Read this passage",exact:true})).toBeEnabled();
  expect(serverCreates).toBe(0);
});

}
