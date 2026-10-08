import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// WP-D4 gate: the app shell has no serious/critical axe violations on the four main
// destinations, in both themes, at desktop and phone width (mocked API).
const PAGES = ["/", "/discover", "/library", "/updates", "/updates/downloads", "/updates/problems", "/more"];
const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`shell is axe-clean (${theme}, ${size})`, async ({ signedInPage: page }) => {
      await page.setViewportSize(viewport);
      await page.evaluate((value) => localStorage.setItem("nexus-theme", value), theme);
      for (const path of PAGES) {
        await page.goto(path);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(1);
        await page.waitForTimeout(500);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const blocking = result.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${path} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        expect(blocking, blocking.join("\n")).toEqual([]);
      }
      if (size === "desktop") {
        await page.goto("/");
        await page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: /e2e-user/ }).click();
        await expect(page.getByRole("dialog", { name: "Account" })).toBeVisible();
        await page.waitForTimeout(500);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const blocking = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `profile menu ${v.id}`);
        expect(blocking, blocking.join("\n")).toEqual([]);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("button", { name: /e2e-user/ })).toBeFocused();
      }
    });
  }
}

test("skip link comes first and route changes focus the page heading", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.desktop);
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Updates" }).click();
  await expect(page).toHaveURL(/\/updates$/);
  await expect(page).toHaveTitle("Updates – Nexus");
  await expect(page.locator("#main h1")).toBeFocused();
});

test("phone tab bar reaches every destination with a visible label", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.phone);
  await page.goto("/");
  const tabs = page.getByRole("navigation", { name: "Main" });
  for (const [label, url] of [["Discover", /\/discover$/], ["Library", /\/library$/], ["Updates", /\/updates$/], ["More", /\/more$/], ["Home", /\/$/]] as const) {
    await tabs.getByRole("link", { name: label }).click();
    await expect(page).toHaveURL(url);
    await expect(tabs.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  }
});
