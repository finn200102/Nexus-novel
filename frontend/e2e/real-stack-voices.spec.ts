import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("global narrator prepares multiple story chapters and supports passage handoff", async ({page}) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || process.env.NEXUS_E2E_VOICE_CLONE !== "1", "Requires explicitly enabled local Qwen hardware qualification.");
  test.setTimeout(900_000);
  const fixture=JSON.parse(readFileSync(process.env.NEXUS_E2E_COMPANION_FIXTURE!,"utf8"));
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const signedIn=page.waitForResponse(response=>response.url().endsWith("/api/auth/login") && response.request().method()==="POST");
  await page.getByRole("button", {name:"Sign in",exact:true}).click();
  const authorization={Authorization:`Bearer ${(await (await signedIn).json()).access_token}`};
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/settings/voices");
  await expect(page.getByRole("heading",{name:"Narrator voices",exact:true})).toBeVisible();
  await page.getByLabel(/^Narrator name/).fill("Synthetic acceptance narrator");
  await page.getByLabel(/^Voice recording/).setInputFiles(process.env.NEXUS_E2E_VOICE_SAMPLE!);
  if(process.env.NEXUS_E2E_VOICE_EXCERPT==="1") {
    expect(readFileSync(process.env.NEXUS_E2E_VOICE_SAMPLE!).byteLength).toBeGreaterThan(1_048_576);
    await expect(page.getByLabel("Excerpt start (seconds)",{exact:true})).toHaveValue("0");
    await expect(page.getByLabel("Excerpt end (seconds)",{exact:true})).toHaveValue("15");
    await expect(page.getByLabel("Use a selected excerpt",{exact:true})).toBeChecked();
  }
  // Exercise upload-only local recognition with synthetic permitted material.
  const uploaded=page.waitForResponse(r=>r.url().endsWith("/api/audio/voices") && r.request().method()==="POST");
  await page.getByRole("button",{name:"Create narrator voice",exact:true}).click();
  const uploadResponse=await uploaded;
  expect(uploadResponse.status()).toBe(202);
  if(process.env.NEXUS_E2E_VOICE_EXCERPT==="1") {
    const body=uploadResponse.request().postDataJSON();
    expect(body.excerpt_start_seconds).toBe(0);expect(body.excerpt_duration_seconds).toBe(15);
  }
  await expect(page.getByRole("button",{name:"Use as narrator",exact:true})).toBeVisible({timeout:700_000});
  await page.getByRole("button",{name:"Listen to Synthetic acceptance narrator",exact:true}).click();
  const preview=page.getByLabel("Cloned narrator preview");
  await expect(preview).toBeVisible();
  await expect.poll(()=>preview.evaluate((audio:HTMLAudioElement)=>audio.duration),{timeout:20_000}).toBeGreaterThan(0);
  await preview.evaluate((audio:HTMLAudioElement)=>audio.pause());
  await page.getByRole("button",{name:"Use as narrator",exact:true}).click();
  await expect(page.getByRole("button",{name:"Selected narrator",exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button",{name:"Selected narrator",exact:true})).toBeVisible();
  const settingsAccessibility=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
  expect(settingsAccessibility.violations.filter(item=>["serious","critical"].includes(item.impact || ""))).toEqual([]);
  if(process.env.NEXUS_E2E_ARTIFACT_DIR) await page.screenshot({path:join(process.env.NEXUS_E2E_ARTIFACT_DIR,"narrator-settings.png"),fullPage:true});

  await page.goto(`/library/${fixture.library_id}/novels/${fixture.novel_id}?tab=audio`);
  await expect(page.getByRole("tab",{name:"Audio",exact:true})).toHaveAttribute("aria-selected","true");
  const audio=page.getByRole("region",{name:"Story audio",exact:true});
  await expect(audio.getByRole("combobox",{name:"Narrator",exact:true})).not.toHaveValue("");
  await audio.getByLabel("Through chapter",{exact:true}).fill("2");
  await audio.getByRole("button",{name:"Add chapter range",exact:true}).click();
  await expect(audio.getByText("2 chapters selected: 1, 2",{exact:true})).toBeVisible();
  const queued=page.waitForResponse(r=>r.url().endsWith(`/api/audio/stories/${fixture.novel_id}/jobs`) && r.request().method()==="POST");
  await audio.getByRole("button",{name:"Create selected audio",exact:true}).click();
  const response=await queued;expect(response.status()).toBe(202);
  const batch=await response.json();expect(batch.outcomes).toHaveLength(2);
  for(const row of batch.outcomes){expect(row.outcome).toBe("queued");expect(row.job.provider_id).toBe("qwen3_clone");expect(row.job.provider_voice).toBe("Synthetic acceptance narrator");}
  const result=batch.outcomes[0].job;
  // Earlier provider qualification can leave ready recordings on these same
  // chapters. Wait for these exact new jobs, rather than stale ready buttons.
  for(const row of batch.outcomes) {
    await expect.poll(async()=>{
      const response=await page.request.get(`/api/audio/jobs/${row.job.id}`,{headers:authorization});
      expect(response.ok()).toBe(true);
      const job=await response.json();
      return job.audio_ready ? job.status : `not-ready:${job.status}`;
    },{timeout:240_000,intervals:[1000,2000,3000]}).toBe("completed");
  }
  await expect(audio.getByRole("button",{name:"Listen to chapter 1",exact:true})).toBeVisible({timeout:240_000});
  await expect(audio.getByRole("button",{name:"Listen to chapter 2",exact:true})).toBeVisible({timeout:240_000});
  const audioAccessibility=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze();
  expect(audioAccessibility.violations.filter(item=>["serious","critical"].includes(item.impact || ""))).toEqual([]);
  if(process.env.NEXUS_E2E_ARTIFACT_DIR) {
    await page.screenshot({path:join(process.env.NEXUS_E2E_ARTIFACT_DIR,"story-audio-desktop.png"),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await expect(audio.getByRole("button",{name:"Create selected audio",exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    await page.screenshot({path:join(process.env.NEXUS_E2E_ARTIFACT_DIR,"story-audio-mobile.png"),fullPage:true});
    await page.setViewportSize({width:1280,height:720});
  }
  await audio.getByRole("link",{name:"Open chapter 1",exact:true}).click();
  await page.getByRole("button",{name:"Listen",exact:true}).click();
  await expect(page.getByRole("button",{name:"Generate chapter audio",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Play",exact:true})).toBeVisible();
  const manifest=page.waitForResponse(r=>r.url().endsWith(`/api/audio/jobs/${result.id}/manifest`));
  await page.getByRole("button",{name:"Play",exact:true}).click();
  const timing=await (await manifest).json();expect(timing.precision).toBe("segment");expect(timing.current_source).toBe(true);expect(timing.segments.some((s:{block_id:string|null})=>s.block_id)).toBe(true);
  await expect(page.getByRole("button",{name:"Pause",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Pause",exact:true}).click();
  await page.getByRole("button",{name:"Listen from this passage",exact:true}).click();
  await expect(page.getByRole("button",{name:"Read this passage",exact:true})).toBeEnabled();
  await page.getByRole("button",{name:"Read this passage",exact:true}).click();
  await expect(page.getByRole("button",{name:"Play",exact:true})).toBeVisible();
  await page.goto("/settings/voices");
  await page.getByRole("button",{name:"Delete Synthetic acceptance narrator",exact:true}).click();
  await expect(page.getByRole("button",{name:"Delete Synthetic acceptance narrator",exact:true})).toHaveCount(0);
  await page.goto(`/library/${fixture.library_id}/novels/${fixture.novel_id}?tab=audio`);
  await expect(page.getByRole("button",{name:"Listen to chapter 1",exact:true})).toBeVisible();
});
