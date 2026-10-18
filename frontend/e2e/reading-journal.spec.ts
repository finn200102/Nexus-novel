import { mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import type { ReadingJournalEntry, ReadingRun, ReadingRunChange, ReadingRunProgress } from "../src/services/readingJournalService";
const novelId = 98, oldKey = "11111111-1111-4111-8111-111111111111", newKey = "22222222-2222-4222-8222-222222222222";
const storyPath = `/library/1/novels/${novelId}?tab=history`;
const content = "The first followed chapter begins here. Your previous reading remains in the journal.";
const html = `<p>${content}</p>`, version = createHash("sha256").update(html).digest("hex");
const document = { schema_version: 1, content_version: version, source_format: "html", blocks: [{ id: `b-${version.slice(0, 24)}-0`, kind: "p", html, text: content }], plain_text: content };
async function fixture(page: Page, options: { lostAck?: boolean; long?: boolean; completed?: boolean; conflict?: boolean } = {}) {
  let progress: ReadingRunProgress = { novel_id: novelId, chapter_number: 9, position: 100, percent: 65, revision: 4, reading_run_key: oldKey, furthest_chapter_number: 10, furthest_percent: 90 };
  const run: ReadingRun = { reading_run_key: oldKey, ordinal: options.long ? 22 : 1, status: options.completed ? "completed" : "active", started_at: null, started_at_inferred: true, completed_at: null, completed_at_inferred: !!options.completed, abandoned_at: null, abandon_reason: null, archived_at: null, progress: { ...progress }, next_unread_chapter_id: 9803, next_unread_chapter_number: 3 };
  const runs: ReadingRun[] = [run];
  const entries: ReadingJournalEntry[] = [{ id: 1, novel_id: novelId, novel_title: "Reading journal fixture", reading_run_key: oldKey, kind: "completed", occurred_at: null, inferred: true, reason: null, ordinal: run.ordinal }];
  if (options.long) for (let index = 1; index <= 21; index++) {
    const key = `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
    runs.push({ ...run, reading_run_key: key, ordinal: 22 - index, status: "completed", completed_at_inferred: true, archived_at: "2026-10-15T00:00:00Z" });
    entries.push({ ...entries[0], id: index + 1, reading_run_key: key, ordinal: 22 - index });
  }
  const attempts: { action: string; body: ReadingRunChange }[] = [], receipts = new Map<string, unknown>(), saves: Record<string, unknown>[] = [];
  let secondReader = false;
  const state = (offset = 0, limit = 20) => ({ novel_id: novelId, current_run_key: secondReader ? null : progress.reading_run_key, revision: secondReader ? 0 : progress.revision, current_progress: secondReader ? null : progress, first_chapter_number: 3, total: secondReader ? 0 : runs.length, offset, limit, items: secondReader ? [] : runs.slice(offset, offset + limit) });
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api(?=\/)/, ""), method = req.method();
    if (path === "/auth/login" && req.postDataJSON()?.username === "journal-other") { secondReader = true; return route.fulfill({ json: { access_token: "fixture-journal-other", token_type: "bearer", expires_in: 900, id: 8, username: "journal-other", is_admin: false } }); }
    if (secondReader && path === "/auth/refresh") return route.fulfill({ json: { access_token: "fixture-journal-other", token_type: "bearer", expires_in: 900, id: 8, username: "journal-other", is_admin: false } });
    if (path === `/novel/${novelId}` && secondReader) return route.fulfill({ status: 404, json: { detail: "Story not found" } });
    if (path === `/novel/${novelId}`) return route.fulfill({ json: { id: novelId, library_id: 1, title: "Reading journal fixture", author: "Fixture", metadata_id: null, url: "nexus-local:reading-journal", novel_site: "local", chapter_count: 2, num_chapters: 2, scrape_status: "completed" } });
    if (path === `/chapter/${novelId}`) return route.fulfill({ json: [3, 9].map(number => ({ id: 9800 + number, chapter_number: number, title: number === 3 ? "First followed chapter" : "Saved position", content_status: "PRESENT", category: "story" })) });
    if (path === `/chapter/content/library/1/${novelId}/3`) return route.fulfill({ json: { id: 9803, novel_id: novelId, chapter_number: 3, title: "First followed chapter", document, content } });
    if (path === `/chapter/progress/${novelId}`) {
      if (method === "PUT") { const body = req.postDataJSON(); saves.push(body); progress = { ...progress, ...body, revision: progress.revision + 1, locator_content_version: body.content_version }; }
      return route.fulfill({ json: progress });
    }
    if (path === `/chapter/annotations/${novelId}`) return route.fulfill({ json: [] });
    if (path.startsWith(`/chapter/versions/${novelId}/`)) return route.fulfill({ json: { current_version: version, next_cursor: null, versions: [] } });
    if (path === `/reading/stories/${novelId}/runs`) return route.fulfill({ json: state(Number(url.searchParams.get("offset") || 0), Number(url.searchParams.get("limit") || 20)) });
    if (path === "/reading/journal") { const offset = Number(url.searchParams.get("offset") || 0), limit = Number(url.searchParams.get("limit") || 20); return route.fulfill({ json: { total: secondReader ? 0 : entries.length, offset, limit, items: secondReader ? [] : entries.slice(offset, offset + limit) } }); }
    const action = path.match(new RegExp(`^/reading/stories/${novelId}/runs/(start|finish|drop)$`));
    if (action && method === "POST") {
      const kind = action[1], body = req.postDataJSON() as ReadingRunChange; attempts.push({ action: kind, body });
      if (receipts.has(body.operation_id)) return route.fulfill({ json: receipts.get(body.operation_id) });
      if (options.conflict || body.expected_revision !== progress.revision || body.reading_run_key !== progress.reading_run_key) return route.fulfill({ status: 409, json: { detail: { code: "progress_conflict", message: "Another device changed this reading. Review the latest position." } } });
      const now = "2026-10-16T10:00:00Z", current = runs.find(row => row.reading_run_key === progress.reading_run_key)!;
      progress = { ...progress, revision: progress.revision + 1 };
      if (kind === "start") { current.archived_at = now; current.progress = { ...progress, revision: progress.revision - 1 }; progress = { ...progress, chapter_number: 3, position: 0, percent: 0, reading_run_key: newKey, furthest_chapter_number: 0, furthest_percent: 0 }; runs.unshift({ ...run, reading_run_key: newKey, ordinal: current.ordinal + 1, status: "active", started_at: now, started_at_inferred: false, completed_at: null, completed_at_inferred: false, archived_at: null, progress: { ...progress } }); }
      else { current.status = kind === "finish" ? "completed" : "abandoned"; current.progress = { ...progress }; if (kind === "finish") { current.completed_at = now; current.completed_at_inferred = false; } else { current.abandoned_at = now; current.abandon_reason = body.reason || null; } }
      entries.unshift({ id: entries.length + 1, novel_id: novelId, novel_title: "Reading journal fixture", reading_run_key: progress.reading_run_key!, kind: kind === "start" ? "started" : kind === "finish" ? "completed" : "abandoned", occurred_at: now, inferred: false, reason: body.reason || null, ordinal: runs[0].ordinal });
      const response = JSON.parse(JSON.stringify(state())); receipts.set(body.operation_id, response);
      if (options.lostAck && attempts.length === 1) return route.abort("failed");
      return route.fulfill({ json: response });
    }
    if (path.startsWith("/audio/jobs")) return route.fulfill({ json: [] });
    if (path.startsWith("/audio/pronunciation")) return route.fulfill({ json: { scope: "pronunciation:98", revision: 0, rules: [], account_rules: [], inherit_account: true, effective_rules: [], effective_version: null } });
    return route.fallback();
  });
  await page.goto(storyPath); await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("nexus-signed-in") || "null")?.id)).toBe(7);
  const panel = page.getByRole("region", { name: "Private reading history", exact: true }); await expect(panel.getByRole("region", { name: "Current reading", exact: true }).getByText("Chapter 9 · 65%", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Reading history", exact: true })).toHaveAttribute("aria-selected", "true");
  return { panel, attempts, runs, entries, saves };
}

test("start again reviews existing position, preserves inferred completion, and opens the actual first chapter", async ({ signedInPage: page }) => {
  const data = await fixture(page, { completed: true });
  await expect(data.panel.getByText("Finished: Date unknown · inferred from earlier records", { exact: true })).toBeVisible();
  await mkdir("/tmp/nexus-reading-journal-ui-review", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-reading-journal-ui-review/${page.context().browser()?.browserType().name()}-desktop.png`, fullPage: true });
  await data.panel.getByRole("button", { name: "Start again", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "Start this story again?", exact: true });
  await expect(dialog).toContainText("Existing position: Chapter 9 · 65%"); await expect(dialog).toContainText("completion history and notes are preserved"); expect(data.attempts).toEqual([]);
  await dialog.getByRole("button", { name: "Start new reading", exact: true }).click(); await expect(page).toHaveURL(new RegExp(`/library/1/novels/${novelId}/3$`));
  expect(data.attempts[0].body).toEqual({ expected_revision: 4, reading_run_key: oldKey, operation_id: expect.any(String) });
  expect(data.runs).toHaveLength(2); expect(data.runs[1].status).toBe("completed"); expect(data.runs[1].completed_at_inferred).toBe(true);
  const cached = await page.evaluate(async id => { const path = "/src/services/chapterService.ts"; const module = await import(path); return module.chapterService.getCachedReadingProgress(id); }, novelId);
  expect(cached.reading_run_key).toBe(newKey); expect(cached.revision).toBeGreaterThanOrEqual(5);
});

