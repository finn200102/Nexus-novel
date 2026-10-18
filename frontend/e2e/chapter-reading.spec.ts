import {mkdir,writeFile} from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type {Page} from "@playwright/test";
import {test,expect} from "./fixtures";
import type {ChapterReadingItem,ChapterReadingSummary} from "../src/services/chapterService";
async function fixture(page:Page,options:{current?:number;finished?:boolean;emptyRecords?:boolean}={}){
 let current=options.current??7;const queries:{offset:number;q:string;scope:string}[]=[];
 const numbers=[-2,0,7,...Array.from({length:1997},(_,index)=>index+11),20007];
 const rows:ChapterReadingItem[]=numbers.map((chapter_number,index)=>({id:index+1,novel_id:11,chapter_number,title:index===2000?"Last indexed chapter beyond the first thousand":"Chapter fixture part "+chapter_number,category:"story",content_status:"PRESENT",audio_status:"MISSING",created_at:"2026-10-16T00:00:00Z",updated_at:"2026-10-16T00:00:00Z",ordinal:index+1,followed_ordinal:index+1,followed:true,completed_checkpoint:!options.emptyRecords&&index===0,max_percent:!options.emptyRecords&&index===0?100:chapter_number===current?40:null}));
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
  const url=new URL(route.request().url()),endpoint=url.pathname.replace(/^\/api(?=\/)/,"");
  if(endpoint==="/chapter/reading-summary/11"){
   const index=numbers.indexOf(current);const result:ChapterReadingSummary={novel_id:11,reading_run_key:null,revision:2,total_chapters:rows.length,followed_total:rows.length,completed_chapters:options.emptyRecords?0:1,followed_completed_chapters:options.emptyRecords?0:1,completion_basis:"recorded_checkpoints",completed_reading:!!options.finished,current:{chapter_id:index+1,chapter_number:current,ordinal:index+1,followed_ordinal:index+1,percent:40},next_unread_chapter_id:index+1,next_unread_chapter_number:current,categories:["story"],categories_truncated:false};return route.fulfill({json:result});
  }
  if(endpoint==="/chapter/reading-chapters/11"){
   const offset=Number(url.searchParams.get("offset")||0),limit=Number(url.searchParams.get("limit")||100),q=url.searchParams.get("q")||"",scope=url.searchParams.get("category_scope")||"all";queries.push({offset,q,scope});const filtered=rows.filter(row=>!q||String(row.chapter_number).includes(q)||row.title?.includes(q));return route.fulfill({json:{novel_id:11,reading_run_key:null,revision:2,total:filtered.length,offset,limit,items:filtered.slice(offset,offset+limit)}});
  }
  if(endpoint==="/chapter/novel/11/download-status")return route.fulfill({json:{total:rows.length,present:rows.length,missing:0,failed:0,processing:0,processing_chapters:[],failed_chapters:[]}});
  if(endpoint==="/chapter/progress/11")return route.fulfill({json:{chapter_number:current,position:0,percent:40,revision:2,reading_run_key:null}});
  return route.fallback();
 });
 return{queries,setCurrent:(value:number)=>{current=value;}};
}
async function open(page:Page){await page.goto("/story/4?copy=11");await expect(page.getByRole("heading",{name:"The Quiet Ledger",exact:true})).toBeVisible();}
test("source chapter labels, ordinals and completed records stay distinct across server pages beyond1000",async({signedInPage:page},testInfo)=>{
 const data=await fixture(page);await open(page);await expect(page.getByText("Current place: Chapter 7 · 3 of 2001 in story · 40%",{exact:true})).toBeVisible();await expect(page.getByRole("progressbar",{name:"Recorded completed chapters",exact:true})).toHaveAttribute("aria-valuenow","1");await expect(page.getByText("2,001 chapters",{exact:true})).toBeVisible();
 await page.getByRole("tab",{name:"Chapters",exact:true}).click();await expect(page.getByText("1–100 of 2001 matching chapters",{exact:true})).toBeVisible();await expect(page.getByText("1 of 2001 completed chapters recorded · 2001 downloaded on the server · 0 saved offline",{exact:true})).toBeVisible();
 const zero=page.locator('[data-chapter="0"]');await expect(zero.getByRole("img",{name:"No completed chapter record",exact:true})).toBeVisible();await expect(page.getByRole("img",{name:"Completed chapter recorded",exact:true})).toHaveCount(1);
 await page.getByRole("button",{name:"Next chapters",exact:true}).click();await expect(page.getByText("101–200 of 2001 matching chapters",{exact:true})).toBeVisible();expect(data.queries[data.queries.length-1]).toEqual({offset:100,q:"",scope:"followed"});
 await page.getByRole("searchbox",{name:"Find chapter",exact:true}).fill("20007");await expect(page.getByRole("link",{name:"Chapter 20007: Last indexed chapter beyond the first thousand",exact:true})).toBeVisible();await expect(page.getByText("1–1 of 1 matching chapters",{exact:true})).toBeVisible();expect(data.queries[data.queries.length-1]).toEqual({offset:0,q:"20007",scope:"all"});
 await mkdir("/tmp/nexus-chapter-reading-ui",{recursive:true});await page.screenshot({path:`/tmp/nexus-chapter-reading-ui/${testInfo.project.name}-desktop.png`});
});
test("chapter zero and negative prologues remain reading places without invented completion markers",async({signedInPage:page})=>{
 const data=await fixture(page,{current:0,finished:true,emptyRecords:true});await open(page);await expect(page.getByRole("link",{name:"Continue · Ch. 0",exact:true})).toHaveAttribute("href","/library/1/novels/11/0");await expect(page.getByText("Current place: Chapter 0 · 2 of 2001 in story · 40%",{exact:true})).toBeVisible();await expect(page.getByText("This reading is marked finished. Chapter records are shown separately.",{exact:true})).toBeVisible();await expect(page.getByRole("progressbar",{name:"Recorded completed chapters",exact:true})).toHaveAttribute("aria-valuenow","0");
 await page.getByRole("tab",{name:"Chapters",exact:true}).click();await expect(page.getByRole("link",{name:"Chapter 0: Chapter fixture part 0",exact:true})).toBeVisible();await expect(page.getByRole("img",{name:"Completed chapter recorded",exact:true})).toHaveCount(0);
 data.setCurrent(-2);await page.goto("/story/4?copy=11");await expect(page.getByRole("link",{name:"Continue · Ch. -2",exact:true})).toHaveAttribute("href","/library/1/novels/11/-2");await expect(page.getByText("Current place: Chapter -2 · 1 of 2001 in story · 40%",{exact:true})).toBeVisible();
});
test("phone chapter summaries and page controls fit and remain accessible",async({signedInPage:page},testInfo)=>{
 await fixture(page);await page.setViewportSize({width:390,height:844});await open(page);await page.getByRole("tab",{name:"Chapters",exact:true}).click();await expect(page.getByText("1–100 of 2001 matching chapters",{exact:true})).toBeVisible();await page.locator(".story-chapters__bar").scrollIntoViewIfNeeded();
 await page.evaluate(async()=>{await document.fonts.ready;await Promise.all(document.getAnimations().filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>undefined)));});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);const result=await new AxeBuilder({page}).analyze();await mkdir("/tmp/nexus-chapter-reading-ui",{recursive:true});await writeFile(`/tmp/nexus-chapter-reading-ui/${testInfo.project.name}-phone-axe.json`,JSON.stringify(result.violations,null,2));expect(result.violations).toEqual([]);await page.screenshot({path:`/tmp/nexus-chapter-reading-ui/${testInfo.project.name}-phone.png`});
});
