import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// WP-D4 gate: the app shell has no serious/critical axe violations on the four main
// destinations, in both themes, at desktop and phone width (mocked API).
const PAGES = ["/", "/discover", "/library", "/updates", "/updates/downloads", "/updates/problems", "/more", "/stats"];
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

// Library polish + WP-D14 gate: heading switcher menu, Organize menu, Shelves sheet and the
// Add story sheet (opened from the top bar, prefilled with the current library) are axe-clean.
const AFTER_DIR = "../../docs/ui-review/screens-after";
for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`library and Add story are axe-clean (${theme}, ${size})`, async ({ signedInPage: page }) => {
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
      const shot = (name: string) =>
        page.screenshot({ path: `${AFTER_DIR}/${name}-${size === "phone" ? "mobile" : "desktop"}-${theme}.png` });

      await page.goto("/library");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const switcher = page.locator("#main h1").getByRole("button");
      await expect(switcher).toBeVisible();
      await expect(page.getByRole("button", { name: "Add novel" })).toHaveCount(0);
      await check("library");
      await shot("library");

      if (size === "phone") {
        await expect(page.getByLabel("My tag")).toBeHidden();
        await page.getByRole("button", { name: /^Filters/ }).click();
        await expect(page.getByLabel("My tag")).toBeVisible();
        await check("library filters");
      }

      await switcher.click();
      await expect(page.getByRole("menuitem", { name: "Rename library…" })).toBeVisible();
      await check("library menu");
      await page.keyboard.press("Escape");
      await expect(switcher).toBeFocused();

      await page.getByRole("button", { name: "Organize" }).click();
      await page.getByRole("menuitem", { name: "Shelves…" }).click();
      await expect(page.getByRole("dialog", { name: "Shelves" })).toBeVisible();
      await check("shelves sheet");
      await page.keyboard.press("Escape");

      await page.getByRole("button", { name: "Add story" }).first().click();
      const sheet = page.getByRole("dialog", { name: "Add story" });
      await expect(sheet).toBeVisible();
      await expect(sheet.getByLabel("Story link")).toBeFocused();
      await check("add story");
      await shot("add-story");
      await sheet.getByRole("tab", { name: "Import" }).click();
      await check("add story import");
      await page.keyboard.press("Escape");
      await expect(sheet).toHaveCount(0);
    });
  }
}

// WP-D8 gate: Discover with results, site chips, inline filters and the More filters sheet open.
for (const theme of ["light", "dark"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`discover is axe-clean with filters open (${theme}, ${size})`, async ({ signedInPage: page }) => {
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
      const suffix = `${size === "phone" ? "mobile" : "desktop"}-${theme}`;

      await page.goto("/discover");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("heading", { level: 2, name: "Results" })).toBeVisible();
      await expect(page.getByRole("heading", { level: 3, name: "The Quiet Ledger" })).toBeVisible();
      await expect(page.getByRole("group", { name: "Sites" }).getByRole("button", { name: "All sites" })).toHaveAttribute("aria-pressed", "true");
      await check("discover");
      await page.screenshot({ path: `${AFTER_DIR}/discover-${suffix}.png` });

      await page.getByLabel("Length").selectOption("long");
      await expect(page).toHaveURL(/filters=/);
      await expect(page.getByRole("button", { name: /Remove filter Min words/ })).toBeVisible();

      const more = page.getByRole("button", { name: /^More filters/ });
      await more.click();
      const sheet = page.getByRole("dialog", { name: "More filters" });
      await expect(sheet).toBeVisible();
      await check("more filters");
      await page.screenshot({ path: `${AFTER_DIR}/discover-filters-${suffix}.png` });
      await page.keyboard.press("Escape");
      await expect(sheet).toHaveCount(0);
      await expect(more).toBeFocused();

      await page.getByRole("button", { name: "More actions for The Quiet Ledger" }).click();
      await expect(page.getByRole("menuitem", { name: /Hide author/ })).toBeVisible();
      await check("card menu");
      await page.keyboard.press("Escape");
    });
  }
}