test("lost start response retries the same operation without creating another reading", async ({ signedInPage: page }) => {
  const data = await fixture(page, { lostAck: true }); await data.panel.getByRole("button", { name: "Start again", exact: true }).click(); await page.getByRole("button", { name: "Start new reading", exact: true }).click();
  await page.getByRole("button", { name: "Retry same reading change", exact: true }).click(); await expect(page).toHaveURL(new RegExp(`/library/1/novels/${novelId}/3$`));
  expect(data.attempts).toHaveLength(2); expect(data.attempts[1]).toEqual(data.attempts[0]); expect(data.runs).toHaveLength(2); expect(data.entries.filter(entry => entry.kind === "started")).toHaveLength(1);
});

test("queued offline progress blocks restart and remains available for reader reconciliation", async ({ signedInPage: page }) => {
  const data = await fixture(page); await page.evaluate(async id => { const path = "/src/services/progressSyncQueue.ts"; const module = await import(path); module.enqueueProgress({ novelId: id, chapter: 8, position: 40, percent: 50, ts: Date.now(), readingRunKey: "11111111-1111-4111-8111-111111111111", blocked: true }); }, novelId);
  await expect(data.panel.getByRole("button", { name: "Start again", exact: true })).toBeDisabled(); await expect(data.panel.getByRole("link", { name: "Open reader to review unsynchronized progress", exact: true })).toBeVisible(); expect(data.attempts).toEqual([]);
  const queued = await page.evaluate(async () => { const path = "/src/services/progressSyncQueue.ts"; return (await import(path)).getQueuedProgress(); }); expect(queued).toHaveLength(1); expect(queued[0].chapter).toBe(8); expect(queued[0].readingRunKey).toBe(oldKey);
});

