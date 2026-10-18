import { mkdir, readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import type { TranslationBatchInput, TranslationBatchReview, StoryTranslation } from "../src/services/readerToolsService";
const novelId = 97, storyPath = `/library/1/novels/${novelId}?tab=translations`;
const epub = Buffer.from("Deterministic translated EPUB attachment fixture; encoding is verified by backend tests.");
const variant = (id: number, changes: Partial<StoryTranslation> = {}): StoryTranslation => ({ id, chapter_id: id, chapter_number: id, chapter_title: `Saved chapter ${id}`, language: "de", status: "completed", source_version: "original-v1", current_source_version: "original-v1", source_current: true, exportable: true, completed_blocks: 3, total_blocks: 3, provider: { kind: "local", model: "fixture-model" }, error: null, ...changes });
async function fixture(page: Page, initial?: StoryTranslation[], options: { ao3?: boolean; paidBudget?: boolean; conflict?: boolean; exportError?: boolean } = {}) {
  const rows = initial || [variant(1), variant(2, { source_current: false, exportable: false, source_version: "old-version" }), variant(3, { language: "fr" }), variant(4, { status: "failed", exportable: false }), variant(5, { status: "processing", exportable: false, completed_blocks: 1 }), variant(6, { chapter_number: 1 })];
  const exports: number[][] = [], actions: {id:number; action:string}[] = [], offsets: number[] = [];
  let generationCalls = 0;
  let storedTranslationPermission: boolean | null = null;
  const grants: { translation: boolean; ao3_consent: boolean }[] = [];
  const reviews: TranslationBatchInput[] = [], batches: (TranslationBatchInput & { review_token: string })[] = [];
  const sourceChapters = Array.from({ length: 51 }, (_, index) => ({ id: 9701 + index, chapter_number: index + 1, title: `Source chapter ${index + 1}`, content_status: index === 1 ? "MISSING" : "PRESENT", source_version: index === 1 ? null : "original-v1", downloaded: index !== 1 }));
  const batchReview = (input: TranslationBatchInput): TranslationBatchReview => {
    const remote = input.provider_id === 2;
    const items = input.chapter_ids.map(id => ({ chapter_id: id, chapter_number: id - 9700, title: `Source chapter ${id - 9700}`, outcome: remote && options.paidBudget === false ? "blocked" : id === 9703 ? "already_ready" : id === 9704 ? "needs_retry" : "ready_to_queue", job_id: id === 9703 ? 3 : null, source_version: "original-v1", blocks: 8, estimated_max_usd: remote ? 0.05 : 0, error: remote && options.paidBudget === false ? "Configure a spending budget first." : null }));
    return { review_token: `review-${reviews.length}`, expires_at: "2030-01-01T00:00:00Z", provider: { id: input.provider_id, name: remote ? "Economy API" : "Local translator", kind: remote ? "openrouter" : "local_translation", model: remote ? "economy-model" : "local-model", external: remote }, language: input.language, permission: { allowed: !remote || input.external_consent && (!options.ao3 || input.ao3_consent), error: null, is_ao3: !!options.ao3 }, budget: { configured: remote && options.paidBudget !== false, available_usd: options.paidBudget === false ? 0 : 5, budget_usd: options.paidBudget === false ? 0 : 5, used_usd: 0, reserved_usd: 0 }, estimated_max_usd: remote ? 0.05 : 0, queueable: items.filter(row => row.outcome === "ready_to_queue").length, total: items.length, items };
  };
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api(?=\/)/, ""), method = req.method();
    if (path === `/novel/${novelId}`) return route.fulfill({ json: { id: novelId, library_id: 1, title: "Saved translations fixture", author: "Fixture", metadata_id: null, url: "nexus-local:translations", novel_site: "local", chapter_count: 51, num_chapters: 51, scrape_status: "completed" } });
    if (path === `/chapter/${novelId}`) return route.fulfill({ json: [] });
    if (path === `/chapter/progress/${novelId}`) return route.fulfill({ json: null });
    if (path === `/chapter/annotations/${novelId}`) return route.fulfill({ json: [] });
    if (path === "/reader/providers") return route.fulfill({ json: [
      { id: 1, name: "Local translator", kind: "local_translation", model: "local-model", base_url: "http://local.invalid", budget_usd: 0, used_usd: 0, reserved_usd: 0, enabled: true, supported_languages: ["de", "en"] },
      { id: 2, name: "Economy API", kind: "openrouter", model: "economy-model", base_url: "https://remote.invalid", budget_usd: options.paidBudget === false ? 0 : 5, used_usd: 0, reserved_usd: 0, input_price: 1, output_price: 2, enabled: true },
      { id: 3, name: "Disabled local", kind: "local_translation", model: "disabled", base_url: "http://disabled.invalid", budget_usd: 0, used_usd: 0, reserved_usd: 0, enabled: false },
    ] });
    if (path.startsWith(`/reader/permissions/${novelId}/`)) {
      if (method === "PATCH" && path.endsWith("/translation")) { const value = req.postDataJSON(); grants.push(value); storedTranslationPermission = value.translation; }
      return route.fulfill({ json: { translation: storedTranslationPermission, companion: null, ao3_consent: !!options.ao3 && storedTranslationPermission === true, is_ao3: !!options.ao3, local: path.endsWith("/1") } });
    }
    if (path === `/reader/stories/${novelId}/translation-chapters`) {
      const offset = Number(url.searchParams.get("offset") || 0), limit = Number(url.searchParams.get("limit") || 50);
      return route.fulfill({ json: { novel_id: novelId, offset, limit, total: sourceChapters.length, items: sourceChapters.slice(offset, offset + limit) } });
    }
    if (path === `/reader/stories/${novelId}/translation-batch/preview`) { const input = req.postDataJSON(); reviews.push(input); return route.fulfill({ json: batchReview(input) }); }
    if (path === `/reader/stories/${novelId}/translation-batch/jobs`) {
      const input = req.postDataJSON(); batches.push(input);
      if (options.conflict) return route.fulfill({ status: 409, json: { detail: "Source changed. Review this batch again." } });
      const reviewed = batchReview(input), items = reviewed.items.map(row => ({ ...row, outcome: row.outcome === "ready_to_queue" ? "queued" : row.outcome }));
      rows.push(variant(105, { chapter_number: 1, status: "queued", exportable: false, completed_blocks: 0 }));
      return route.fulfill({ status: 202, json: { total: items.length, queued: reviewed.queueable, items } });
    }
    if (path === `/reader/stories/${novelId}/translations`) {
      const offset = Number(url.searchParams.get("offset") || 0), limit = Number(url.searchParams.get("limit") || 50); offsets.push(offset);
      return route.fulfill({ json: { novel_id: novelId, offset, limit, total: rows.length, items: rows.slice(offset, offset + limit) } });
    }
    if (path === `/reader/stories/${novelId}/translations/epub`) { if (options.exportError) return route.fulfill({ status: 422, json: { detail: "Select fewer chapters: export exceeds 40 MiB." } }); exports.push(req.postDataJSON().translation_job_ids); return route.fulfill({ body: epub, contentType: "application/epub+zip", headers: { "content-disposition": 'attachment; filename="fixture-translations.epub"' } }); }
    const action = path.match(/^\/reader\/translation-jobs\/(\d+)$/);
    if (action && method === "POST") {
      const id = Number(action[1]), operation = req.postDataJSON().action; actions.push({ id, action: operation });
      const index = rows.findIndex(row => row.id === id); rows[index] = { ...rows[index], status: operation === "retry" ? "queued" : "cancelled" };
      return route.fulfill({ json: rows[index] });
    }
    if (path.startsWith("/reader/translations/") && method === "POST") { generationCalls++; return route.fulfill({ status: 400, json: { detail: "This workspace must not generate new variants." } }); }
    return route.fallback();
  });
  await page.goto(storyPath);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("nexus-signed-in") || "null")?.id)).toBe(7);
  const panel = page.getByRole("region", { name: "Story translations", exact: true });
  await expect(panel.getByRole("checkbox", { name: `Export chapter ${rows[0].chapter_number}, ${rows[0].language}, variant ${rows[0].id}`, exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Translations", exact: true })).toHaveAttribute("aria-selected", "true");
  return { panel, rows, exports, actions, offsets, reviews, batches, grants, generationCalls: () => generationCalls };
}

test("saved translations select exact completed current variants and download without generation", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await expect(data.panel.getByRole("checkbox", { name: "Export chapter 2, de, variant 2", exact: true })).toBeDisabled();
  await data.panel.getByRole("checkbox", { name: "Export chapter 1, de, variant 1", exact: true }).check();
  await data.panel.getByRole("checkbox", { name: "Export chapter 3, fr, variant 3", exact: true }).click();
  await expect(data.panel.getByText("Choose one translation language per EPUB. Clear your selection to change language.", { exact: true })).toBeVisible();
  await expect(data.panel.getByRole("checkbox", { name: "Export chapter 3, fr, variant 3", exact: true })).not.toBeChecked();
  await data.panel.getByRole("checkbox", { name: "Export chapter 1, de, variant 6", exact: true }).check();
  await expect(data.panel.getByRole("checkbox", { name: "Export chapter 1, de, variant 1", exact: true })).not.toBeChecked();
  const downloadable = page.waitForEvent("download");
  await data.panel.getByRole("button", { name: "Download translated EPUB", exact: true }).click();
  const download = await downloadable; expect(download.suggestedFilename()).toBe("translated-story-97-de.epub");
  expect(await readFile((await download.path())!)).toEqual(epub);
  expect(data.exports).toEqual([[6]]); expect(data.generationCalls()).toBe(0);
  await mkdir("/tmp/nexus-story-translations-ui-review", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-desktop.png`, fullPage: true });
});

test("translation paging preserves explicit selection and retry requires a charge-aware confirmation", async ({ signedInPage: page }) => {
  const rows = Array.from({ length: 51 }, (_, index) => variant(index + 1, index === 50 ? { status: "failed", exportable: false } : {}));
  const data = await fixture(page, rows);
  await data.panel.getByRole("checkbox", { name: "Export chapter 1, de, variant 1", exact: true }).check();
  await data.panel.getByRole("button", { name: "Next translations", exact: true }).click();
  await expect(data.panel.getByText("51–51 of 51", { exact: true })).toBeVisible(); expect(data.offsets).toContain(50);
  await expect(data.panel.getByRole("button", { name: "Remove selected variant 1", exact: true })).toBeVisible();
  await data.panel.getByRole("button", { name: "Retry translation 51", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Retry this translation?", exact: true });
  await expect(dialog).toContainText("may incur API charges"); expect(data.actions).toEqual([]);
  await dialog.getByRole("button", { name: "Keep saved translation", exact: true }).click(); expect(data.actions).toEqual([]);
  await data.panel.getByRole("button", { name: "Retry translation 51", exact: true }).click();
  await dialog.getByRole("button", { name: "Retry selected translation", exact: true }).click();
  await expect.poll(() => data.actions).toEqual([{ id: 51, action: "retry" }]);
  await expect(data.panel.getByRole("button", { name: "Cancel translation 51", exact: true })).toBeVisible();
  await data.panel.getByRole("button", { name: "Cancel translation 51", exact: true }).click();
  await expect.poll(() => data.actions).toEqual([{ id: 51, action: "retry" }, { id: 51, action: "cancel" }]);
  expect(data.generationCalls()).toBe(0);
});

test("translation workspace and retry dialog fit a phone and have accessible controls", async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const data = await fixture(page);
  await mkdir("/tmp/nexus-story-translations-ui-review", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-mobile.png`, fullPage: true });
  const bounds = await data.panel.boundingBox(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391);
  const axe = await new AxeBuilder({ page }).include(".story-translations").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]);
  await data.panel.getByRole("button", { name: "Retry translation 4", exact: true }).click();
  await page.getByRole("dialog").evaluate(async element => { await Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => undefined))); });
  const modal = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(modal.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]);
  await page.keyboard.press("Escape"); await expect(page.getByRole("dialog")).toHaveCount(0); expect(data.actions).toEqual([]);
});


