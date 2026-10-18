import {readFileSync} from "node:fs";
import {expect,test} from "@playwright/test";
import type {SavedSearchDefinition} from "../src/generated/api";

const fixtureDefinition = (q: string): SavedSearchDefinition => ({
 version:1,scope:"catalog",q,site:null,similar_to:null,
 filters:{excludeText:[],sortBy:"title",tag:["catalog-watch-fixture"]},
});

test("catalog matching shelves baseline and private alerts survive the real worker lifecycle",async({page,request})=>{
 test.skip(process.env.NEXUS_E2E_MODE!=="real"||!process.env.NEXUS_E2E_CATALOG_WATCH_FIXTURE,"Requires the disposable catalog-watch fixture.");
 test.setTimeout(180_000);
 const phase=process.env.NEXUS_E2E_CATALOG_PHASE;
 expect(["activate","verify"]).toContain(phase);
 const fixture=JSON.parse(readFileSync(process.env.NEXUS_E2E_CATALOG_WATCH_FIXTURE!,"utf8"));
 await page.goto("/login");await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
 const loggedIn=page.waitForResponse(response=>response.url().endsWith("/api/auth/login")&&response.request().method()==="POST");await page.getByRole("button",{name:"Sign in",exact:true}).click();const headers={Authorization:`Bearer ${(await(await loggedIn).json()).access_token}`};await expect(page).not.toHaveURL(/\/login/);
 const readSaved=async(name=fixture.search_name)=>{const response=await request.get("/api/saved-searches",{headers});expect(response.ok()).toBeTruthy();return (await response.json()).find((row:{name:string})=>row.name===name);};
 if(phase==="activate"){
  const existing=await readSaved();expect(existing,"Activation fixture should have a fresh saved-query name").toBeUndefined();
  const response=await request.post("/api/saved-searches",{headers,data:{name:fixture.search_name,definition:fixtureDefinition(""),notify_on_match:false}});expect(response.status()).toBe(201);
 }
 const rankedName=`${fixture.search_name} ranked`;
 const saved=await readSaved();expect(saved).toBeTruthy();
 const state=async()=>{const response=await request.get(`/api/catalog-watches/${saved.id}`,{headers});expect(response.ok()).toBeTruthy();return response.json();};
 const matches=async()=>{const response=await request.get(`/api/catalog-watches/${saved.id}/matches?offset=0&limit=50`,{headers});expect(response.ok()).toBeTruthy();return response.json();};
 if(phase==="verify"){
  const ranked=await readSaved(rankedName);expect(ranked).toBeTruthy();
  await Promise.all([
   expect.poll(async()=>(await matches()).total,{timeout:120_000,intervals:[1000,2000,5000]}).toBe(1),
   expect.poll(async()=>{const response=await request.get(`/api/catalog-watches/${ranked.id}/matches?offset=0&limit=50`,{headers});expect(response.ok()).toBeTruthy();return(await response.json()).total;},{timeout:120_000,intervals:[1000,2000,5000]}).toBe(1),
  ]);
  const rankedState=await request.get(`/api/catalog-watches/${ranked.id}`,{headers});expect(rankedState.ok()).toBeTruthy();expect(await rankedState.json()).toMatchObject({status:"active",match_count:1,unread_count:1});
  const rankedMatches=await request.get(`/api/catalog-watches/${ranked.id}/matches?offset=0&limit=50`,{headers});expect(rankedMatches.ok()).toBeTruthy();const rankedMatch=(await rankedMatches.json()).items[0];expect(rankedMatch.novel.id).not.toBe(fixture.existing_metadata_id);expect(rankedMatch.read_at).toBeNull();
 }
 await page.goto("/discover/all");await page.getByRole("button",{name:`Matching stories & alerts ${fixture.search_name}`,exact:true}).click();const sheet=page.getByRole("dialog",{name:`Catalog shelf · ${fixture.search_name}`,exact:true});
 if(phase==="activate"){
  await expect(sheet.getByRole("heading",{name:"Alerts off",exact:true})).toBeVisible();await sheet.getByLabel("Catalog matching mode",{exact:true}).selectOption("lexical");await sheet.getByRole("button",{name:"Prepare matching preview",exact:true}).click();await expect(sheet.locator(`a[href="/story/${fixture.existing_metadata_id}"]`)).toBeVisible();await expect(sheet.getByRole("button",{name:"Enable reviewed matching alerts",exact:true})).toBeEnabled();
  await sheet.getByRole("button",{name:"Enable reviewed matching alerts",exact:true}).click();await expect.poll(async()=>(await state()).status,{timeout:120_000,intervals:[1000,2000,5000]}).toBe("active");await sheet.getByRole("button",{name:"Refresh matching status",exact:true}).click();await expect(sheet.getByRole("heading",{name:"Matching alerts on",exact:true})).toBeVisible();expect((await matches()).total).toBe(0);expect((await state()).baseline_total).toBeGreaterThanOrEqual(1);
  expect(await readSaved(rankedName),"Ranked activation fixture should also be fresh").toBeUndefined();
  const rankedCreated=await request.post("/api/saved-searches",{headers,data:{name:rankedName,definition:fixtureDefinition("Catalog Watch Fixture"),notify_on_match:false}});expect(rankedCreated.status()).toBe(201);const ranked=await rankedCreated.json();
  const rankedPrepared=await request.post(`/api/catalog-watches/${ranked.id}/prepare`,{headers,data:{expected_revision:ranked.revision,mode:"lexical"}});expect(rankedPrepared.ok()).toBeTruthy();const prepared=await rankedPrepared.json();expect(prepared).toMatchObject({status:"prepared",mode:"lexical",search_revision:ranked.revision});expect(prepared.prepared_revision).toMatch(/^[0-9a-f]{64}$/);
  const rankedPreview=await request.post(`/api/catalog-watches/${ranked.id}/results`,{headers,data:{offset:0,limit:50}});expect(rankedPreview.ok()).toBeTruthy();const preview=await rankedPreview.json();expect(preview.total).toBe(1);expect(preview.items.map((row:{id:number})=>row.id)).toEqual([fixture.existing_metadata_id]);
  const rankedActivated=await request.post(`/api/catalog-watches/${ranked.id}/activate`,{headers,data:{expected_revision:ranked.revision,prepared_revision:prepared.prepared_revision}});expect(rankedActivated.ok()).toBeTruthy();
  await expect.poll(async()=>{const response=await request.get(`/api/catalog-watches/${ranked.id}`,{headers});expect(response.ok()).toBeTruthy();return(await response.json()).status;},{timeout:120_000,intervals:[1000,2000,5000]}).toBe("active");
  const rankedBaseline=await request.get(`/api/catalog-watches/${ranked.id}/matches?offset=0&limit=50`,{headers});expect(rankedBaseline.ok()).toBeTruthy();expect((await rankedBaseline.json()).total).toBe(0);

 }else{
  await expect(sheet.getByRole("heading",{name:"Matching alerts on",exact:true})).toBeVisible();const values=await matches();expect(values.items).toHaveLength(1);const match=values.items[0];expect(match.novel.id).not.toBe(fixture.existing_metadata_id);expect(match.novel.title).toContain(fixture.title_prefix);await expect(sheet.getByRole("link",{name:match.novel.title,exact:true})).toHaveAttribute("href",`/story/${match.novel.id}`);await sheet.getByRole("button",{name:`Mark ${match.novel.title} as read`,exact:true}).click();await expect.poll(async()=>(await state()).unread_count).toBe(0);await expect(sheet.getByRole("button",{name:`Mark ${match.novel.title} as read`,exact:true})).toHaveCount(0);await sheet.getByRole("button",{name:"Pause matching alerts",exact:true}).click();await expect(sheet.getByRole("heading",{name:"Matching alerts paused",exact:true})).toBeVisible();expect((await state()).status).toBe("paused");expect((await matches()).items[0].read_at).toBeTruthy();
 }
});
