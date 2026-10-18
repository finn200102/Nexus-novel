import {readFileSync} from "node:fs";
import {expect,test} from "@playwright/test";

test("reviewed source transfer preserves exact originals and undo fences late saves across lost acknowledgments",async({page,request})=>{
  test.skip(process.env.NEXUS_E2E_MODE!=="real" || !process.env.NEXUS_E2E_SOURCE_MIGRATION_FIXTURE,"Requires the disposable acceptance stack.");
  test.setTimeout(120_000);
  const fixture=JSON.parse(readFileSync(process.env.NEXUS_E2E_SOURCE_MIGRATION_FIXTURE!,"utf8"));
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login=page.waitForResponse(response=>response.url().endsWith("/api/auth/login") && response.request().method()==="POST");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  const headers={Authorization:`Bearer ${(await(await login).json()).access_token}`};
  await expect(page).not.toHaveURL(/\/login/);
  // A full supported mapping exceeds nginx's default 1 MiB body limit. Invalid
  // chapter IDs must reach application validation rather than fail at the proxy.
  const largePlan=await request.post("/api/reader/source-migrations/preview",{headers,data:{
    source_novel_id:fixture.source_id,target_novel_id:fixture.target_id,
    mappings:Array.from({length:20_000},(_,index)=>({source_chapter_id:1_000_000_000+index,target_chapter_id:1_500_000_000+index})),
  }});
  expect(largePlan.status()).toBe(404);
  expect(largePlan.headers()["content-type"]).toContain("application/json");
  expect((await largePlan.json()).detail).toBe("A mapped chapter is unavailable in the selected owned story copies");
  const get=async(path:string)=>{const response=await request.get(`/api${path}`,{headers});expect(response.ok(),path).toBeTruthy();return response.json();};
  const state=(id:number)=>get(`/reading/stories/${id}/runs`);
  const stats=async()=>(await get("/stats/summary?range=all")).totals;
  const baseline=await stats();
  const original=await state(fixture.source_id);
  expect(original.current_run_key).toBe(fixture.source_run_key);
  expect(original.current_progress.chapter_number).toBe(7);
  expect(original.current_progress.furthest_chapter_number).toBe(7);
  await page.goto(`/library/${fixture.library_id}/novels/${fixture.source_id}`);
  await page.getByRole("tab",{name:"Details",exact:true}).click();
  await page.getByText("Continue with another source",{exact:true}).click();
  const migration=page.getByRole("region",{name:"Source migration",exact:true});
  await expect(migration).toBeVisible();
  await migration.getByLabel("Find an existing copy in your library",{exact:true}).fill(fixture.target_title);
  await migration.getByRole("button",{name:"Search my copies",exact:true}).click();
  await migration.getByRole("button",{name:`Choose ${fixture.target_title}`,exact:true}).click();
  const previewResponse=page.waitForResponse(response=>response.url().includes("/reader/source-migrations/preview") && response.request().method()==="POST");
  await migration.getByRole("button",{name:"Build chapter preview",exact:true}).click();
  const preview=await previewResponse;expect(preview.ok()).toBeTruthy();
  const reviewed=await preview.json();
  expect(reviewed.can_apply).toBe(true);expect(reviewed.counts.receipts_copied).toBe(1);expect(reviewed.counts.annotations_copied).toBe(1);
  expect(reviewed.items.every((item:{candidates:Array<{evidence:string[]}>})=>item.candidates.every(candidate=>!candidate.evidence.includes("stable_id")))).toBe(true);
  await migration.getByRole("button",{name:"Review transfer",exact:true}).click();
  await expect(page.getByRole("dialog",{name:"Confirm source transfer",exact:true})).toBeVisible();
  const appliedResponse=page.waitForResponse(response=>response.url().endsWith("/reader/source-migrations/apply") && response.request().method()==="POST");
  await page.getByRole("button",{name:"Confirm transfer",exact:true}).click();
  const applied=await appliedResponse;expect(applied.ok()).toBeTruthy();
  const appliedBody=await applied.json(),applyOperation=applied.request().postDataJSON();
  const authoritative=await get(`/reader/source-migrations/${appliedBody.id}`);
  expect(authoritative.status).toBe("applied");expect(authoritative.can_undo).toBe(true);
  const target=await state(fixture.target_id);
  expect(target.current_progress.chapter_number).toBe(20);expect(target.current_progress.percent).toBe(40);
  expect(target.current_progress.furthest_chapter_number).toBe(20);expect(target.current_progress.furthest_percent).toBe(40);
  expect(target.current_progress.text_offset).toBe(11);expect(target.current_progress.text_quote).toBe("😀");
  expect(target.current_run_key).not.toBe(original.current_run_key);
  expect((await get(`/novel/${fixture.target_id}?library_id=${fixture.library_id}`)).next_unread_chapter_number).toBe(20);
  const notes=await get(`/chapter/annotations/${fixture.target_id}`);
  expect(notes).toHaveLength(1);expect(notes[0].note).toBe("Private emoji note");expect(notes[0].text_offset).toBe(11);
  expect((await stats()).reading_runs_finished).toBe(baseline.reading_runs_finished);
  // Stay on Story Details: opening Reader would legitimately change the target.
  await expect(page).toHaveURL(url=>url.pathname===`/library/${fixture.library_id}/novels/${fixture.source_id}` && url.searchParams.get("tab")==="details");
  await expect(migration.getByRole("button",{name:`Review undo transfer ${appliedBody.id}`,exact:true})).toBeEnabled();
  await migration.getByRole("button",{name:`Review undo transfer ${appliedBody.id}`,exact:true}).click();
  await expect(page.getByRole("dialog",{name:"Confirm source transfer undo",exact:true})).toBeVisible();
  const undoResponse=page.waitForResponse(response=>response.url().endsWith(`/reader/source-migrations/${appliedBody.id}/undo`) && response.request().method()==="POST");
  await page.getByRole("button",{name:"Undo reviewed transfer",exact:true}).click();
  const undone=await undoResponse;expect(undone.ok()).toBeTruthy();
  const undoBody=await undone.json(),undoOperation=undone.request().postDataJSON();expect(undoBody.status).toBe("undone");
  const applyReplay=await request.post("/api/reader/source-migrations/apply",{headers,data:applyOperation});
  expect(applyReplay.ok()).toBeTruthy();expect(await applyReplay.json()).toEqual(appliedBody);
  const undoReplay=await request.post(`/api/reader/source-migrations/${appliedBody.id}/undo`,{headers,data:undoOperation});
  expect(undoReplay.ok()).toBeTruthy();expect(await undoReplay.json()).toEqual(undoBody);
  expect((await get(`/reader/source-migrations/${appliedBody.id}`)).status).toBe("undone");
  const blank=await state(fixture.target_id);
  expect(blank.current_run_key).not.toBe(target.current_run_key);expect(blank.revision).toBeGreaterThan(target.revision);
  expect(blank.current_progress.chapter_number).toBe(10);expect(blank.current_progress.percent).toBe(0);
  expect(blank.current_progress.furthest_chapter_number).toBe(0);expect(blank.current_progress.furthest_percent).toBe(0);
  expect(await get(`/chapter/annotations/${fixture.target_id}`)).toEqual([]);
  const delayed=await request.put(`/api/chapter/progress/${fixture.target_id}`,{headers,data:{chapter_number:20,position:900,percent:100,
    expected_revision:blank.revision,reading_run_key:target.current_run_key,operation_id:"source-migration-delayed-target-save",
    content_version:fixture.chapters[1][1].document.content_version}});
  expect(delayed.status()).toBe(409);expect((await delayed.json()).detail.code).toBe("reading_run_changed");
  const sourceAfter=await state(fixture.source_id);
  expect(sourceAfter.current_run_key).toBe(original.current_run_key);expect(sourceAfter.revision).toBe(original.revision);
  expect(sourceAfter.current_progress).toEqual(original.current_progress);
  for(const side of [0,1]){
    const novelId=side===0?fixture.source_id:fixture.target_id;
    for(const chapter of fixture.chapters[side]){
      const current=await get(`/chapter/content/library/${fixture.library_id}/${novelId}/${chapter.number}`);
      expect(current.document).toEqual(chapter.document);
    }
  }
  const final=await stats();expect(final.stories_finished).toBe(baseline.stories_finished);
  expect(final.reading_runs_finished).toBe(baseline.reading_runs_finished);
});
