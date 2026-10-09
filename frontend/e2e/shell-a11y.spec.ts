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

// WP-D9 gate: the story page (in a library and catalog-only) with each tab, menu and sheet open.
for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`story page is axe-clean (${theme}, ${size})`, async ({ signedInPage: page }) => {
      await page.setViewportSize(viewport);
      await page.evaluate((value) => localStorage.setItem("nexus-theme", value), theme);
      const check = async (label: string) => {
        await page.waitForTimeout(300);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const blocking = result.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        expect(blocking, blocking.join("\n")).toEqual([]);
      };

      await page.goto("/story/4");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("link", { name: /Continue · Ch\. 2/ })).toBeVisible();
      await check("about");
      for (const tab of ["Chapters", "My notes", "Details"]) {
        await page.getByRole("tab", { name: tab }).click();
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
        await check(tab);
      }
      await page.getByRole("tab", { name: "Chapters" }).click();
      await page.getByRole("button", { name: "Manage downloads…" }).click();
      await expect(page.getByRole("dialog", { name: "Downloads and offline" })).toBeVisible();
      await check("downloads sheet");
      await page.keyboard.press("Escape");
      await expect(page.getByRole("button", { name: "Manage downloads…" })).toBeFocused();
      await page.getByRole("button", { name: "More actions" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      await check("more menu");
      await page.keyboard.press("Escape");

      await page.goto("/story/5");
      await expect(page.getByRole("button", { name: "Add to library" })).toBeVisible();
      await expect(page.getByText("Experimental")).toBeVisible();
      await check("catalog-only");
    });
  }
}

test("story page keeps the old library and Discover URLs working", async ({ signedInPage: page }) => {
  await page.goto("/library/1/novels/11");
  await expect(page).toHaveURL(/\/story\/4\?copy=11$/);
  await expect(page.getByRole("heading", { level: 1, name: "The Quiet Ledger" })).toBeFocused();
  await page.goto("/discover/royalroad/5");
  await expect(page).toHaveURL(/\/story\/5$/);
  await expect(page.getByRole("heading", { level: 1, name: "The Cartographer's Apprentice" })).toBeVisible();
});

// WP-D13 gate: every admin section (admin-only) is axe-clean with the same rule set, in both themes, at both widths.
const ADMIN_PAGES = ["/admin/status", "/admin/jobs", "/admin/users", "/admin/duplicates"];

for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`admin sections are axe-clean (${theme}, ${size})`, async ({ signedInPage: page }) => {
      await page.setViewportSize(viewport);
      await page.evaluate((value) => localStorage.setItem("nexus-theme", value), theme);
      for (const path of ADMIN_PAGES) {
        await page.goto(path);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.getByRole("navigation", { name: "Admin sections" })).toBeVisible();
        await expect(page.getByRole("heading", { level: 1, name: "Admin" })).toBeVisible();
        await page.waitForTimeout(500);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const blocking = result.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${path} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        expect(blocking, blocking.join("\n")).toEqual([]);
      }
    });
  }
}

// WP-D12 gate: every settings section has no serious/critical axe violations, in both themes,
// at desktop and phone width; old settings URLs redirect to their section.
const SETTINGS_PAGES = [
  "/settings/account",
  "/settings/appearance",
  "/settings/notifications",
  "/settings/ereaders",
  "/settings/hidden",
  "/settings/data",
];
for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`settings sections are axe-clean (${theme}, ${size})`, async ({ signedInPage: page }) => {
      await page.setViewportSize(viewport);
      await page.evaluate((value) => localStorage.setItem("nexus-theme", value), theme);
      for (const path of SETTINGS_PAGES) {
        await page.goto(path);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await page.waitForTimeout(500);
        const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const blocking = result.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${path} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        expect(blocking, blocking.join("\n")).toEqual([]);
      }
      await page.goto("/settings");
      await page.waitForTimeout(500);
      const index = await new AxeBuilder({ page }).withTags(TAGS).analyze();
      const indexBlocking = index.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `/settings ${v.id}`);
      expect(indexBlocking, indexBlocking.join("\n")).toEqual([]);
    });
  }
}

test("old settings URLs redirect to their section", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.desktop);
  for (const [from, to] of [
    ["/account", /\/settings\/account$/],
    ["/notifications", /\/settings\/notifications$/],
    ["/hidden-content", /\/settings\/hidden$/],
  ] as const) {
    await page.goto(from);
    await expect(page).toHaveURL(to);
  }
});
