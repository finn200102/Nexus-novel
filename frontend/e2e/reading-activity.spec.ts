import { mkdir } from "node:fs/promises";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
async function fixture(page: Page, lostAck = false) {
  let enabled = true, revision = 4;
  const writes: { expected_revision: number; operation_id: string; values: { tracking_enabled: boolean } }[] = [];
  const receipts = new Map<string, unknown>();
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path !== "/stats/preferences") return route.fallback();
    if (request.method() === "GET") return route.fulfill({ json: { revision, values: { tracking_enabled: enabled } } });
    const value = request.postDataJSON(); writes.push(value);
    if (receipts.has(value.operation_id)) return route.fulfill({ json: receipts.get(value.operation_id) });
    if (value.expected_revision !== revision) return route.fulfill({ status: 409, json: { detail: "Setting changed on another device" } });
    enabled = value.values.tracking_enabled; revision++;
    const result = { revision, values: { tracking_enabled: enabled } }; receipts.set(value.operation_id, result);
    if (lostAck && writes.length === 1) return route.abort("failed");
    return route.fulfill({ json: result });
  });
  await page.goto("/settings/reading");
  await expect(page.getByRole("switch", { name: "Measure reading activity", exact: true })).toBeEnabled();
  return { writes, revision: () => revision };
}

test("measurement can be disabled and re-enabled from accessible private settings on a phone", async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const data = await fixture(page);
  const toggle = page.getByRole("switch", { name: "Measure reading activity", exact: true });
  await expect(toggle).toBeChecked(); await toggle.click();
  await expect(toggle).not.toBeChecked(); await expect(page.getByText("Reading measurement is off.", { exact: true })).toBeVisible();
  await expect(page.getByText(/Turning measurement off keeps your saved place/)).toBeVisible();
  expect(data.writes).toHaveLength(1); expect(data.writes[0].values.tracking_enabled).toBe(false);
  await toggle.focus(); await page.keyboard.press("Space"); await expect(toggle).toBeChecked();
  expect(data.writes).toHaveLength(2); expect(data.writes[1].expected_revision).toBe(5);
  await expect(page.getByRole("link", { name: "Open reading statistics", exact: true })).toHaveAttribute("href", "/stats");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations.filter(row => ["serious", "critical"].includes(row.impact || ""))).toEqual([]);
  await mkdir("/tmp/nexus-reading-activity-ui-review", { recursive: true });
  await page.screenshot({ path: `/tmp/nexus-reading-activity-ui-review/${page.context().browser()?.browserType().name()}-phone.png`, fullPage: true });
});

test("a lost disable acknowledgement survives reload and retries the exact operation once", async ({ signedInPage: page }) => {
  const data = await fixture(page, true);
  await page.getByRole("switch", { name: "Measure reading activity", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("could not be confirmed");
  const canTrack = () => page.evaluate(async () => { const path = "/src/services/readingActivityService.ts"; return (await import(path)).readingActivityService.canTrack(); });
  expect(await canTrack()).toBe(false); expect(data.revision()).toBe(5);
  await page.reload();
  await expect(page.getByText("A setting change still needs confirmation. This device has paused measurement.", { exact: true })).toBeVisible();
  expect(await canTrack()).toBe(false);
  await page.getByRole("button", { name: "Retry same change", exact: true }).click();
  await expect(page.getByText("Reading measurement is off.", { exact: true })).toBeVisible();
  expect(data.writes).toHaveLength(2); expect(data.writes[1]).toEqual(data.writes[0]); expect(data.revision()).toBe(5);
  expect(await canTrack()).toBe(false);
});
