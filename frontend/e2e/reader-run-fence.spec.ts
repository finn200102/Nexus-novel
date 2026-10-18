import {createHash} from "node:crypto";
import type {Route} from "@playwright/test";
import {test,expect} from "./fixtures";
const novelId=99,oldKey="11111111-1111-4111-8111-111111111111",newKey="22222222-2222-4222-8222-222222222222";
const documentFor=(number:number)=>{
  const texts=Array.from({length:35},(_,index)=>`Chapter ${number}, paragraph ${index+1}. Alice walks beside the harbour and remembers the story. `.repeat(3));
  const html=texts.map(text=>`<p>${text}</p>`).join("");
  return{schema_version:1,source_format:"html",content_version:createHash("sha256").update(html).digest("hex"),plain_text:texts.join("\n\n"),blocks:texts.map((text,index)=>({id:`chapter-${number}-block-${index}`,kind:"p",text,html:`<p>${text}</p>`}))};
};
for(const delay of ["progress","content"] as const)test(`an old reader load cannot adopt a restarted run while ${delay} is delayed`,async({signedInPage:page})=>{
  const documents=[documentFor(1),documentFor(2)];
  const old={novel_id:novelId,reading_run_key:oldKey,chapter_number:2,position:0,percent:100,revision:4,furthest_chapter_number:2,furthest_percent:100};
  let progress={...old},held=false,started=false;
  const saves:Record<string,unknown>[]=[];
  let release!:()=>void;const pending=new Promise<void>(done=>{release=done;});
  const handler=async(route:Route)=>{
    const request=route.request(),path=new URL(request.url()).pathname.replace(/^\/api(?=\/)/,"");
    if(path===`/novel/${novelId}`)return route.fulfill({json:{id:novelId,library_id:1,title:"Run fence fixture",author:"Fixture",metadata_id:null,url:"nexus-local:run-fence",novel_site:"local",chapter_count:2,num_chapters:2,scrape_status:"completed"}});
    if(path===`/chapter/${novelId}`)return route.fulfill({json:documents.map((_,index)=>({id:9901+index,novel_id:novelId,chapter_number:index+1,title:`Chapter ${index+1}`,content_status:"PRESENT"}))});
    if(path===`/chapter/annotations/${novelId}`)return route.fulfill({json:[]});
    if(path===`/chapter/progress/${novelId}`){
      if(request.method()==="GET"){
        const snapshot={...progress};if(delay==="progress"&&!started){held=true;await pending;}
        return route.fulfill({json:snapshot});
      }
      const body=request.postDataJSON();saves.push(body);
      if(body.reading_run_key!==progress.reading_run_key)return route.fulfill({status:409,json:{detail:{code:"reading_run_changed",current:progress}}});
      progress={...progress,...body,revision:progress.revision+1,furthest_chapter_number:Math.max(progress.furthest_chapter_number,body.chapter_number)};
      return route.fulfill({json:progress});
    }
    const content=path.match(new RegExp(`^/chapter/content/library/1/${novelId}/([12])$`));
    if(content){const number=Number(content[1]);if(delay==="content"&&number===2&&!started){held=true;await pending;}
      return route.fulfill({json:{id:9900+number,novel_id:novelId,chapter_number:number,title:`Chapter ${number}`,content_status:"PRESENT",content:documents[number-1].plain_text,document:documents[number-1]}});}
    if(path===`/reading/stories/${novelId}/runs/start`){
      const body=request.postDataJSON();expect(body.reading_run_key).toBe(oldKey);expect(body.expected_revision).toBe(4);
      started=true;progress={...old,reading_run_key:newKey,chapter_number:1,percent:0,position:0,revision:5,furthest_chapter_number:0,furthest_percent:0};
      return route.fulfill({json:{novel_id:novelId,current_run_key:newKey,revision:5,current_progress:progress,total:2,offset:0,limit:20,first_chapter_number:1,items:[]}});
    }
    if(path==="/audio/jobs")return route.fulfill({json:[]});
    return route.fallback();
  };
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,handler);
  await page.evaluate(async({id,snapshot})=>{const path="/src/services/chapterService.ts";(await import(path)).chapterService.acceptReadingRun(id,snapshot);},{id:novelId,snapshot:old});
  // Hold every pre-restart request, including StrictMode effect replays.
  await page.goto(`/library/1/novels/${novelId}/2`);
  await expect.poll(()=>held).toBe(true);
  const operator=await page.context().newPage();
  try{
    // A second same-origin tab performs the real client service request and
    // accepts its acknowledgement. Its storage write is shared with the Reader.
    await operator.route("**/run-fence-operator",route=>route.fulfill({contentType:"text/html",body:"<!doctype html><title>Run action fixture</title>"}));
    await operator.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,handler);
    await operator.goto("/run-fence-operator");
    await operator.evaluate(async({id,key})=>{
      const accountPath="/src/services/accountStorage.ts";(await import(accountPath)).activateAccountStorage(7);
      const journalPath="/src/services/readingJournalService.ts",chapterPath="/src/services/chapterService.ts";
      const state=await(await import(journalPath)).readingJournalService.change(id,"start",{expected_revision:4,reading_run_key:key,operation_id:"native-start-again"});
      (await import(chapterPath)).chapterService.acceptReadingRun(id,state.current_progress);
    },{id:novelId,key:oldKey});
    expect(started).toBe(true);release();await page.bringToFront();
    await expect(page.getByText(/A different reading session is active\. Your unsynchronized position/)).toBeVisible();
    await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy","false");
    await expect(page).toHaveURL(new RegExp(`/novels/${novelId}/2$`));
    await expect(page.getByRole("button",{name:"Keep this device’s position",exact:true})).toHaveCount(0);
    await page.locator(".reader__content").evaluate(element=>{element.scrollTop=element.scrollHeight/2;element.dispatchEvent(new Event("scroll"));});
    await page.waitForTimeout(700); // Existing progress debounce is 500ms.
    expect(saves.every(body=>body.reading_run_key!==newKey)).toBe(true);
    expect(progress.furthest_chapter_number).toBe(0);expect(progress.chapter_number).toBe(1);
    const cache=await page.evaluate(async id=>{const path="/src/services/chapterService.ts";return(await import(path)).chapterService.getCachedReadingProgress(id);},novelId);
    expect(cache?.reading_run_key).toBe(newKey);
    await page.getByRole("button",{name:"Discard this queued position and use the current reading session",exact:true}).click();
    await expect(page).toHaveURL(new RegExp(`/novels/${novelId}/1$`));
    await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy","false");
  }finally{release();await operator.close();}
});
