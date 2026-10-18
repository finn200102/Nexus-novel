import {readFileSync} from "node:fs";
import {randomUUID} from "node:crypto";
import {test,expect} from "@playwright/test";

test("optional reading measurement, calendar review and goals stay private and portable",async({page,request})=>{
  test.skip(process.env.NEXUS_E2E_MODE!=="real" || !process.env.NEXUS_E2E_READING_RUNS_FIXTURE,"Requires the disposable acceptance stack.");
  test.setTimeout(120_000);
  const fixture=JSON.parse(readFileSync(process.env.NEXUS_E2E_READING_RUNS_FIXTURE!,"utf8")),year=new Date().getUTCFullYear();
  await page.goto("/login");await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login=page.waitForResponse(response=>response.url().endsWith("/api/auth/login") && response.request().method()==="POST");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  const headers={Authorization:`Bearer ${(await(await login).json()).access_token}`};await expect(page).not.toHaveURL(/\/login/);
  const get=async(path:string)=>{const response=await request.get(`/api${path}`,{headers});expect(response.ok()).toBeTruthy();return response.json();};
  const restore=async(path:string,values:Record<string,unknown>)=>{
    const current=await get(path);
    const response=await request.put(`/api${path}`,{headers,data:{expected_revision:current.revision,operation_id:randomUUID(),values}});
    expect(response.ok()).toBeTruthy();
  };
  const originalRuns=await get(`/reading/stories/${fixture.novel_id}/runs`);
  try{
    const before=await get("/stats/summary?range=all");
    await page.goto("/settings/reading");
    const measurement=page.getByRole("switch",{name:"Measure reading activity",exact:true});await expect(measurement).toBeEnabled();
    await expect(measurement).toBeChecked();
    const off=page.waitForResponse(response=>response.url().endsWith("/api/stats/preferences") && response.request().method()==="PUT");
    await measurement.click();const changed=await off;expect(changed.ok()).toBeTruthy();
    const disabled=await changed.json();expect(disabled.values.tracking_enabled).toBe(false);
    expect(changed.request().postDataJSON().expected_revision).toBe(disabled.revision-1);
    await expect(page.getByText("Reading measurement is off.",{exact:true})).toBeVisible();
    expect((await get("/stats/preferences")).values.tracking_enabled).toBe(false);
    const heartbeat=await request.post("/api/stats/reading-time",{headers,data:{novel_id:fixture.novel_id,chapter_id:fixture.chapters[0].id,seconds:60,words_read_estimate:200}});
    expect(heartbeat.ok()).toBeTruthy();expect(await heartbeat.json()).toEqual({recorded_seconds:0});
    const after=await get("/stats/summary?range=all");
    expect(after.totals.seconds).toBe(before.totals.seconds);expect(after.totals.words).toBe(before.totals.words);
    await page.goto("/stats");await page.getByText("Calendar year review & optional goal",{exact:true}).click();
    const review=page.getByRole("region",{name:`Private reading review for ${year}`,exact:true});
    await expect(review).toBeVisible();await expect(review.getByText(/Reading activity tracking is off/)).toBeVisible();
    await expect(review.getByRole("region",{name:`Monthly reading activity for ${year}`,exact:true}).getByRole("listitem")).toHaveCount(12);
    const goal=review.getByRole("region",{name:`Optional reading goal for ${year}`,exact:true});
    await goal.getByRole("button",{name:"Set an optional goal",exact:true}).click();
    await goal.getByLabel("Completed readings goal",{exact:true}).fill("12");await goal.getByRole("button",{name:"Review goal change",exact:true}).click();
    await expect(page.getByRole("dialog",{name:"Save this reading goal?",exact:true})).toBeVisible();
    const save=page.waitForResponse(response=>response.url().endsWith(`/api/stats/goals/${year}`) && response.request().method()==="PUT");
    await page.getByRole("button",{name:"Save reading goal",exact:true}).click();const saved=await save;
    expect(saved.ok()).toBeTruthy();const savedGoal=await saved.json();expect(savedGoal.values.target_readings).toBe(12);
    expect(saved.request().postDataJSON().expected_revision).toBe(savedGoal.revision-1);
    await expect(goal.getByText("Current goal: 12 completed readings",{exact:true})).toBeVisible();
    expect((await get(`/stats/goals/${year}`)).values.target_readings).toBe(12);
    const staleGoal=await request.put(`/api/stats/goals/${year}`,{headers,data:{...saved.request().postDataJSON(),operation_id:randomUUID(),values:{target_readings:99}}});
    expect(staleGoal.status()).toBe(409);expect((await staleGoal.json()).detail.code).toBe("preference_conflict");
    expect((await get(`/stats/goals/${year}`)).values.target_readings).toBe(12);
    const calendar=await get(`/stats/review/${year}`);
    expect(calendar.start).toBe(`${year}-01-01`);expect(calendar.end).toBe(`${year}-12-31`);expect(calendar.through).toBe(new Date().toISOString().slice(0,10));
    expect(calendar.summary.range).toBe("calendar_year");expect(calendar.summary.start).toBe(`${year}-01-01`);expect(calendar.summary.end).toBe(calendar.through);
    expect(calendar.tracking_enabled).toBe(false);expect(calendar.months.map((month:{month:number})=>month.month)).toEqual(Array.from({length:12},(_,index)=>index+1));
    for(const key of ["reading_runs_finished","rereads_finished","seconds","words","chapters_finished"]){
      expect(calendar.months.reduce((sum:number,month:Record<string,number>)=>sum+month[key],0)).toBe(calendar.summary.totals[key]);
    }
    expect(calendar.goal).toEqual({target_readings:12,completed_readings:calendar.summary.totals.reading_runs_finished});
    const exported=await get("/me/export");
    expect(exported.activity_preferences).toEqual({tracking_enabled:false});
    expect(exported.reading_goals).toContainEqual({year,values:{target_readings:12}});
    expect(JSON.stringify(exported)).not.toContain("PRIVATE_OTHER_READER_JOURNAL");
    expect((await request.get(`/api/reading/stories/${fixture.foreign_novel_id}/runs`,{headers})).status()).toBe(404);
    expect((await request.post("/api/stats/reading-time",{headers,data:{novel_id:fixture.foreign_novel_id,chapter_id:fixture.chapters[0].id,seconds:60}})).status()).toBe(404);
    const untouched=await get(`/reading/stories/${fixture.novel_id}/runs`);
    expect(untouched.current_run_key).toBe(originalRuns.current_run_key);expect(untouched.revision).toBe(originalRuns.revision);expect(untouched.total).toBe(originalRuns.total);
  }finally{
    try{await restore("/stats/preferences",{tracking_enabled:true});}
    finally{await restore(`/stats/goals/${year}`,{target_readings:null});}
  }
  expect((await get("/stats/preferences")).values.tracking_enabled).toBe(true);
  expect((await get(`/stats/goals/${year}`)).values.target_readings).toBeNull();
});
