import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

test("server provider prepares two chapters, preserves matching audio and plays measured PCM", async ({ page, request }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_COMPANION_FIXTURE,
    "Requires the isolated acceptance stack and its deterministic speech fixture.");
  test.setTimeout(180_000);
  const fixture = JSON.parse(readFileSync(process.env.NEXUS_E2E_COMPANION_FIXTURE!, "utf8"));
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const signedIn = page.waitForResponse(response => response.url().endsWith("/api/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const login = await signedIn;
  expect(login.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  await expect(page).not.toHaveURL(/\/login/);

  await page.goto(`/library/${fixture.library_id}/novels/${fixture.novel_id}?tab=audio`);
  const audio = page.getByRole("region", { name: "Story audio", exact: true });
  await audio.getByRole("combobox", { name: "Voice provider", exact: true }).selectOption("custom");
  await audio.getByRole("combobox", { name: "Generate audio", exact: true }).selectOption("server");
  await audio.getByLabel("API base URL", { exact: true }).fill("http://fixture-source:8090/tts/v1");
  await audio.getByLabel("Model", { exact: true }).fill("fixture");
  await audio.getByLabel("Voice", { exact: true }).fill("fixture");
  await audio.getByLabel("API key", { exact: true }).fill("");
  await audio.getByRole("button", { name: "Check provider", exact: true }).click();
  await expect(audio.getByText("Provider is reachable from the Nexus server.", { exact: true })).toBeVisible();

  const selectBoth = async () => {
    await audio.getByLabel("From chapter", { exact: true }).fill("1");
    await audio.getByLabel("Through chapter", { exact: true }).fill("2");
    await audio.getByRole("button", { name: "Add chapter range", exact: true }).click();
    await expect(audio.getByText("2 chapters selected: 1, 2", { exact: true })).toBeVisible();
  };
  const submit = async () => {
    const queued = page.waitForResponse(response => response.url().endsWith(`/api/audio/stories/${fixture.novel_id}/jobs`)
      && response.request().method() === "POST");
    await audio.getByRole("button", { name: "Create selected audio", exact: true }).click();
    const response = await queued;
    expect(response.status()).toBe(202);
    expect(response.request().postDataJSON().voice_profile_id).toBeUndefined();
    expect(response.request().postDataJSON().provider).toMatchObject({ id: "custom", model: "fixture", voice: "fixture", execution_mode: "server" });
    expect(response.request().postDataJSON().provider.api_key).toBeUndefined();
    return response.json();
  };
  await selectBoth();
  const batch = await submit();
  expect(batch.outcomes).toHaveLength(2);
  for (const row of batch.outcomes) {
    expect(row.outcome).toBe("queued");
    expect(row.job.provider_id).toBe("custom");
    expect(row.job.voice_profile_id).toBeNull();
    // Another journey may have left playable recordings for these chapters.
    // Wait for this exact newly requested rendition before checking alignment.
    await expect.poll(async () => {
      const result = await request.get(`/api/audio/jobs/${row.job.id}`, { headers });
      expect(result.ok()).toBeTruthy();
      return (await result.json()).status;
    }, { timeout: 120_000 }).toBe("completed");
  }
  await expect(audio.getByRole("button", { name: "Listen to chapter 1", exact: true })).toBeVisible({ timeout: 120_000 });
  await expect(audio.getByRole("button", { name: "Listen to chapter 2", exact: true })).toBeVisible({ timeout: 120_000 });
  for (const row of batch.outcomes) {
    const manifestResponse = await request.get(`/api/audio/jobs/${row.job.id}/manifest`, { headers });
    expect(manifestResponse.ok()).toBeTruthy();
    const manifest = await manifestResponse.json();
    expect(manifest.precision).toBe("segment");
    expect(manifest.current_source).toBe(true);
    expect(manifest.source_version).toBe(row.job.source_version);
    expect(manifest.duration_seconds).toBeGreaterThan(0);
    expect(manifest.segments.some((segment: { block_id: string | null }) => segment.block_id)).toBe(true);
    expect(manifest.segments.at(-1).end_seconds).toBe(manifest.duration_seconds);
    const recording = await request.get(`/api/audio/jobs/${row.job.id}/audio`, { headers });
    expect(recording.ok()).toBeTruthy();
    expect(recording.headers()["content-type"]).toContain("audio/wav");
    expect((await recording.body()).subarray(0, 4).toString()).toBe("RIFF");
  }
  await selectBoth();
  const repeated = await submit();
  expect(repeated.outcomes.map((row: { outcome: string }) => row.outcome)).toEqual(["already_ready", "already_ready"]);
  expect(repeated.outcomes.map((row: { job: { id: number } }) => row.job.id)).toEqual(batch.outcomes.map((row: { job: { id: number } }) => row.job.id));

  await audio.getByRole("button", { name: "Listen to chapter 1", exact: true }).click();
  const playback = audio.getByLabel("Chapter 1 audio", { exact: true });
  await expect(playback).toBeVisible();
  await expect.poll(() => playback.evaluate((element: HTMLAudioElement) => element.duration)).toBeGreaterThan(0);
  await playback.evaluate((element: HTMLAudioElement) => element.play());
  try {
    await expect.poll(() => playback.evaluate((element: HTMLAudioElement) => element.currentTime),
      { timeout: 15_000 }).toBeGreaterThan(0);
  } catch (error) {
    const state = await playback.evaluate((element: HTMLAudioElement) => ({
      currentTime: element.currentTime, duration: element.duration,
      paused: element.paused, ended: element.ended, readyState: element.readyState,
      error: element.error ? { code: element.error.code, message: element.error.message } : null,
      played: Array.from({ length: element.played.length }, (_, index) => [element.played.start(index), element.played.end(index)]),
    }));
    await test.info().attach("audio-playback-state", { body: JSON.stringify(state), contentType: "application/json" });
    throw error;
  }
  await playback.evaluate((element: HTMLAudioElement) => element.pause());
});
