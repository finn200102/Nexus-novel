import { test, expect, Page, BrowserContext, Browser, Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";

// Read-only UI capture for review of a running stack. Skipped unless UI_CAPTURE=1.
//   cd nexus-novel/frontend && UI_CAPTURE=1 NEXUS_E2E_VIDEO=off \
//     npx playwright test e2e/ui-capture.spec.ts --config playwright.docker.config.ts
// Writes screenshots, the axe report and the page inventory under <repo>/docs/ui-review.
// Never submits forms, starts live searches, imports, deletes or changes settings.

const enabled = process.env.UI_CAPTURE === "1";
// Run from nexus-novel/frontend (the npx command above); the docs folder is two levels up.
const docsDir = path.resolve(process.cwd(), "../../docs/ui-review");
const screensDir = path.join(docsDir, "screens");

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  mobile: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
} as const;
const SCHEMES = ["default", "dark", "light"] as const;
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

type Viewport = keyof typeof VIEWPORTS;
type Scheme = (typeof SCHEMES)[number];

interface Entry {
  name: string;
  path: string;
  anon?: boolean;
  prep?: (page: Page) => Promise<void>;
  post?: (page: Page) => Promise<void>;
}

interface Session {
  page: Page;
  errors: string[];
}

interface AxeViolation {
  id: string;
  impact: string;
  help: string;
  helpUrl: string;
  nodes: number;
  example: string;
}

interface Inventory {
  name: string;
  url: string;
  title: string;
  headings: string[];
  interactive: number;
  consoleErrors: string[];
  loadMs: number;
}

const shots: string[] = [];
const failures: string[] = [];
const axeByPage = new Map<string, AxeViolation[] | string>();
const keyboardByPage = new Map<string, { focusVisible: number; order: string[] }>();
const inventory: Inventory[] = [];

const contextOptions = (vp: Viewport, scheme: Scheme) => ({
  ...VIEWPORTS[vp],
  ...(scheme === "default" ? {} : { colorScheme: scheme }),
});

async function settle(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
  await page.waitForTimeout(400);
}