test("finish and stop are explicit, keep the position, and record only the private optional reason", async ({ signedInPage: page }) => {
  const data = await fixture(page); await data.panel.getByRole("button", { name: "Finish this reading", exact: true }).click(); await expect(page.getByRole("dialog", { name: "Mark this reading finished?", exact: true })).toContainText("saved position stays where it is"); expect(data.attempts).toEqual([]);
  await page.getByRole("button", { name: "Mark reading finished", exact: true }).click(); await expect(data.panel.getByRole("region", { name: "Current reading", exact: true })).toContainText("Reading 1 · Finished");
  await data.panel.getByRole("button", { name: "Stop this reading", exact: true }).click(); const reason = page.getByLabel("Reason for stopping (optional)", { exact: true }); await expect(reason).toHaveAttribute("maxlength", "500"); await reason.fill("Prefer a different pace"); await page.getByRole("button", { name: "Stop reading", exact: true }).click();
  await expect(data.panel.getByRole("region", { name: "Private reading journal", exact: true })).toContainText("Reason: Prefer a different pace");
  expect(data.attempts.map(item => item.action)).toEqual(["finish", "drop"]); expect(data.attempts[1].body.reason).toBe("Prefer a different pace"); await expect(data.panel.getByRole("region", { name: "Current reading", exact: true })).toContainText("Chapter 9 · 65%");
});

