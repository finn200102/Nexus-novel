import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";

// WP-D5/D6 gate: reader layout, bars, chapter drawer, text settings and shortcuts
// (mocked API). axe must report no serious/critical issues in every reader theme.
const LIBRARY_ID = 1;
const NOVEL_ID = 77;
const CHAPTERS = 30;
const READER = `/library/${LIBRARY_ID}/novels/${NOVEL_ID}/3`;
const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

const paragraph = (n: number) =>
  `Paragraph ${n}. The ledger was bound in grey calfskin and smelled faintly of lamp oil, which Orren had always found reassuring. Lamp oil meant someone had stayed late, and someone staying late meant someone cared whether the numbers were right.`;
const content = [
  "A/N: Thanks for the patience this week. The audit arc wraps up in two chapters, and then we go to the coast.",
  "",
  ...Array.from({ length: 40 }, (_, i) => paragraph(i + 1)),
].join("\n");

async function mockReader(page: Page) {
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    const reply = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === `/novel/${NOVEL_ID}`) {
      return reply({ id: NOVEL_ID, library_id: LIBRARY_ID, title: "The Quiet Ledger", author: "Fixture Author", total_chapters: CHAPTERS, next_unread_chapter_number: 4, chapters: [] });
    }
    if (path === `/chapter/${NOVEL_ID}`) {
      return reply([
        { id: 2000, novel_id: NOVEL_ID, chapter_number: 0, title: "Table of contents", category: "index" },
        ...Array.from({ length: CHAPTERS }, (_, i) => ({
          id: 2001 + i, novel_id: NOVEL_ID, chapter_number: i + 1, title: i === 2 ? "Interest Compounds" : `A Long Chapter Title Number ${i + 1} That Wraps Onto Two Lines`, category: "story",
        })),
      ]);
    }
    if (path === `/chapter/progress/${NOVEL_ID}`) return reply({ chapter_number: 2, position: 0, percent: 100 });
    const match = path.match(new RegExp(`^/chapter/content/library/${LIBRARY_ID}/${NOVEL_ID}/(\\d+)$`));
    if (match) {
      const n = Number(match[1]);
      return reply({ id: 2000 + n, novel_id: NOVEL_ID, chapter_number: n, title: n === 3 ? "Interest Compounds" : `Chapter ${n}`, content });
    }
    if (path === `/chapter/annotations/${NOVEL_ID}`) return reply(route.request().method() === "POST" ? { id: 9, chapter_number: 3, annotation_type: "bookmark", position: 0, percent: 0 } : []);
    if (path === `/chapter/history/${NOVEL_ID}`) return reply({ chapters_touched: 3, active_days: 2, current_streak_days: 1 });
    if (path.startsWith(`/novel/hiatus/${NOVEL_ID}`)) return reply({ state: "active", confidence: 0.8, reason: "Updates every few days." });
    if (path.startsWith("/audio/jobs")) return reply([]);
    if (path === `/personal/novels/${NOVEL_ID}`) return reply({ novel_id: NOVEL_ID, followed_categories: ["story"], user_tags: [], shelf_ids: [] });
    if (path.startsWith("/chapter/progress")) return reply({});
    return route.fallback();
  });
}

async function openReader(page: Page, settings: Record<string, unknown> = {}, appTheme = "light") {
  await mockReader(page);
  await page.evaluate(([value, theme]) => {
    localStorage.setItem("nexus-theme", theme as string);
    localStorage.setItem("nexus-reader-typography", JSON.stringify({ v: 2, ...(value as object) }));
    localStorage.removeItem("nexus-reader-layout");
    localStorage.removeItem("nexus-reader-shortcuts");
  }, [settings, appTheme] as const);
  await page.goto(READER);
  await expect(page.getByRole("heading", { level: 1, name: "Interest Compounds" })).toBeVisible();
  await page.waitForTimeout(400);
}

async function expectAxeClean(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const blocking = result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${label} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
  expect(blocking, blocking.join("\n")).toEqual([]);
}

for (const [size, viewport] of Object.entries(SIZES)) {
  test(`reader is axe-clean in every reader theme (${size})`, async ({ signedInPage: page }) => {
    await page.setViewportSize(viewport);
    for (const theme of ["paper", "sepia", "night", "black"]) {
      await openReader(page, { theme });
      await expect(page.locator(".reader")).toHaveAttribute("data-reader-theme", theme);
      await expectAxeClean(page, `${theme} scroll`);
      await page.getByRole("button", { name: "Chapters" }).click();
      await expect(page.getByRole("dialog", { name: "Chapters" })).toBeVisible();
      await page.waitForTimeout(300);
      await expectAxeClean(page, `${theme} chapters`);
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Text settings" }).click();
      await expect(page.getByRole("dialog", { name: "Text settings" })).toBeVisible();
      await page.waitForTimeout(300);
      await expectAxeClean(page, `${theme} text settings`);
      await page.keyboard.press("Escape");
    }
    for (const app of ["light", "dark"]) {
      await openReader(page, { theme: "app" }, app);
      await expect(page.locator(".reader")).toHaveAttribute("data-reader-theme", app === "dark" ? "night" : "paper");
      await expectAxeClean(page, `app ${app}`);
      await page.evaluate(() => localStorage.setItem("nexus-reader-layout", "paged"));
      await page.reload();
      await expect(page.getByText(/^Page \d+ of \d+/)).toBeVisible();
      await page.waitForTimeout(400);
      await expectAxeClean(page, `app ${app} paged`);
    }
  });
}