async function newSession(context: BrowserContext): Promise<Session> {
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text().slice(0, 200));
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message.slice(0, 200)}`));
  return { page, errors };
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username:").fill("smoke-admin");
  await page.getByLabel("Password:").fill("smoke-password-123");
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page).not.toHaveURL(/\/login(?:$|\?)/);
}

async function clickThenPath(page: Page, locators: Locator[], pattern: RegExp): Promise<string | undefined> {
  for (const locator of locators) {
    if ((await locator.count()) === 0) continue;
    await locator.first().click().catch(() => undefined);
    await page.waitForURL(pattern, { timeout: 10_000 }).catch(() => undefined);
    const pathname = new URL(page.url()).pathname;
    if (pattern.test(pathname)) return pathname;
    await page.goBack().catch(() => undefined);
    await settle(page);
  }
  return undefined;
}

function collectChapterNumbers(value: unknown, out: { number: number; downloaded: boolean }[]) {
  if (Array.isArray(value)) value.forEach((item) => collectChapterNumbers(item, out));
  else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.chapter_number === "number") {
      // content_status is MISSING until the chapter body is downloaded.
      const status = typeof record.content_status === "string" ? record.content_status : "";
      const downloaded = status !== "" && !/missing|pending|queued|failed/i.test(status);
      out.push({ number: record.chapter_number, downloaded });
    }
    Object.values(record).forEach((field) => collectChapterNumbers(field, out));
  }
}

// Finds real ids by clicking through the stack's own UI (its list rows are buttons, not links).
async function buildEntries(page: Page): Promise<Entry[]> {
  const missing = (what: string) => failures.push(`discovery: ${what} not reachable, route skipped`);

  await settle(page);
  const libraryPath = await clickThenPath(page, [page.getByRole("button", { name: "My library" })], /^\/library\/\d+$/);
  if (!libraryPath) throw new Error("could not open My library from home");
  await settle(page);

  const chapterBodies: unknown[] = [];
  page.on("response", async (response) => {
    if (/\/api\/chapter/.test(response.url()) && response.ok()) {
      try { chapterBodies.push(await response.json()); } catch { /* not JSON */ }
    }
  });
  // The first library novel can have no chapters yet, so try the first few cards until one has a chapter.
  let novelPath: string | undefined;
  let chapterPath: string | undefined;
  let guidePath: string | undefined;
  const novelPattern = new RegExp(`^${libraryPath}/novels/\\d+$`);
  for (let i = 0; i < 6 && !chapterPath; i++) {
    await page.goto(libraryPath, { waitUntil: "load" });
    await page.locator(".novel-card").first().waitFor({ timeout: 10_000 }).catch(() => undefined);
    chapterBodies.length = 0;
    const candidate = await clickThenPath(page, [page.locator(".novel-card").nth(i)], novelPattern);
    if (!candidate) continue;
    await settle(page);
    const found: { number: number; downloaded: boolean }[] = [];
    chapterBodies.forEach((body) => collectChapterNumbers(body, found));
    const downloaded = found.filter((c) => c.downloaded).map((c) => c.number);
    const pick = downloaded.length ? Math.min(...downloaded) : undefined;
    novelPath ??= candidate;
    if (pick !== undefined) {
      novelPath = candidate;
      chapterPath = `${candidate}/${pick}`;
      guidePath = (await page.locator('a[href^="/story-guide/"]').first().getAttribute("href").catch(() => null)) ?? undefined;
    }
  }
  if (!novelPath) missing("library novel");
  if (!chapterPath) missing("downloaded chapter");

  await page.goto("/discover", { waitUntil: "load" });
  await settle(page);
  await page.locator(".novel-card").first().waitFor({ timeout: 15_000 }).catch(() => undefined);
  const discoverDetail = await clickThenPath(
    page,
    [page.locator(".novel-card")],
    /^\/discover\/[^/]+\/[^/]+$/,
  );
  if (!discoverDetail) missing("discover item");

  const clickByName = (name: RegExp) => async (p: Page) => {
    await p.getByRole("button", { name }).first().click();
  };
  const reader = chapterPath ?? "/";

  return [
    { name: "login", path: "/login", anon: true },
    { name: "signup", path: "/signup", anon: true },
    { name: "home", path: "/" },
    { name: "discover", path: "/discover" },
    {
      name: "discover-search",
      path: "/discover",
      prep: async (p) => p.getByRole("tab", { name: "Search the sites" }).click(),
    },
    { name: "discover-filters", path: "/discover", prep: clickByName(/filter/i) },
    ...(discoverDetail ? [{ name: "discover-novel", path: discoverDetail }] : []),
    { name: "library", path: libraryPath },
    ...(novelPath ? [{ name: "novel-library", path: novelPath }] : []),
    ...(chapterPath
      ? [
          { name: "reader-scroll", path: reader },
          {
            name: "reader-paged",
            path: reader,
            prep: async (p: Page) => {
              await p.evaluate(() => localStorage.setItem("nexus-reader-layout", "paged"));
              await p.reload({ waitUntil: "load" });
              await settle(p);
            },
            post: async (p: Page) => p.evaluate(() => localStorage.setItem("nexus-reader-layout", "scroll")),
          },
          {
            name: "reader-settings",
            path: reader,
            prep: clickByName(/^Text settings$/),
          },
          { name: "reader-chapter-drawer", path: reader, prep: clickByName(/^Chapters$/) },
        ]
      : []),
    { name: "downloads", path: "/downloads" },
    { name: "activity", path: "/activity" },
    { name: "account", path: "/account" },
    { name: "notifications", path: "/notifications" },
    { name: "hidden-content", path: "/hidden-content" },
    { name: "admin-users", path: "/admin/users" },
    { name: "scrape-jobs", path: "/scrape-jobs" },
    { name: "operations", path: "/operations" },
    { name: "integrations", path: "/integrations" },
    ...(guidePath ? [{ name: "story-guide", path: guidePath }] : []),
  ];
}

async function capture(session: Session, entry: Entry, vp: Viewport, scheme: Scheme) {
  const { page, errors } = session;
  const label = `${entry.name} ${vp} ${scheme}`;
  const primary = vp === "desktop" && scheme === "default";
  errors.length = 0;
  try {
    const started = Date.now();
    await page.goto(entry.path, { waitUntil: "load" });
    await settle(page);
    const loadMs = Date.now() - started;
    try {
      if (entry.prep) {
        await entry.prep(page);
        await settle(page);
      }
      await page.screenshot({ path: path.join(screensDir, `${entry.name}-${vp}-${scheme}.png`), fullPage: true });
      shots.push(label);

      if (primary) {
        const url = page.url();
        const title = await page.title();
        const headings = await page.$$eval("h1,h2,h3", (nodes) =>
          nodes.map((n) => `${n.tagName}: ${(n.textContent ?? "").trim().slice(0, 80)}`).slice(0, 40),
        );
        const interactive = await page.$$eval(
          'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[tabindex]:not([tabindex="-1"])',
          (nodes) => nodes.length,
        );
        inventory.push({ name: entry.name, url, title, headings, interactive, consoleErrors: [...errors], loadMs });

        const axe = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
        axeByPage.set(
          entry.name,
          axe.violations.map((v) => ({
            id: v.id,
            impact: v.impact ?? "none",
            help: v.help,
            helpUrl: v.helpUrl,
            nodes: v.nodes.length,
            example: v.nodes[0]?.target.join(" ") ?? "",
          })),
        );

        await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
        const order: string[] = [];
        let focusVisible = 0;
        for (let i = 0; i < 15; i++) {
          await page.keyboard.press("Tab");
          const stop = await page.evaluate(() => {
            const el = document.activeElement as HTMLElement | null;
            if (!el || el === document.body) return { name: "(body)", visible: false };
            const style = getComputedStyle(el);
            const visible = style.outlineStyle !== "none" || style.boxShadow !== "none";
            const text = el.getAttribute("aria-label") || (el.innerText ?? "").trim().slice(0, 40) || el.getAttribute("title") || "";
            return { name: `${el.tagName.toLowerCase()}: ${text || "(unnamed)"}`, visible };
          });
          order.push(stop.name);
          if (stop.visible) focusVisible++;
        }
        keyboardByPage.set(entry.name, { focusVisible, order });
      }
    } finally {
      if (entry.post) await entry.post(page).catch(() => undefined);
    }
  } catch (error) {
    failures.push(`${label}: ${(error as Error).message.split("\n")[0].slice(0, 200)}`);
  }
}

function writeReports() {
  const lines: string[] = [];
  lines.push("# Nexus 1.0 axe report", "", "Desktop 1440x900, default colour scheme. Tags: wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice.", "");
  const totals = new Map<string, number>();
  const rules = new Map<string, { count: number; impact: string; help: string; helpUrl: string }>();
  for (const [name, result] of axeByPage) {
    lines.push(`## ${name}`, "");
    if (typeof result === "string") {
      lines.push(`Not analysed: ${result}`, "");
      continue;
    }
    if (result.length === 0) {
      lines.push("No violations.", "");
      continue;
    }
    lines.push("| Impact | Rule | Nodes | Example selector | Help |", "| --- | --- | --- | --- | --- |");
    for (const v of result) {
      lines.push(`| ${v.impact} | \`${v.id}\` ${v.help} | ${v.nodes} | \`${v.example.replace(/\|/g, "\\|")}\` | ${v.helpUrl} |`);
      totals.set(v.impact, (totals.get(v.impact) ?? 0) + v.nodes);
      const agg = rules.get(v.id) ?? { count: 0, impact: v.impact, help: v.help, helpUrl: v.helpUrl };
      agg.count += v.nodes;
      rules.set(v.id, agg);
    }
    lines.push("");
  }
  lines.push("## Totals", "", "| Impact | Affected nodes |", "| --- | --- |");
  for (const [impact, count] of totals) lines.push(`| ${impact} | ${count} |`);
  lines.push("", "## Top rules by affected nodes", "", "| Rule | Impact | Nodes | Help |", "| --- | --- | --- | --- |");
  for (const [id, r] of [...rules].sort((a, b) => b[1].count - a[1].count).slice(0, 10)) {
    lines.push(`| \`${id}\` | ${r.impact} | ${r.count} | ${r.helpUrl} |`);
  }
  lines.push("", "## Keyboard check (Tab x15, desktop)", "", "Focus visible = computed outline-style or box-shadow is not none on the focused element.", "");
  for (const [name, k] of keyboardByPage) {
    lines.push(`- **${name}**: ${k.focusVisible}/15 stops with visible focus. Order: ${k.order.join(" → ")}`);
  }
  lines.push("");
  if (failures.length) lines.push("## Failed captures", "", ...failures.map((f) => `- ${f}`), "");
  fs.writeFileSync(path.join(docsDir, "axe-report.md"), lines.join("\n"));

  const inv: string[] = ["# Nexus 1.0 UI inventory", "", "Desktop 1440x900, default scheme, logged in as smoke-admin. Load time is goto(load) only, before settle.", ""];
  for (const item of inventory) {
    inv.push(`## ${item.name}`, "", `- URL: ${item.url}`, `- Title: ${item.title || "(none)"}`, `- Load time: ${item.loadMs} ms`, `- Interactive elements: ${item.interactive}`);
    inv.push(`- Console errors (${item.consoleErrors.length}): ${item.consoleErrors.length ? item.consoleErrors.map((e) => `\`${e.replace(/`/g, "'")}\``).join("; ") : "none"}`);
    inv.push(`- Headings: ${item.headings.length ? item.headings.join(" / ").replace(/\n/g, " ") : "none"}`, "");
  }
  if (failures.length) inv.push("## Failed captures", "", ...failures.map((f) => `- ${f}`), "");
  fs.writeFileSync(path.join(docsDir, "inventory.md"), inv.join("\n"));
}

test.describe("UI capture", () => {
  test.skip(!enabled, "Set UI_CAPTURE=1 to capture review screens against the running stack.");

  test("capture every main route", async ({ browser }: { browser: Browser }) => {
    test.setTimeout(60 * 60_000);
    fs.mkdirSync(screensDir, { recursive: true });
    let entries: Entry[] | null = null;

    try {
      for (const vp of Object.keys(VIEWPORTS) as Viewport[]) {
        for (const scheme of SCHEMES) {
          const context = await browser.newContext(contextOptions(vp, scheme));
          const session = await newSession(context);
          try {
            // Logged-out pages first, in the same context before login.
            const anonEntries: Entry[] = [{ name: "login", path: "/login" }, { name: "signup", path: "/signup" }];
            for (const entry of anonEntries) await capture(session, entry, vp, scheme);

            await login(session.page);
            if (!entries) entries = await buildEntries(session.page);
            for (const entry of entries) {
              if (entry.anon) continue;
              await capture(session, entry, vp, scheme);
            }
          } catch (error) {
            failures.push(`${vp} ${scheme} session: ${(error as Error).message.split("\n")[0].slice(0, 200)}`);
          } finally {
            await context.close();
          }
        }
      }
    } finally {
      for (const entry of entries ?? []) {
        if (entry.anon || axeByPage.has(entry.name)) continue;
        axeByPage.set(entry.name, "capture failed before analysis");
      }
      writeReports();
      console.log(`screenshots: ${shots.length}`);
      console.log(`failures: ${failures.length}`);
    }
    expect(shots.length).toBeGreaterThan(0);
  });
});