test("bulk local translation reviews exact chapter IDs then explicitly queues without regenerating existing variants", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await data.panel.getByText("Translate downloaded chapters", { exact: true }).click();
  const creation = data.panel.getByRole("region", { name: "Create chapter translations", exact: true });
  await expect(creation.getByRole("checkbox", { name: "Translate chapter 2: Source chapter 2", exact: true })).toBeDisabled();
  await creation.getByLabel("Translation provider", { exact: true }).selectOption("1");
  for (const number of [1, 3, 4]) await creation.getByRole("checkbox", { name: `Translate chapter ${number}: Source chapter ${number}`, exact: true }).check();
  await creation.getByRole("button", { name: "Review translation batch", exact: true }).click();
  const review = creation.getByRole("region", { name: "Translation batch review", exact: true }); await expect(review).toBeVisible();
  await expect(review).toContainText("8 paragraphs"); await expect(review).toContainText("Existing completed variant kept"); await expect(review).toContainText("Existing variant needs explicit retry below");
  expect(data.batches).toEqual([]); expect(data.reviews[0]).toEqual({ chapter_ids: [9701, 9703, 9704], provider_id: 1, language: "de", external_consent: false, ao3_consent: false });
  await creation.getByLabel("Translation language code", { exact: true }).fill("en"); await expect(review).toHaveCount(0);
  await creation.getByRole("button", { name: "Review translation batch", exact: true }).click(); await expect(review).toBeVisible();
  await review.getByRole("button", { name: "Queue reviewed translations", exact: true }).click();
  await expect(creation.getByRole("region", { name: "Translation batch outcomes", exact: true })).toContainText("1 new translations queued from 3 selected chapters");
  expect(data.batches).toEqual([{ chapter_ids: [9701, 9703, 9704], provider_id: 1, language: "en", external_consent: false, ao3_consent: false, review_token: "review-2" }]);
  await expect(data.panel.getByRole("progressbar", { name: "Translation 105 progress", exact: true })).toHaveAttribute("value", "0");
  expect(data.generationCalls()).toBe(0);
  await mkdir("/tmp/nexus-story-translations-ui-review", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-bulk-local.png`, fullPage: true });
});

test("bulk external AO3 processing requires separate consent and paid budget without local fallback", async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const data = await fixture(page, undefined, { ao3: true, paidBudget: false });
  await data.panel.getByText("Translate downloaded chapters", { exact: true }).click(); const creation = data.panel.getByRole("region", { name: "Create chapter translations", exact: true });
  await expect(creation.getByRole("option", { name: "Disabled local · disabled · Disabled", exact: true })).toBeDisabled();
  await creation.getByLabel("Translation provider", { exact: true }).selectOption("2");
  await creation.getByRole("checkbox", { name: "Translate chapter 1: Source chapter 1", exact: true }).check();
  const preview = creation.getByRole("button", { name: "Review translation batch", exact: true }); await expect(preview).toBeDisabled();
  const external = creation.getByRole("checkbox", { name: "Allow sending these selected chapters to this external provider", exact: true }); await external.check(); await expect(preview).toBeDisabled();
  await creation.getByRole("checkbox", { name: "I explicitly allow external processing of this AO3 material", exact: true }).check();
  await creation.getByRole("button", { name: "Remember translation permission for this story", exact: true }).click();
  await expect(creation.getByText("Translation permission is already remembered for this story and provider. Confirm this batch’s external processing above.", { exact: true })).toBeVisible();
  expect(data.grants).toEqual([{ translation: true, ao3_consent: true }]); expect(data.reviews).toEqual([]); expect(data.batches).toEqual([]);
  await preview.click();
  const review = creation.getByRole("region", { name: "Translation batch review", exact: true });
  await expect(review.getByRole("button", { name: "Queue reviewed translations", exact: true })).toBeDisabled(); await expect(review).toContainText("Configure a spending budget first.");
  expect(data.reviews).toEqual([{ chapter_ids: [9701], provider_id: 2, language: "de", external_consent: true, ao3_consent: true }]); expect(data.batches).toEqual([]);
  const axe = await new AxeBuilder({ page }).include(".story-translation-creation").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); expect(axe.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-bulk-mobile.png`, fullPage: true });
  await review.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-bulk-mobile-review.png` });
  await creation.getByLabel("Translation provider", { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `/tmp/nexus-story-translations-ui-review/${page.context().browser()?.browserType().name()}-bulk-mobile-provider.png` });
  await external.uncheck(); await expect(review).toHaveCount(0); await expect(creation.getByLabel("Translation provider", { exact: true })).toHaveValue("2"); expect(data.generationCalls()).toBe(0);
});

test("changed bulk review refuses queue replay and EPUB errors retain server detail", async ({ signedInPage: page }) => {
  const data = await fixture(page, undefined, { conflict: true, exportError: true });
  await data.panel.getByRole("checkbox", { name: "Export chapter 1, de, variant 1", exact: true }).check(); await data.panel.getByRole("button", { name: "Download translated EPUB", exact: true }).click(); await expect(data.panel.getByText("Select fewer chapters: export exceeds 40 MiB.", { exact: true })).toBeVisible();
  await data.panel.getByText("Translate downloaded chapters", { exact: true }).click(); const creation = data.panel.getByRole("region", { name: "Create chapter translations", exact: true });
  await creation.getByLabel("Translation provider", { exact: true }).selectOption("1"); await creation.getByRole("checkbox", { name: "Translate chapter 1: Source chapter 1", exact: true }).check(); await creation.getByRole("button", { name: "Review translation batch", exact: true }).click(); await creation.getByRole("button", { name: "Queue reviewed translations", exact: true }).click();
  await expect(creation.getByText("Source changed. Review this batch again.", { exact: true })).toBeVisible(); await expect(creation.getByRole("region", { name: "Translation batch review", exact: true })).toHaveCount(0); expect(data.batches).toHaveLength(1); expect(data.generationCalls()).toBe(0);
});
