import { mkdir } from "node:fs/promises";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import type { CalendarYearReview, ReadingGoal, ReadingGoalWrite } from "../src/services/readingStatsService";
const year = new Date().getUTCFullYear();
const goal = (target: number | null = null, revision = 0): ReadingGoal => ({ revision, values: { target_readings: target } });
async function fixture(page: Page, conflictAndLostAck = false, scenario: { goalFailsOnce?: boolean; laterTarget?: number } = {}) {
  const profiles = new Map<number, ReadingGoal>(), puts: { year: number; body: ReadingGoalWrite }[] = [], reviews: number[] = [], goalGets: number[] = [], receipts = new Map<string, ReadingGoal>(); let committed = 0, goalLoadUnavailable = !!scenario.goalFailsOnce;
  const summary = (selected: number) => ({ range: "calendar_year", start: `${selected}-01-01`, end: `${selected}-12-31`, totals: { seconds: 0, words: 0, chapters_finished: 0, stories_finished: 2, reading_runs_finished: 3, rereads_finished: 1 }, daily: [], streak: { current: 0, longest: 0, min_seconds: 300 }, top_stories: [], by_site: [], by_tag: [], completion_history: { undated_runs: 2, undated_runs_included: false } });
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.replace(/^\/api(?=\/)/, ""), method = req.method();
    if (path === "/stats/summary") return route.fulfill({ json: { ...summary(year), range: url.searchParams.get("range") || "week" } });
    const review = path.match(/^\/stats\/review\/(\d+)$/);
    if (review) {
      const selected = Number(review[1]); reviews.push(selected); const result: CalendarYearReview = { year: selected, start: `${selected}-01-01`, end: `${selected}-12-31`, through: selected < year ? `${selected}-12-31` : new Date().toISOString().slice(0, 10), tracking_enabled: false, summary: { ...summary(selected), range: "calendar_year" }, months: Array.from({ length: 12 }, (_, index) => ({ month: index + 1, seconds: 0, words: 0, chapters_finished: 0, stories_finished: index === 0 ? 2 : 0, reading_runs_finished: index === 0 ? 3 : 0, rereads_finished: index === 0 ? 1 : 0 })), goal: { target_readings: profiles.get(selected)?.values.target_readings ?? null, completed_readings: 3 } }; return route.fulfill({ json: result });
    }
    const entry = path.match(/^\/stats\/goals\/(\d+)$/);
    if (entry) {
      const selected = Number(entry[1]);
      if (method === "GET") { goalGets.push(selected); if (goalLoadUnavailable) return route.fulfill({ status: 503, json: { detail: "The optional goal is temporarily unavailable." } }); return route.fulfill({ json: profiles.get(selected) || goal() }); }
      const body = req.postDataJSON() as ReadingGoalWrite; puts.push({ year: selected, body });
      if (receipts.has(body.operation_id)) { if (scenario.laterTarget !== undefined) profiles.set(selected, goal(scenario.laterTarget, 4)); return route.fulfill({ json: receipts.get(body.operation_id) }); }
      if (conflictAndLostAck && puts.length === 1) { profiles.set(selected, goal(5, 2)); return route.fulfill({ status: 409, json: { detail: { code: "preference_conflict", current: goal(5, 2), message: "Goal changed on another device. Review it again." } } }); }
      const current = profiles.get(selected) || goal();
      if (body.expected_revision !== current.revision) return route.fulfill({ status: 409, json: { detail: { code: "preference_conflict", current, message: "Goal changed. Review again." } } });
      const changed = goal(body.values.target_readings, current.revision + 1); profiles.set(selected, changed); receipts.set(body.operation_id, changed); committed++;
      if (conflictAndLostAck && puts.length === 2) return route.abort("failed"); return route.fulfill({ json: changed });
    }
    return route.fallback();
  });
  await page.goto("/stats"); await expect(page.getByRole("heading", { name: "Reading stats", exact: true })).toBeVisible(); const disclosure = page.locator("summary").filter({ hasText: "Calendar year review & optional goal" }); await expect(disclosure).toBeVisible();
  expect(reviews).toEqual([]); expect(goalGets).toEqual([]); expect(puts).toEqual([]); await disclosure.click(); const panel = page.getByRole("region", { name: `Private reading review for ${year}`, exact: true }); await expect(panel).toBeVisible(); if (scenario.goalFailsOnce) await expect(panel.getByRole("button", { name: "Retry optional goal", exact: true })).toBeVisible(); else await expect(panel.getByText("No goal set. You can keep reading without one.", { exact: true })).toBeVisible(); return { panel, puts, reviews, goalGets, recoverGoal: () => { goalLoadUnavailable = false; }, committed: () => committed };
}

