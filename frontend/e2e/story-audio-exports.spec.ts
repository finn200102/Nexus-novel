import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import type { AudioExportJob, PodcastEpisode } from "../src/services/audioExportService";
import type { StoryAudioChapter } from "../src/services/audioService";

const novelId = 96;
const storyPath = `/library/1/novels/${novelId}?tab=audio`;
const downloadBytes = Buffer.from("Nexus deterministic M4B download fixture. Codec validation belongs to the encoder tests.");
const makeExport = (status: AudioExportJob["status"]): AudioExportJob => ({
  id: 71, novel_id: novelId, status, total_chapters: 2,
  completed_chapters: status === "completed" ? 2 : 1, audio_bytes: status === "completed" ? downloadBytes.length : null,
  duration_seconds: status === "completed" ? 30 : null, error: null, file_ready: status === "completed",
  created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z",
  chapters: [{ audio_job_id: 9601, chapter_number: 1, title: "The opening", source_version: "original-v1" },
    { audio_job_id: 9603, chapter_number: 3, title: "Across the harbour", source_version: "original-v1" }],
});
async function fixture(page: Page) {
  await page.addInitScript(() => {
    const events: { open: boolean; summary: string; time: number }[] = [];
    (window as unknown as { exportToggleEvents: typeof events }).exportToggleEvents = events;
    document.addEventListener("toggle", event => {
      if (event.target instanceof HTMLDetailsElement) events.push({ open: event.target.open, summary: event.target.querySelector("summary")?.textContent || "", time: performance.now() });
    }, true);
  });
  const selected: { novel_id: number; audio_job_ids: number[] }[] = [];
  const changes: string[] = [];
  const jobs = new Map<number, AudioExportJob>();
  let feedActive = false, tokens = 0, narrationRequests = 0, secondReader = false;
  const episodes: PodcastEpisode[] = [
    { id: 501, source_audio_job_id: 9601, chapter_number: 1, status: "processing", audio_bytes: null, duration_seconds: null, error_code: null, error: null },
    { id: 503, source_audio_job_id: 9603, chapter_number: 3, status: "failed", audio_bytes: null, duration_seconds: null, error_code: "encoder_failed", error: "Podcast preparation failed. The original recording is preserved." },
  ];
  const podcastStatus = (url: string | null = null, offset = 0, limit = 50) => {
    const active = feedActive && !secondReader;
    return { active, feed_url: url, format: "mp3", ready: active ? episodes.filter(row => row.status === "completed").length : 0,
      pending: active ? episodes.filter(row => ["queued", "processing", "retry_wait"].includes(row.status)).length : 0,
      failed: active ? episodes.filter(row => ["failed", "cancelled"].includes(row.status)).length : 0, episodes: active ? episodes.slice(offset, offset + limit) : [], episodes_total: active ? episodes.length : 0, episodes_offset: offset, episodes_limit: limit };
  };
  const chapters: StoryAudioChapter[] = [1, 2, 3].map(number => ({
    id: 9600 + number, chapter_number: number, title: number === 1 ? "The opening" : number === 2 ? "Still preparing" : "Across the harbour",
    content_status: "PRESENT", downloaded: true, source_version: "original-v1",
    latest_job: { id: 9600 + number, status: number === 2 ? "processing" : "completed", audio_ready: number !== 2,
      provider_id: "qwen3_clone", provider_model: "fixture", provider_voice: `Narrator ${number}`, total_parts: 2, completed_parts: number === 2 ? 1 : 2, source_version: "original-v1" },
  }));
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api(?=\/)/, "");
    const method = request.method();
    if (path === "/auth/login" && request.postDataJSON()?.username === "second-reader") {
      secondReader = true;
      return route.fulfill({ json: { access_token: "fixture-second-reader", token_type: "bearer", expires_in: 900, id: 8, username: "second-reader", is_admin: false } });
    }
    if (secondReader && path === "/auth/refresh") return route.fulfill({ json: { access_token: "fixture-second-reader", token_type: "bearer", expires_in: 900, id: 8, username: "second-reader", is_admin: false } });
    if (path === `/novel/${novelId}`) return route.fulfill({ status: secondReader ? 404 : 200, json: secondReader ? { detail: "Story not found" } : { id: novelId, library_id: 1, title: "Exports fixture story", author: "Fixture", metadata_id: null, url: "nexus-local:exports-fixture", novel_site: "local", chapter_count: 3, num_chapters: 3, scrape_status: "completed" } });
    if (path === `/chapter/${novelId}`) return route.fulfill({ json: chapters });
    if (path === `/chapter/progress/${novelId}`) return route.fulfill({ json: null });
    if (path === `/chapter/annotations/${novelId}`) return route.fulfill({ json: [] });
    if (path === `/audio/stories/${novelId}`) return route.fulfill({ json: { novel_id: novelId, total: 3, offset: 0, limit: 50, summary: { chapters: 3, downloaded: 3, ready: 2, queued: 1, needs_retry: 0 }, chapters } });
    if (path === `/audio/stories/${novelId}/jobs` || path === "/audio/jobs" && method === "POST") {
      narrationRequests++; return route.fulfill({ status: 400, json: { detail: "Exports must not request narration" } });
    }
    if (path === "/audio/pronunciation" || path.startsWith("/audio/pronunciation/stories/")) return route.fulfill({ json: { scope: path.includes("stories") ? `pronunciation:${novelId}` : "pronunciation:account", revision: 0, rules: [], account_rules: [], inherit_account: true, effective_rules: [], effective_version: null } });
    if (path === "/audio/voices/default") return route.fulfill({ json: { voice_profile_id: null, revision: 0 } });
    if (path === "/audio/voices" || path === "/audio/jobs") return route.fulfill({ json: [] });
    if (path === "/audio/exports") {
      if (method === "POST") { selected.push(request.postDataJSON()); const job = makeExport("queued"); jobs.set(job.id, job); return route.fulfill({ status: 202, json: job }); }
      return route.fulfill({ json: secondReader ? [] : [...jobs.values()] });
    }
    const mutation = path.match(/^\/audio\/exports\/(\d+)(?:\/(cancel|retry|download))?$/);
    if (mutation) {
      const id = Number(mutation[1]), operation = mutation[2];
      if (method === "DELETE") { changes.push(`delete:${id}`); jobs.delete(id); return route.fulfill({ status: 204 }); }
      if (operation === "download") { changes.push(`download:${id}`); return route.fulfill({ json: { url: `http://127.0.0.1:4188/__fixture_exports/${id}.m4b`, expires_in: 300 }, headers: { "set-cookie": `nexus_fixture_export=scoped-fixture; HttpOnly; SameSite=Strict; Path=/__fixture_exports/${id}.m4b; Max-Age=300` } }); }
      if (operation === "cancel" || operation === "retry") { changes.push(`${operation}:${id}`); const job = makeExport(operation === "cancel" ? "cancelled" : "processing"); jobs.set(id, job); return route.fulfill({ json: job }); }
      return route.fulfill({ json: jobs.get(id) });
    }
    const retryEpisode = path.match(new RegExp(`^/audio/stories/${novelId}/podcast/episodes/(\\d+)/retry$`));
    if (retryEpisode) {
      const id = Number(retryEpisode[1]), index = episodes.findIndex(row => row.id === id);
      changes.push(`episode:retry:${id}`);
      if (index < 0) return route.fulfill({ status: 404 });
      episodes[index] = { ...episodes[index], status: "queued", error: null, error_code: null };
      return route.fulfill({ json: episodes[index] });
    }
    if (path === `/audio/stories/${novelId}/podcast`) {
      if (method === "POST") { feedActive = true; tokens++; changes.push("feed:create"); return route.fulfill({ status: 201, json: podcastStatus(`https://nexus.example/podcasts/private-fixture-${tokens}/feed.xml`) }); }
      if (method === "DELETE") { feedActive = false; changes.push("feed:revoke"); return route.fulfill({ status: 204 }); }
      return route.fulfill({ json: podcastStatus(null, Number(new URL(request.url()).searchParams.get("offset") || 0), Number(new URL(request.url()).searchParams.get("limit") || 50)) });
    }
    if (secondReader && !path.startsWith("/auth/")) return route.fulfill({ json: [] });
    return route.fallback();
  });
  await page.request.post("http://127.0.0.1:4188/__fixture_exports/reset");
  await page.goto(storyPath);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("nexus-signed-in") || "null")?.id)).toBe(7);
  await expect(page.getByRole("region", { name: "Story audio", exact: true }).getByRole("checkbox", { name: "Chapter 1: The opening", exact: true })).toBeVisible();
  const disclosure = page.locator("summary").filter({ hasText: "Audiobook exports and private podcast" });
  await disclosure.focus(); await page.keyboard.press("Enter");
  const panel = page.getByRole("region", { name: "Exports and podcast", exact: true });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("checkbox", { name: "Export chapter 1: The opening", exact: true })).toBeVisible();
  return { panel, disclosure, selected, changes, jobs, chapters, episodes, narrationRequests: () => narrationRequests, fileRequests: async () => (await page.request.get("http://127.0.0.1:4188/__fixture_exports/requests")).json() };
}

