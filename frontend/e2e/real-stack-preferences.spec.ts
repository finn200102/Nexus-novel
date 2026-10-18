import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";

test("reader typography synchronizes through the real API across separate device profiles", async ({ page, browser }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_COMPANION_FIXTURE, "Requires the isolated acceptance stack.");
  const fixture = JSON.parse(readFileSync(process.env.NEXUS_E2E_COMPANION_FIXTURE!, "utf8"));
  const login = async (target: Page) => {
    await target.goto("/login");
    await target.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
    await target.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
    await target.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(target).not.toHaveURL(/\/login/);
    await target.goto(`/library/${fixture.library_id}/novels/${fixture.novel_id}/1`);
    await target.getByRole("button", { name: "Text settings" }).click();
  };
  await login(page);
  await expect(page.getByLabel("Text size")).toHaveText("19");
  const saved = page.waitForResponse(response => response.url().endsWith("/api/reader/preferences") && response.request().method() === "PUT" && response.status() === 200);
  await page.getByRole("button", { name: "Larger text" }).click();
  const value = await (await saved).json();
  expect(value.values.typography.fontSize).toBe(20);
  const secondContext = await browser.newContext();
  try {
    const second = await secondContext.newPage();
    await login(second);
    await expect(second.getByLabel("Text size")).toHaveText("20");
    await second.getByRole("switch", { name: "Only for this story" }).click();
    await second.getByRole("radio", { name: "Sepia", exact: true }).click();
    await expect(second.locator(".reader")).toHaveAttribute("data-reader-theme", "sepia");
    const committed = second.waitForResponse(response => response.url().endsWith(`/api/reader/preferences/stories/${fixture.novel_id}`) && response.request().method() === "GET" && response.status() === 200);
    await second.evaluate(() => window.dispatchEvent(new Event("focus")));
    await committed;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(page.locator(".reader")).toHaveAttribute("data-reader-theme", "sepia");
    await expect(page.getByRole("switch", { name: "Only for this story" })).toBeChecked();
  } finally { await secondContext.close(); }
});

test("discovery interests and exclusions persist through the real API", async ({ page }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real", "Requires the isolated acceptance stack.");
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/for-you");
  await page.getByText("Set interests and exclusions", { exact: true }).click();
  await page.getByLabel("Favorite tags", { exact: true }).fill("Slow burn");
  await page.getByLabel("Excluded tags", { exact: true }).fill("Horror");
  await page.getByRole("button", { name: "Save discovery preferences", exact: true }).click();
  await expect(page.getByText("Discovery preferences saved.", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByText("Set interests and exclusions", { exact: true }).click();
  await expect(page.getByLabel("Favorite tags", { exact: true })).toHaveValue("Slow burn");
  await expect(page.getByLabel("Excluded tags", { exact: true })).toHaveValue("Horror");
  await page.getByRole("button", { name: "Reset discovery preferences", exact: true }).click();
  await expect(page.getByText("Discovery preferences reset.", { exact: true })).toBeVisible();
});
