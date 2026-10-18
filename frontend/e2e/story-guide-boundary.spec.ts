import { mkdir, writeFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

test("guide honors signed verified evidence, empty boundaries and verification failures", async ({ signedInPage: page }, info) => {
  const requests: Array<{ path: string; through: string | null; from: string | null }> = [];
  let boundary: number | null = -2, conflict = false;
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const url = new URL(route.request().url()), path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (!path.startsWith("/discovery/novels/4/story-guide")) return route.fallback();
    requests.push({ path, through: url.searchParams.get("through_chapter"), from: url.searchParams.get("from_chapter") });
    if (path.endsWith("/projection")) {
      if (conflict) return route.fulfill({ status: 409, json: { detail: "Reader evidence cannot be verified. Confirm the current chapter text." } });
      return route.fulfill({ json: { projection_version: "reader-v1", safe_through_chapter: boundary, coverage: { state: boundary === null ? "empty" : "ready", analyzed_chapter_count: boundary === null ? 0 : 1, validated_dossier_count: boundary === null ? 0 : 1, entities: 0, characters: 0, world_entries: 0, assertions: 0, relationships: 0, citations: 0, needs_review: 0 }, overview: { story_so_far: [] }, characters: [], world: [], relationships: [], timeline: [], assertions: [], chapter_dossiers: [] } });
    }
    if (path.endsWith("/changes")) return route.fulfill({ json: { work_id: 4, from_chapter: boundary === null ? null : boundary - 1, through_chapter: boundary, count: 0, changes: { characters: [], world: [], relationships: [], revelations: [], consequences: [], takeaways: [] } } });
    if (path.endsWith("/timeline")) return route.fulfill({ json: { safe_through_chapter: boundary, timelines: [] } });
    return route.fulfill({ json: { chapters_analyzed: boundary === null ? 0 : 1, through_chapter: boundary, characters: [], chapters: [], guide_status: "ready" } });
  });
  await page.goto("/story/4/guide?through_chapter=-2");
  await expect(page.getByRole("heading", { name: "What matters at chapter -2", exact: true })).toBeVisible();
  await expect.poll(() => requests.some(row => row.path.endsWith("/changes") && row.from === "-3" && row.through === "-2")).toBe(true);
  expect(requests.filter(row => row.path.endsWith("/projection")).every(row => row.through === "-2")).toBe(true);
  await expect(page.getByRole("link", { name: "Private companion provider setup", exact: true })).toHaveAttribute("href", "/settings/providers");
  await expect(page.getByRole("button", { name: "Rebuild cited guide", exact: true })).toHaveCount(0);
  boundary = 0;
  await page.goto("/story/4/guide?through_chapter=0");
  await expect(page.getByRole("heading", { name: "What matters at chapter 0", exact: true })).toBeVisible();
  await expect.poll(() => requests.some(row => row.path.endsWith("/changes") && row.from === "-1" && row.through === "0")).toBe(true);
  boundary = null;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/story/4/guide");
  await expect(page.getByText("No completed chapters have verified evidence yet.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Prepare local chapter evidence", exact: true })).toBeDisabled();
  await expect(page.getByRole("navigation", { name: "AI story guide sections", exact: true })).toHaveCount(0);
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const violations = (await new AxeBuilder({ page }).analyze()).violations;
  await mkdir("/tmp/nexus-story-guide-boundary-ui", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-story-guide-boundary-ui/${info.project.name}-phone.png` });
  await writeFile(`/tmp/nexus-story-guide-boundary-ui/${info.project.name}-phone-axe.json`, JSON.stringify(violations, null, 2));
  expect(violations).toEqual([]);
  conflict = true;
  await page.goto("/story/4/guide?through_chapter=-2");
  await expect(page.getByText("Reader evidence cannot be verified. Confirm the current chapter text.", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "AI story guide sections", exact: true })).toHaveCount(0);
});

test("private reader companion keeps prologue and zero boundaries without fabricated evidence", async ({ signedInPage: page }) => {
  const questions: Array<{ through_chapter?: number }> = [];
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/novel/77") return route.fulfill({ json: { id: 77, library_id: 1, title: "Private prologue fixture", total_chapters: 2, next_unread_chapter_number: 0 } });
    if (path === "/chapter/77") return route.fulfill({ json: [-2, 0].map((chapter_number, id) => ({ id: 3000 + id, novel_id: 77, chapter_number, title: chapter_number === -2 ? "Before the ledger" : "Zero chapter", category: "story" })) });
    if (path.startsWith("/chapter/content/library/1/77/")) return route.fulfill({ json: { id: 3000, novel_id: 77, chapter_number: -2, title: "Before the ledger", content: "A quiet prologue before the opening of the ledger." } });
    if (path === "/chapter/progress/77") return route.fulfill({ json: { chapter_number: -2, position: 0, percent: 0, revision: 0 } });
    if (path === "/chapter/annotations/77") return route.fulfill({ json: [] });
    if (path === "/chapter/history/77") return route.fulfill({ json: { chapters_touched: 0, active_days: 0, current_streak_days: 0 } });
    if (path === "/personal/novels/77") return route.fulfill({ json: { novel_id: 77, followed_categories: ["story"], user_tags: [], shelf_ids: [] } });
    if (path === "/reader/providers") return route.fulfill({ json: [{ id: 1, name: "Local fixture", kind: "local", model: "fixture-model", base_url: "http://never-called.invalid", budget_usd: 0, used_usd: 0, reserved_usd: 0 }] });
    if (path.startsWith("/reader/translations/77/")) return route.fulfill({ json: [] });
    if (path === "/reader/companion/77/questions") { questions.push(route.request().postDataJSON()); return route.fulfill({ json: { answer: "Insufficient verified current-reading evidence.", through_chapter: null, charged_usd: 0, citations: [] } }); }
    if (path.startsWith("/audio/jobs")) return route.fulfill({ json: [] });
    return route.fallback();
  });
  await page.goto("/library/1/novels/77/-2");
  await expect(page.getByRole("heading", { level: 1, name: "Before the ledger" })).toBeVisible();
  await page.getByRole("button", { name: "More reader actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Translation & story companion", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Translation & story companion", exact: true });
  await sheet.getByLabel("Provider", { exact: true }).selectOption("1");
  await sheet.getByLabel("Story question", { exact: true }).fill("Who is this person?");
  await expect(sheet.getByLabel("Use completed chapters through", { exact: true })).toHaveValue("-3");
  await sheet.getByRole("button", { name: "Ask with chapter evidence", exact: true }).click();
  await expect(sheet.getByText("Insufficient verified current-reading evidence.", { exact: true })).toBeVisible();
  expect(questions).toHaveLength(1); expect(questions[0].through_chapter).toBe(-3);
  await expect(sheet.getByText(/No completed chapter has verified evidence in this reading/)).toBeVisible();
  await sheet.getByLabel("Use completed chapters through", { exact: true }).fill("0");
  await expect(sheet.getByRole("button", { name: "Ask with chapter evidence", exact: true })).toBeDisabled();
  expect(questions).toHaveLength(1);
});