test("completed recordings export by exact job snapshot, recover, stream and delete without narration", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await expect(data.panel.getByRole("checkbox", { name: "Export chapter 2: Still preparing", exact: true })).toBeDisabled();
  await data.panel.getByRole("checkbox", { name: "Export chapter 1: The opening", exact: true }).check();
  await data.panel.getByRole("checkbox", { name: "Export chapter 3: Across the harbour", exact: true }).check();
  // A newer recording arrives after selection. Export must preserve the
  // recordings the reader actually reviewed, even when the next poll changes rows.
  data.chapters[0].latest_job = { ...data.chapters[0].latest_job!, id: 9691, provider_voice: "Replacement narrator" };
  await expect(data.panel.getByText("Ready · Replacement narrator", { exact: true })).toBeVisible({ timeout: 7000 }).catch(async error => {
    throw new Error(`${String(error)}\nDisclosure events: ${JSON.stringify(await page.evaluate(() => (window as unknown as { exportToggleEvents: unknown }).exportToggleEvents))}`);
  });
  await data.panel.getByRole("button", { name: "Create M4B audiobook", exact: true }).click();
  await expect.poll(() => data.selected).toEqual([{ novel_id: novelId, audio_job_ids: [9601, 9603] }]);
  await data.panel.getByRole("button", { name: "Cancel export 71", exact: true }).click();
  await expect(data.panel.getByRole("button", { name: "Retry export 71", exact: true })).toBeVisible();
  await data.panel.getByRole("button", { name: "Retry export 71", exact: true }).click();
  await expect(data.panel.getByRole("progressbar", { name: "Audiobook export 71 progress", exact: true })).toHaveAttribute("value", "1");
  data.jobs.set(71, makeExport("completed"));
  await expect(data.panel.getByRole("button", { name: "Download audiobook 71", exact: true })).toBeVisible({ timeout: 7000 });
  const downloadReady = page.waitForEvent("download");
  await data.panel.getByRole("button", { name: "Download audiobook 71", exact: true }).click();
  const downloaded = await downloadReady;
  expect(downloaded.suggestedFilename()).toMatch(/\.m4b$/);
  const saved = await downloaded.path(); expect(saved).not.toBeNull();
  expect(await readFile(saved!)).toEqual(downloadBytes);
  expect(await data.fileRequests()).toEqual({ downloads: 1, authorizedHeader: false, cookiePresent: true });
  await data.panel.getByRole("button", { name: "Delete export 71", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete audiobook export 71?", exact: true });
  await expect(dialog).toBeVisible(); expect(data.changes).not.toContain("delete:71");
  await dialog.getByRole("button", { name: "Delete audiobook", exact: true }).click();
  await expect(data.panel.getByRole("heading", { name: "Audiobook export 71", exact: true })).toHaveCount(0);
  expect(data.changes).toEqual(["cancel:71", "retry:71", "download:71", "delete:71"]);
  expect(data.narrationRequests()).toBe(0);
});

test("private podcast URLs are one-time, reviewed on rotation and revoked without persistent secrets", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  expect(data.changes).toEqual([]);
  await data.panel.getByRole("button", { name: "Create private podcast", exact: true }).click();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveValue(/private-fixture-1/);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("private-fixture-");
  await data.disclosure.click(); await expect(data.panel).toHaveCount(0);
  await data.disclosure.click();
  await expect(data.panel.getByText("Private podcast is active.", { exact: true })).toBeVisible();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveCount(0);
  await data.panel.getByRole("button", { name: "Rotate podcast URL", exact: true }).focus();
  await page.keyboard.press("Enter");
  let dialog = page.getByRole("dialog", { name: "Rotate the private podcast URL?", exact: true });
  await expect(dialog).toBeVisible(); expect(data.changes).toEqual(["feed:create"]);
  await page.keyboard.press("Escape");
  await expect(data.panel.getByRole("button", { name: "Rotate podcast URL", exact: true })).toBeFocused();
  await data.panel.getByRole("button", { name: "Rotate podcast URL", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Rotate the private podcast URL?", exact: true });
  await dialog.getByRole("button", { name: "Rotate URL", exact: true }).click();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveValue(/private-fixture-2/);
  await data.panel.getByRole("button", { name: "Revoke podcast URL", exact: true }).click();
  await page.getByRole("dialog", { name: "Revoke the private podcast URL?", exact: true }).getByRole("button", { name: "Revoke URL", exact: true }).click();
  await expect(data.panel.getByText("Private podcast is disabled.", { exact: true })).toBeVisible();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveCount(0);
  expect(data.changes).toEqual(["feed:create", "feed:create", "feed:revoke"]);
});

test("podcast MP3 preparation polls and retries only the failed episode", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await data.panel.getByRole("button", { name: "Create private podcast", exact: true }).click();
  const preparation = data.panel.getByRole("region", { name: "Podcast episode preparation", exact: true });
  await expect(preparation.getByText("MP3 episodes: 0 ready · 1 queued or preparing · 1 need attention", { exact: true })).toBeVisible();
  await expect(preparation.getByText("Chapter 1: Preparing MP3", { exact: true })).toBeVisible();
  await preparation.getByRole("button", { name: "Retry podcast chapter 3", exact: true }).click();
  await expect(preparation.getByText("MP3 episodes: 0 ready · 2 queued or preparing · 0 need attention", { exact: true })).toBeVisible();
  expect(data.changes).toEqual(["feed:create", "episode:retry:503"]);
  for (let index = 0; index < data.episodes.length; index++) data.episodes[index] = { ...data.episodes[index], status: "completed", audio_bytes: 2048, duration_seconds: 15 };
  await expect(preparation.getByText("MP3 episodes: 2 ready · 0 queued or preparing · 0 need attention", { exact: true })).toBeVisible({ timeout: 7000 });
  await expect(preparation.getByRole("progressbar", { name: "Podcast MP3 preparation", exact: true })).toHaveAttribute("value", "2");
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveValue(/private-fixture-1/);
  expect(data.narrationRequests()).toBe(0);
});

test("changing accounts removes the private feed URL and previous export rows", async ({ signedInPage: page }) => {
  const data = await fixture(page); data.jobs.set(71, makeExport("completed"));
  await data.panel.getByRole("button", { name: "Create private podcast", exact: true }).click();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveValue(/private-fixture-1/);
  await page.goto("/more");
  page.on("dialog", dialog => void dialog.accept());
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await page.getByLabel(/username/i).fill("second-reader");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await expect(page.getByLabel("Private podcast URL", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Audiobook export 71", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("private-fixture-");
});

for (const viewport of [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`exports and podcast have accessible ${viewport.name} controls and confirmation`, async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const data = await fixture(page);
    const findings = await new AxeBuilder({ page }).include(".story-audio-exports").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(findings.violations.filter(item => ["serious", "critical"].includes(item.impact || ""))).toEqual([]);
    const bounds = await data.panel.boundingBox(); expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
    await data.panel.getByRole("button", { name: "Create private podcast", exact: true }).click();
    await data.panel.getByRole("button", { name: "Rotate podcast URL", exact: true }).click();
    await page.getByRole("dialog").evaluate(async element => { await Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => undefined))); });
    const modal = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(modal.violations.filter(item => ["serious", "critical"].includes(item.impact || ""))).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
}


test("podcast failures beyond two hundred chapters remain reachable and retry the exact episode", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  data.episodes.splice(0, data.episodes.length, ...Array.from({ length: 201 }, (_, index) => ({
    id: 1500 + index, source_audio_job_id: 19600 + index, chapter_number: index + 1,
    status: index === 200 ? "failed" : "completed", audio_bytes: 2048, duration_seconds: 15,
    error_code: index === 200 ? "encoder_failed" : null, error: null,
  })));
  await data.panel.getByRole("button", { name: "Create private podcast", exact: true }).click();
  const preparation = data.panel.getByRole("region", { name: "Podcast episode preparation", exact: true });
  await expect(preparation.getByText("MP3 episodes: 200 ready · 0 queued or preparing · 1 need attention", { exact: true })).toBeVisible();
  for (let pageNumber = 1; pageNumber <= 4; pageNumber++) {
    await preparation.getByRole("button", { name: "Next podcast episodes", exact: true }).click();
    await expect(preparation.getByText(`${pageNumber * 50 + 1}–${Math.min((pageNumber + 1) * 50, 201)} of 201 episodes`, { exact: true })).toBeVisible();
  }
  await preparation.getByRole("button", { name: "Retry podcast chapter 201", exact: true }).click();
  await expect.poll(() => data.changes).toContain("episode:retry:1700");
  await expect(preparation.getByText("Chapter 201: Queued", { exact: true })).toBeVisible();
  await expect(data.panel.getByLabel("Private podcast URL", { exact: true })).toHaveValue("https://nexus.example/podcasts/private-fixture-1/feed.xml");
  expect(data.narrationRequests()).toBe(0);
});