test("saved readings and journal pages remain independent, while stale reviews require new confirmation", async ({ signedInPage: page }) => {
  const data = await fixture(page, { long: true, conflict: true }); await data.panel.getByRole("button", { name: "Next readings", exact: true }).click(); await expect(data.panel.getByRole("region", { name: "Saved readings", exact: true })).toContainText("21–22 of 22 readings"); await expect(data.panel.getByRole("region", { name: "Current reading", exact: true })).toContainText("Reading 22 · In progress");
  await data.panel.getByRole("button", { name: "Next journal entries", exact: true }).click(); await expect(data.panel.getByRole("region", { name: "Private reading journal", exact: true })).toContainText("21–22 of 22 journal entries");
  await data.panel.getByRole("button", { name: "Start again", exact: true }).click(); await page.getByRole("button", { name: "Start new reading", exact: true }).click(); await expect(page.getByRole("dialog")).toHaveCount(0); await expect(data.panel.getByText("Another device changed this reading. Review the latest position.", { exact: true })).toBeVisible(); expect(data.attempts).toHaveLength(1);
});

test("reading journal and confirmation fit a phone with accessible controls", async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const data = await fixture(page); const axe = await new AxeBuilder({ page }).include(".story-reading-history").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); expect(axe.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390); await mkdir("/tmp/nexus-reading-journal-ui-review", { recursive: true }); await page.screenshot({ path: `/tmp/nexus-reading-journal-ui-review/${page.context().browser()?.browserType().name()}-mobile.png`, fullPage: true });
  await data.panel.getByRole("button", { name: "Stop this reading", exact: true }).click(); await page.getByRole("dialog").evaluate(async element => { await Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => undefined))); }); const modal = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); expect(modal.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]); await page.screenshot({ path: `/tmp/nexus-reading-journal-ui-review/${page.context().browser()?.browserType().name()}-confirmation.png` }); await page.keyboard.press("Escape"); expect(data.attempts).toEqual([]);
});


test("signing into another account cannot retain the prior private journal or stopping reason", async ({ signedInPage: page }) => {
  const data = await fixture(page); await data.panel.getByRole("button", { name: "Stop this reading", exact: true }).click(); await page.getByLabel("Reason for stopping (optional)", { exact: true }).fill("Private journal reason for the first reader"); await page.getByRole("button", { name: "Stop reading", exact: true }).click();
  await expect(data.panel.getByRole("region", { name: "Private reading journal", exact: true })).toContainText("Private journal reason for the first reader");
  await page.goto("/more"); page.on("dialog", dialog => void dialog.accept()); await page.getByRole("button", { name: "Sign out", exact: true }).click(); await expect(page).toHaveURL(/login/); await page.getByLabel(/username/i).fill("journal-other"); await page.getByLabel(/password/i).fill("fixture-password"); await page.getByRole("button", { name: /login|sign in/i }).click(); await expect(page).not.toHaveURL(/login/);
  await expect(page.getByText("Private journal reason for the first reader", { exact: false })).toHaveCount(0); await expect(page.getByRole("region", { name: "Private reading journal", exact: true })).toHaveCount(0); expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("Private journal reason for the first reader");
});
