import { test, expect } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";

test("explicit interests save, stale drafts reconcile, and catalog-feed labeling remains honest", async ({ signedInPage: page }) => {
  let revision = 0;
  let values: Record<string, string[]> = {};
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/recommendations/preferences") {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        if (body.expected_revision !== revision) return route.fulfill({ status: 409, json: { detail: { current: { revision, values } } } });
        values = body.values; revision++;
      }
      return route.fulfill({ json: { revision, values } });
    }
    if (path === "/recommendations") return route.fulfill({ json: { data: [], basis: revision ? "your_preferences" : "catalog_feed", source_states: [] } });
    return route.fallback();
  });
  await page.goto("/for-you");
  await expect(page.getByText(/Local catalog feed/)).toBeVisible();
  await page.getByText("Set interests and exclusions", { exact: true }).click();
  await page.getByLabel("Favorite tags", { exact: true }).fill("Slow burn\nAdventure");
  await page.getByLabel("Excluded tags", { exact: true }).fill("Horror");
  await page.getByRole("button", { name: "Save discovery preferences", exact: true }).click();
  await expect(page.getByText("Discovery preferences saved.", { exact: true })).toBeVisible();
  expect(values.tags).toEqual(["Slow burn", "Adventure"]);
  await page.getByLabel("Favorite tags", { exact: true }).fill("Mystery");
  revision++; values = { ...values, tags: ["Fantasy"] };
  await page.reload();
  await page.getByText("Set interests and exclusions", { exact: true }).click();
  await expect(page.getByText(/Preferences changed on another device/)).toBeVisible();
  await expect(page.getByLabel("Favorite tags", { exact: true })).toHaveValue("Mystery");
  await page.getByRole("button", { name: "Keep my choices", exact: true }).click();
  await expect(page.getByText("Discovery preferences saved.", { exact: true })).toBeVisible();
  expect(values.tags).toEqual(["Mystery"]);
  const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(audit.violations.filter(row => row.impact === "serious" || row.impact === "critical")).toEqual([]);
});
