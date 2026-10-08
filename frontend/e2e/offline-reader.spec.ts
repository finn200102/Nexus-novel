import { test, expect } from "@playwright/test";
import { authUser, installMockApi } from "./mockApi";

// The offline path needs the real service worker (app shell) and IndexedDB
// (chapter text), so this spec allows workers and mocks the API on the
// context, where worker-issued requests are visible.
test.use({ serviceWorkers: "allow" });

const LIBRARY_ID = 1;
const NOVEL_ID = 42;
const CHAPTERS = 12;

const novel = {
  id: NOVEL_ID,
  library_id: LIBRARY_ID,
  title: "Offline Fixture Story",
  author: "Fixture Author",
  url: "https://www.royalroad.com/fiction/42/offline-fixture-story",
  novel_site: "royalroad",
  description: "A story for the offline reader test.",
  chapters: [],
};

const chapterText = (n: number) => `Offline fixture text for chapter ${n}.`;

test("chapters made available offline open after an offline reload", async ({ page, context }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await installMockApi(context);
  // Later routes win over the generic mock.
  await context.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    const reply = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === `/novel/${NOVEL_ID}`) return reply(novel);
    if (path === `/chapter/${NOVEL_ID}`) {
      return reply(Array.from({ length: CHAPTERS }, (_, i) => ({
        id: 1000 + i + 1, novel_id: NOVEL_ID, chapter_number: i + 1, title: `Chapter ${i + 1}`, content_status: "PRESENT",
      })));
    }
    if (path === `/chapter/progress/${NOVEL_ID}`) return reply({ detail: "No progress" }, 404);
    const content = path.match(new RegExp(`^/chapter/content/library/${LIBRARY_ID}/${NOVEL_ID}/(\\d+)$`));
    if (content) {
      const n = Number(content[1]);
      return reply({ id: 1000 + n, novel_id: NOVEL_ID, chapter_number: n, title: `Chapter ${n}`, content: `<p>${chapterText(n)}</p>` });
    }
    if (path === "/shelves") return reply([]);
    if (path === `/personal/novels/${NOVEL_ID}`) {
      return reply({ novel_id: NOVEL_ID, notes: null, rating: null, user_tags: [], followed_categories: null, auto_download: false, keep_ahead: 5, shelf_ids: [] });
    }
    if (path === "/personal/tags") return reply({ tags: [] });
    if (path === `/chapter/annotations/${NOVEL_ID}`) return reply([]);
    return route.fallback();
  });

  await page.goto("/login");
  await page.getByLabel(/username/i).fill(authUser.username);
  await page.getByLabel(/password/i).fill(authUser.password);
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login|signup/);

  await page.goto(`/library/${LIBRARY_ID}/novels/${NOVEL_ID}`);
  const offline = page.getByRole("region", { name: "Offline reading" });
  await offline.getByRole("button", { name: "Next 10 chapters" }).click();
  await expect(offline).toContainText("Saved 10 chapters offline.");

  // Let the service worker take control and cache the app shell and modules.
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await page.goto(`/library/${LIBRARY_ID}/novels/${NOVEL_ID}/1`);
  await expect(page.getByText(chapterText(1))).toBeVisible();

  await context.setOffline(true);
  // Chapter 7 was never opened online, so only the offline store has it.
  await page.goto(`/library/${LIBRARY_ID}/novels/${NOVEL_ID}/7`);
  await expect(page.getByText(chapterText(7))).toBeVisible();
  await page.reload();
  await expect(page.getByText(chapterText(7))).toBeVisible();
  // The text came from the device, not from a (mocked) server response.
  await expect(page.getByText("Reading the saved copy on this device.")).toBeVisible();
  await context.setOffline(false);

  expect(pageErrors).toEqual([]);
});