test("text column is 66ch by default and nothing overflows at 390 and 320 px", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.desktop);
  await openReader(page);
  const measure = await page.locator(".reader__text").evaluate((el) => {
    const probe = document.createElement("div");
    probe.style.width = "66ch";
    el.appendChild(probe);
    const expected = probe.getBoundingClientRect().width;
    probe.remove();
    return { actual: el.getBoundingClientRect().width, expected };
  });
  expect(Math.abs(measure.actual - measure.expected)).toBeLessThan(1);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
    const textOverflow = await page.locator(".reader__content").evaluate((el) => { el.scrollTop = el.scrollHeight; return el.scrollWidth - el.clientWidth; });
    expect(textOverflow, `text column overflow at ${width}px`).toBeLessThanOrEqual(0);
    const clipped = await page.locator(".reader-topbar button, .reader-topbar a").evaluateAll((els) =>
      els.filter((el) => { const r = el.getBoundingClientRect(); return r.right > window.innerWidth || r.left < 0; }).length);
    expect(clipped).toBe(0);
  }
});

test("keyboard: drawer traps and restores focus, settings and shortcuts work", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.desktop);
  await openReader(page, { theme: "night" });
  const chapters = page.getByRole("button", { name: "Chapters" });
  await chapters.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Chapters" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("searchbox")).toBeFocused();
  await expect(drawer.locator("[aria-current='true']")).toContainText("Interest Compounds");
  await expect(drawer.getByText("Unread").first()).toBeAttached();
  for (let i = 0; i < 6; i++) await page.keyboard.press("Tab");
  expect(await drawer.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(chapters).toBeFocused();

  // Single-key shortcuts: on by default, can be turned off in the "?" dialog.
  await page.locator(".reader__content").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("?");
  const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("switch", { name: "Single-key shortcuts" }).click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("j");
  await page.keyboard.press("c");
  await expect(page).toHaveURL(new RegExp(`${READER}$`));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(new RegExp(`/novels/${NOVEL_ID}/4$`));
  await expect(page.getByRole("heading", { level: 1, name: "Chapter 4" })).toBeFocused();
  await page.evaluate(() => localStorage.setItem("nexus-reader-shortcuts", "on"));
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("k");
  await expect(page).toHaveURL(new RegExp(`${READER}$`));

  // Text settings popover: Escape closes and returns focus; changes apply immediately.
  const aa = page.getByRole("button", { name: "Text settings" });
  await aa.click();
  const settings = page.getByRole("dialog", { name: "Text settings" });
  await settings.getByRole("radio", { name: "Sepia" }).click();
  await expect(page.locator(".reader")).toHaveAttribute("data-reader-theme", "sepia");
  await settings.getByRole("button", { name: "Larger text" }).click();
  await expect(settings.getByRole("status", { name: "Text size" }).or(settings.locator("output"))).toHaveText("20");
  await page.keyboard.press("Escape");
  await expect(aa).toBeFocused();

  // Typing in a field never triggers shortcuts.
  await page.getByRole("button", { name: "Chapters" }).click();
  await page.getByRole("searchbox").fill("jk");
  await expect(page).toHaveURL(new RegExp(`${READER}$`));
  await page.keyboard.press("Escape");
});

test("paged mode works without a pointer", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.phone);
  await openReader(page);
  await page.evaluate(() => localStorage.setItem("nexus-reader-layout", "paged"));
  await page.reload();
  const status = page.locator(".reader-bottombar__status");
  await expect(status).toContainText("Page 1 of");
  await page.locator("body").press("ArrowRight");
  await expect(status).toContainText("Page 2 of");
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(status).toContainText("Page 1 of");
  await expect(page.getByRole("progressbar", { name: "Page progress" })).toBeVisible();
});

test("author's note is labelled and collapsed by default", async ({ signedInPage: page }) => {
  await page.setViewportSize(SIZES.desktop);
  await openReader(page);
  const note = page.getByRole("complementary", { name: "Author's note" });
  await expect(note).toBeVisible();
  const toggle = note.getByRole("button", { name: "Show" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(note.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
});
