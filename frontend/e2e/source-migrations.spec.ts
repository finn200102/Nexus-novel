import { mkdir, writeFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import type { MigrationInput, MigrationApply, MigrationRecord, MigrationStory, MigrationPreview } from "../src/services/sourceMigrationService";
const source: MigrationStory = { novel_id: 11, library_id: 1, title: "The Quiet Ledger", site: "royalroad", source_url: null, chapter_count: 3, current_progress: { chapter_number: 0, percent: 40, revision: 4 }, eligible: true, blocked_reason: null };
const target: MigrationStory = { ...source, novel_id: 22, title: "The Quiet Ledger — alternate author-hosted edition with a deliberately long title", site: "author", current_progress: null };
const path = "/story/4?copy=11&tab=details";
async function install(page: Page, options: { lostApply?: boolean; paged?: boolean; conflict?: boolean } = {}) {
  const applies: MigrationApply[] = [], undos: { expected_revision: number; operation_id: string }[] = [], previewCalls: { input: MigrationInput; offset: number }[] = [], chapterOffsets: number[] = [];
  let record: MigrationRecord | null = null, dropped = false;
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const request = route.request(), url = new URL(request.url()), endpoint = url.pathname.replace(/^\/api(?=\/)/, "");
    if (endpoint.startsWith("/reader/source-migrations")) {
      const offset = Number(url.searchParams.get("offset") || 0), limit = Number(url.searchParams.get("limit") || 20);
      if (endpoint.endsWith("/targets")) return route.fulfill({ json: { total: 1, offset, limit, items: [target] } });
      if (endpoint.endsWith("/chapters/22")) {
        chapterOffsets.push(offset);
        const chapters = Array.from({ length: 201 }, (_, index) => ({ id: 5000 + index, chapter_number: index - 2, title: `Target part ${index}` }));
        return route.fulfill({ json: { total: chapters.length, offset, limit, items: chapters.slice(offset, offset + limit) } });
      }
      if (endpoint.endsWith("/preview")) {
        const input: MigrationInput = request.postDataJSON(); previewCalls.push({ input, offset });
        const mapped = input.mappings.length > 0, selected = input.mappings[0]?.target_chapter_id ?? null;
        const response: MigrationPreview = { source, target, total: options.paged ? 201 : 1, offset, limit, counts: { mapped: mapped ? 3 : 2, skipped: 0, unresolved: mapped ? 0 : 1, annotations_copied: 1, annotations_retained: 2, receipts_copied: 1, history_copied: 2, preferences_copied: 1, followed_categories_copied: 1 }, warnings: ["Changed-text annotations remain in the original copy."], can_apply: mapped, review_token: mapped ? "exact-reviewed-plan" : null, expires_at: mapped ? "2099-10-16T12:00:00Z" : null,
          items: [{ source_chapter_id: offset + 101, source_chapter_number: offset, source_title: offset ? "Later chapter" : "Opening", candidates: [{ target_chapter_id: 201, chapter_number: -2, title: "Opening A", evidence: ["title"], content_equal: false }, { target_chapter_id: 202, chapter_number: 7, title: "Opening B", evidence: ["title"], content_equal: false }], candidates_truncated: !!options.paged, selected_target_chapter_id: mapped ? selected : null, decision: mapped ? "manual" : "ambiguous", required_for_progress: !offset, annotation_count: 3, annotations_copyable: 1, approximate_position: true, receipt_copyable: false }] };
        return route.fulfill({ json: response });
      }
      if (endpoint.endsWith("/apply")) {
        const input: MigrationApply = request.postDataJSON(); applies.push(input);
        if (options.conflict) return route.fulfill({ status: 409, json: { detail: { code: "source_changed", message: "The source reading changed. Review again." } } });
        record ??= { id: 9, revision: 1, status: "applied", source, target, mappings: input.mappings, counts: { mapped: 3, skipped: 0, unresolved: 0, annotations_copied: 1, annotations_retained: 2, receipts_copied: 1, history_copied: 2, preferences_copied: 1, followed_categories_copied: 1 }, created_at: "2026-10-16T12:00:00Z", undone_at: null, target_progress: { chapter_number: 7, percent: 40, revision: 5 }, can_undo: true, undo_blocked_reason: null };
        if (options.lostApply && !dropped) { dropped = true; return route.abort("connectionfailed"); }
        return route.fulfill({ json: record });
      }
      if (endpoint.endsWith("/9/undo")) {
        undos.push(request.postDataJSON()); record = { ...record!, status: "undone", revision: 2, can_undo: false, undone_at: "2026-10-16T13:00:00Z" }; return route.fulfill({ json: record });
      }
      if (endpoint.endsWith("/9")) return route.fulfill({ json: record });
      if (/\/source-migrations\/?$/.test(endpoint)) return route.fulfill({ json: { total: record ? 1 : 0, offset, limit, items: record ? [record] : [] } });
    }
    if (endpoint === "/chapter/progress/11" || endpoint === "/chapter/progress/22") return route.fulfill({ json: { chapter_number: endpoint.endsWith("11") ? 0 : 7, percent: 40, revision: record?.revision ?? 4 } });
    return route.fallback();
  });
  return { applies, undos, previewCalls, chapterOffsets };
}
async function open(page: Page) {
  await page.goto(path); await page.getByRole("tab", { name: "Details", exact: true }).click();
  await page.getByText("Continue with another source", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Source migration", exact: true })).toBeVisible();
}
async function choose(page: Page) {
  await page.getByRole("button", { name: `Choose ${target.title}`, exact: true }).click();
  await page.getByRole("button", { name: "Build chapter preview", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Target for chapter 0", exact: true })).toBeVisible();
}
async function resolve(page: Page) {
  await page.getByRole("combobox", { name: "Target for chapter 0", exact: true }).selectOption("202");
  await page.getByRole("button", { name: "Review changed chapter matches", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review transfer", exact: true })).toBeEnabled();
}
test("reviewed transfer survives a lost acknowledgement and reload, then permits reviewed undo", async ({ signedInPage: page }) => {
  const fixture = await install(page, { lostApply: true }); await open(page); expect(fixture.previewCalls).toHaveLength(0); await choose(page);
  await expect(page.getByRole("button", { name: "Review transfer", exact: true })).toBeDisabled(); await resolve(page);
  const directory = "/tmp/nexus-source-migrations-ui"; await mkdir(directory, { recursive: true });
  await page.getByRole("region", { name: "Chapter match review", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${directory}/${test.info().project.name}-desktop-preview.png` });
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const desktopAxe = await new AxeBuilder({ page }).analyze(); await writeFile(`${directory}/${test.info().project.name}-desktop-axe.json`, JSON.stringify(desktopAxe.violations, null, 2)); expect(desktopAxe.violations).toEqual([]);
  await page.getByRole("button", { name: "Review transfer", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm source transfer", exact: true }); await expect(dialog).toContainText("Chapter 0 · 40%"); expect(fixture.applies).toHaveLength(0);
  await dialog.getByRole("button", { name: "Confirm transfer", exact: true }).click(); await expect(page.getByRole("button", { name: "Retry same transfer", exact: true })).toBeVisible();
  await open(page); await page.getByRole("button", { name: "Retry same transfer", exact: true }).click(); await expect(page.getByRole("status").filter({ hasText: "Transfer confirmed." })).toBeVisible();
  expect(fixture.applies).toHaveLength(2); expect(fixture.applies[1]).toEqual(fixture.applies[0]); expect(fixture.applies[0].mappings).toEqual([{ source_chapter_id: 101, target_chapter_id: 202 }]);
  await page.getByRole("button", { name: "Review undo transfer 9", exact: true }).click();
  const undo = page.getByRole("dialog", { name: "Confirm source transfer undo", exact: true }); await expect(undo).toContainText("new identity"); await undo.getByRole("button", { name: "Undo reviewed transfer", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Undo confirmed." })).toBeVisible(); expect(fixture.undos).toEqual([{ expected_revision: 1, operation_id: expect.any(String) }]);
});
test("full-plan preview and explicit target chapter selection page independently", async ({ signedInPage: page }) => {
  const fixture = await install(page, { paged: true }); await open(page); await choose(page);
  await page.getByRole("button", { name: "Next chapter matches", exact: true }).click();
  await page.getByRole("combobox", { name: "Target for chapter 100", exact: true }).selectOption("other");
  const picker = page.getByRole("dialog", { name: "Choose a target chapter", exact: true });
  await picker.getByRole("button", { name: "Next target chapters", exact: true }).click();
  await picker.getByRole("combobox", { name: "Target chapter", exact: true }).selectOption("5100");
  await picker.getByRole("button", { name: "Use selected chapter", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review transfer", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Review changed chapter matches", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review transfer", exact: true })).toBeEnabled();
  expect(fixture.previewCalls.map(row => row.offset)).toEqual([0, 100, 100]); expect(fixture.previewCalls[2].input.mappings).toEqual([{ source_chapter_id: 201, target_chapter_id: 5100 }]); expect(fixture.chapterOffsets).toEqual([0, 100]); expect(fixture.applies).toEqual([]);
});
test("phone review and confirmation fit the viewport and expose accessible errors on a stale plan", async ({ signedInPage: page }, testInfo) => {
  const fixture = await install(page, { conflict: true }); await page.setViewportSize({ width: 390, height: 844 }); await open(page); await choose(page); await resolve(page);
  const directory = "/tmp/nexus-source-migrations-ui"; await mkdir(directory, { recursive: true });
  await page.evaluate(async () => { await document.fonts.ready; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${directory}/${testInfo.project.name}-phone-preview.png`, fullPage: true });
  await page.getByRole("button", { name: "Review transfer", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm source transfer", exact: true }); await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => { const bounds = element.getBoundingClientRect(); return bounds.left >= 0 && bounds.right <= innerWidth && element.scrollWidth <= element.clientWidth; })).toBe(true);
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const axe = await new AxeBuilder({ page }).analyze(); await writeFile(`${directory}/${testInfo.project.name}-phone-axe.json`, JSON.stringify(axe.violations, null, 2)); expect(axe.violations).toEqual([]);
  await page.screenshot({ path: `${directory}/${testInfo.project.name}-phone-confirm.png`, fullPage: false });
  await dialog.getByRole("button", { name: "Confirm transfer", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "The source reading changed. Review again." })).toBeVisible(); await expect(dialog).toHaveCount(0); expect(fixture.applies).toHaveLength(1);
});
