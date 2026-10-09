import { test, expect, Page } from "@playwright/test";

// Walks the 1.0 screens against a running stack. Needs a user whose library
// has a Royal Road novel with at least one downloaded chapter:
//   NEXUS_E2E_READER_PATH=/library/<library>/novels/<novel>/<chapter>
// One live Royal Road search request is made; nothing else leaves the stack
// (the bulk import uses a URL that is already in the library).
const realStack = process.env.NEXUS_E2E_MODE === "real";
const username = process.env.NEXUS_E2E_USER;
const password = process.env.NEXUS_E2E_PASSWORD;
const readerPath = process.env.NEXUS_E2E_READER_PATH;
const importUrl = process.env.NEXUS_E2E_IMPORT_URL || "https://www.royalroad.com/fiction/21220/mother-of-learning";

const watchConsole = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    // Expected 4xx answers (e.g. no saved progress) are logged by the browser
    // as resource errors; they are not application errors.
    if (message.type() === "error" && !/Failed to load resource/.test(message.text())) errors.push(message.text());
  });
  return errors;
};

test.describe("Nexus real-stack 1.0 UI", () => {
  test.skip(!realStack, "Set NEXUS_E2E_MODE=real to run against the configured API.");
  test.setTimeout(180_000);

  test("discover, import, story page, reader, updates and settings", async ({ page }) => {
    test.skip(!username || !password || !readerPath, "Needs NEXUS_E2E_USER, NEXUS_E2E_PASSWORD and NEXUS_E2E_READER_PATH.");
    const errors = watchConsole(page);
    const [, libraryId, novelId] = readerPath!.match(/^\/library\/(\d+)\/novels\/(\d+)\/\d+$/) ?? [];

    await page.goto("/login");
    await page.getByLabel("Username").fill(username!);
    await page.getByLabel(/^Password/).fill(password!);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).not.toHaveURL(/\/login(?:$|\?)/);

    // Discover → Search the sites (Royal Road only).
    await page.goto("/discover");
    await page.getByRole("tab", { name: "Search the sites" }).click();
    const live = page.getByRole("region", { name: "Search the sites" });
    const siteToggles = live.getByRole("group", { name: "Sites to search" });
    for (const name of ["FanFiction.net", "AO3"]) {
      const toggle = siteToggles.getByRole("button", { name, exact: true });
      if (await toggle.count() && (await toggle.getAttribute("aria-pressed")) === "true") await toggle.click();
    }
    await expect(siteToggles.getByRole("button", { name: "Royal Road", exact: true })).toHaveAttribute("aria-pressed", "true");
    await live.getByLabel("Search the source sites").fill("mother of learning");
    await live.getByRole("button", { name: "Search", exact: true }).click();
    await expect(live.getByText(/\d+ results · page 1/)).toBeVisible({ timeout: 60_000 });

    // Bulk import of a pasted Royal Road URL (Library → Add story → Import).
    await page.goto("/library");
    await page.getByRole("button", { name: "Add story" }).click();
    const addSheet = page.getByRole("dialog", { name: "Add story" });
    await addSheet.getByRole("tab", { name: "Import" }).click();
    const importForm = addSheet.getByRole("region", { name: "Import stories" });
    await importForm.getByLabel("Links or page text").fill(importUrl);
    await importForm.getByRole("button", { name: "Start import" }).click();
    await expect(importForm.getByRole("region", { name: "Recent imports" })).toBeVisible({ timeout: 30_000 });
    await page.keyboard.press("Escape");

    // Story page (old library URL redirects to /story/:id): notes, shelves, offline control.
    await page.goto(`/library/${libraryId}/novels/${novelId}`);
    await expect(page).toHaveURL(/\/story\/\d+\?copy=/);
    await page.getByRole("tab", { name: "My notes" }).click();
    await expect(page.getByRole("heading", { name: "Your notes" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Your rating" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Shelves" })).toBeVisible();
    await page.getByRole("tab", { name: "Chapters" }).click();
    await expect(page.getByRole("button", { name: "Save next 10 offline" })).toBeVisible();

    // Reader: chapter drawer, paged mode, author's notes setting (Text settings sheet).
    await page.goto(readerPath!);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Chapters", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Chapters" })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Text settings" }).click();
    const settings = page.getByRole("dialog", { name: "Text settings" });
    await settings.getByRole("radiogroup", { name: "Reading mode" }).getByRole("radio", { name: "Pages" }).click();
    await expect(page.getByText(/^Page \d+ of \d+/)).toBeVisible();
    await settings.getByRole("radiogroup", { name: "Reading mode" }).getByRole("radio", { name: "Scroll" }).click();
    const notes = settings.getByRole("radiogroup", { name: "Author’s notes" });
    await notes.getByRole("radio", { name: "Show" }).click();
    await expect(notes.getByRole("radio", { name: "Show" })).toHaveAttribute("aria-checked", "true");
    await notes.getByRole("radio", { name: "Collapse" }).click();
    await page.keyboard.press("Escape");

    // Updates (old /activity redirects): New chapters, Downloads, Problems.
    await page.goto("/activity");
    await expect(page).toHaveURL(/\/updates/);
    await expect(page.getByRole("heading", { name: "Updates", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: /New chapters/ })).toBeVisible();
    await page.getByRole("tab", { name: "Downloads" }).click();

    // Settings (old /account redirects): e-reader app password created and revoked.
    await page.goto("/account");
    await expect(page).toHaveURL(/\/settings\/account/);
    await page.goto("/settings/ereaders");
    await expect(page.getByRole("heading", { name: "E-readers", level: 1 })).toBeVisible();
    const device = `e2e-${Date.now()}`;
    const appPasswordForm = page.locator("form", { has: page.getByRole("button", { name: "Create app password" }) });
    await appPasswordForm.getByLabel("Device name").fill(device);
    await appPasswordForm.getByRole("button", { name: "Create app password" }).click();
    await expect(page.getByText("It is shown only once", { exact: false })).toBeVisible();
    const row = page.getByRole("listitem").filter({ hasText: device });
    await row.getByRole("button", { name: "Revoke" }).click();
    await expect(row).toHaveCount(0);

    await page.goto("/notifications");
    await expect(page.getByRole("heading", { name: "This device" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Other apps and services" })).toBeVisible();

    await page.goto("/hidden-content");
    await expect(page.getByRole("heading", { name: "Hidden content", level: 1 })).toBeVisible();

    expect(errors).toEqual([]);
  });
});