test("calendar review has twelve actual months and optional goal save and clear require explicit review", async ({ signedInPage: page }) => {
  const data = await fixture(page); await expect(page.getByRole("radio", { name: "Past 365 days", exact: true })).toBeVisible(); const monthly = data.panel.getByRole("region", { name: `Monthly reading activity for ${year}`, exact: true }); await expect(monthly.getByRole("listitem")).toHaveCount(12); await expect(monthly.getByRole("heading", { name: "January", exact: true })).toBeVisible(); await expect(monthly.getByRole("heading", { name: "December", exact: true })).toBeVisible(); await expect(data.panel.getByText(/Undated or inferred completions are excluded from this year and its goal/)).toBeVisible();
  await data.panel.getByRole("button", { name: "Set an optional goal", exact: true }).click(); await data.panel.getByLabel("Completed readings goal", { exact: true }).fill("10"); await data.panel.getByRole("button", { name: "Review goal change", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "Save this reading goal?", exact: true }); await expect(dialog).toContainText("New goal: 10 completed readings, including rereads."); expect(data.puts).toEqual([]); await dialog.getByRole("button", { name: "Keep current goal", exact: true }).click(); expect(data.puts).toEqual([]);
  await data.panel.getByRole("button", { name: "Review goal change", exact: true }).click(); await page.getByRole("button", { name: "Save reading goal", exact: true }).click(); await expect(data.panel.getByRole("progressbar", { name: `Reading goal progress for ${year}`, exact: true })).toHaveAttribute("value", "3"); expect(data.puts[0]).toEqual({ year, body: { expected_revision: 0, operation_id: expect.any(String), values: { target_readings: 10 } } });
  await data.panel.getByRole("button", { name: "Clear reading goal", exact: true }).click(); await page.getByRole("dialog", { name: "Clear this reading goal?", exact: true }).getByRole("button", { name: "Clear goal", exact: true }).click(); await expect(data.panel.getByText("No goal set. You can keep reading without one.", { exact: true })).toBeVisible(); expect(data.puts[1].body.values.target_readings).toBeNull();
  const selector = page.getByLabel("Review calendar year", { exact: true }); await expect(selector.getByRole("option", { name: String(year + 1), exact: true })).toHaveCount(0); await selector.selectOption(String(year - 1)); const previous = page.getByRole("region", { name: `Private reading review for ${year - 1}`, exact: true }); await expect(previous).toContainText(`Calendar year: January 1–December 31, ${year - 1}`); await expect(previous.getByRole("listitem")).toHaveCount(12); expect(data.reviews).toContain(year - 1); expect(data.committed()).toBe(2);
  await mkdir("/tmp/nexus-calendar-review-ui", { recursive: true }); await page.screenshot({ path: `/tmp/nexus-calendar-review-ui/${page.context().browser()?.browserType().name()}-desktop.png`, fullPage: true });
});

test("stale goal edits need a new review and lost acknowledgements replay the same exact operation", async ({ signedInPage: page }) => {
  const data = await fixture(page, true, { laterTarget: 20 }); await data.panel.getByRole("button", { name: "Set an optional goal", exact: true }).click(); await data.panel.getByLabel("Completed readings goal", { exact: true }).fill("12"); await data.panel.getByRole("button", { name: "Review goal change", exact: true }).click(); await page.getByRole("button", { name: "Save reading goal", exact: true }).click(); await expect(data.panel.getByText("Goal changed on another device. Review it again.", { exact: true })).toBeVisible(); await expect(page.getByRole("dialog")).toHaveCount(0); expect(data.puts).toHaveLength(1);
  await data.panel.getByRole("button", { name: "Review goal change", exact: true }).click(); await expect(page.getByRole("dialog")).toContainText("Current goal: 5 completed readings"); await page.getByRole("button", { name: "Save reading goal", exact: true }).click(); await page.getByRole("button", { name: "Retry same goal change", exact: true }).click(); await expect(data.panel.getByText("Current goal: 20 completed readings", { exact: true })).toBeVisible(); await expect(data.panel.getByText("Your earlier goal change was confirmed. The goal changed again later; the latest target is shown.", { exact: true })).toBeVisible(); expect(data.puts).toHaveLength(3); expect(data.puts[1]).toEqual(data.puts[2]); expect(data.puts[1].body.expected_revision).toBe(2); expect(data.puts[0].body.operation_id).not.toBe(data.puts[1].body.operation_id); expect(data.committed()).toBe(1);
});

test("calendar review and goal confirmation are accessible on a phone and reject invalid target boundaries", async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const data = await fixture(page); const axe = await new AxeBuilder({ page }).include(".calendar-review").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); expect(axe.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await data.panel.getByRole("button", { name: "Set an optional goal", exact: true }).click(); const input = data.panel.getByLabel("Completed readings goal", { exact: true }), review = data.panel.getByRole("button", { name: "Review goal change", exact: true }); for (const value of ["0", "1.5", "10001"]) { await input.fill(value); await expect(review).toBeDisabled(); } await input.fill("10"); await review.click(); await page.getByRole("dialog").evaluate(async element => { await Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => undefined))); }); const modal = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); expect(modal.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]); await mkdir("/tmp/nexus-calendar-review-ui", { recursive: true }); await page.screenshot({ path: `/tmp/nexus-calendar-review-ui/${page.context().browser()?.browserType().name()}-goal-mobile.png` }); await page.keyboard.press("Escape"); expect(data.puts).toEqual([]);
});


test("a failed initial optional goal load has an explicit retry without reopening the calendar year", async ({ signedInPage: page }) => {
  const data = await fixture(page, false, { goalFailsOnce: true });
  await expect(data.panel.getByText("Loading optional goal…", { exact: true })).toHaveCount(0); const initialLoads = data.goalGets.length, reviewRequests = [...data.reviews]; expect(initialLoads).toBeGreaterThanOrEqual(1); expect(data.puts).toEqual([]); data.recoverGoal();
  await data.panel.getByRole("button", { name: "Retry optional goal", exact: true }).click(); await expect(data.panel.getByText("No goal set. You can keep reading without one.", { exact: true })).toBeVisible(); expect(data.goalGets.length).toBeGreaterThan(initialLoads); expect(data.reviews).toEqual(reviewRequests); expect(data.puts).toEqual([]);
});
