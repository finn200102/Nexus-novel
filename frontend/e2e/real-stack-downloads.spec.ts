import { test, expect } from "@playwright/test";

const realStack = process.env.NEXUS_E2E_MODE === "real";
const username = process.env.NEXUS_E2E_USER;
const password = process.env.NEXUS_E2E_PASSWORD;

// Keep the default stable so a real-stack run exercises the same source every time.
// Operators can point the test at a smaller/private fixture without changing the spec.
const fixtureUrl =
  process.env.NEXUS_E2E_FFN_URL ||
  "https://www.fanfiction.net/s/fixture-story/1/deterministic-fixture";

const terminalStatuses = new Set(["PRESENT", "FAILED"]);

test.describe("Nexus real-stack chapter downloads", () => {
  test.skip(!realStack, "Set NEXUS_E2E_MODE=real to run against the configured API.");

  test("imports a deterministic FFN fixture and reaches a visible terminal chapter state", async ({ page }) => {
    test.skip(
      !username || !password,
      "Real-stack mode requires NEXUS_E2E_USER and NEXUS_E2E_PASSWORD.",
    );

    const downloadResponses: Array<{ status: number; url: string }> = [];
    page.on("response", (response) => {
      if (/\/chapter\/download\//.test(response.url())) {
        downloadResponses.push({ status: response.status(), url: response.url() });
      }
    });

    await page.goto("/login");
    await page.getByLabel("Username:").fill(username!);
    await page.getByLabel("Password:").fill(password!);
    await page.getByRole("button", { name: "Login" }).click();
    await expect(page).not.toHaveURL(/\/login(?:$|\?)/);

    // The home page loads the authenticated user's libraries. Reuse that response
    // so the test does not manufacture or mutate a library just for its fixture.
    const librariesResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" && /\/library\/?$/.test(response.url()),
    );
    await page.goto("/");
    const librariesResponse = await librariesResponsePromise;
    expect(librariesResponse.ok(), await librariesResponse.text()).toBeTruthy();
    const libraries = (await librariesResponse.json()) as Array<{ id: number }>;
    expect(libraries.length, "The authenticated user needs at least one library.").toBeGreaterThan(0);
    const libraryId = libraries[0].id;

    await page.goto(`/library/${libraryId}`);
    await page.getByRole("button", { name: "Add novel" }).click();
    await page.getByLabel("Novel URL").fill(fixtureUrl);

    const importResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/novel\/?$/.test(response.url()),
    );
    await page.getByRole("button", { name: "Add to library" }).click();
    const importResponse = await importResponsePromise;
    expect(importResponse.status(), await importResponse.text()).toBeLessThan(500);
    expect(importResponse.ok(), await importResponse.text()).toBeTruthy();
    const novel = (await importResponse.json()) as { id: number };
    expect(novel.id).toBeTruthy();

    await page.goto(`/library/${libraryId}/novels/${novel.id}`);

    // Metadata/chapter creation is asynchronous after import. Reloading the detail
    // page gives us the same visible state a user sees while keeping the wait bounded.
    await expect
      .poll(
        async () => {
          const chapter = page.locator(".chapter-item").first();
          if (!(await chapter.count())) return "NO_CHAPTER";
          return (await chapter.locator(".chapter-status").textContent())?.trim() || "UNKNOWN";
        },
        { timeout: 120_000, intervals: [2_000, 4_000, 8_000] },
      )
      .not.toBe("NO_CHAPTER");

    // The fixture manifest intentionally leaves chapters missing. Select the
    // first row that exposes the real UI download/retry control so an already
    // present chapter cannot make this acceptance test skip the request.
    const firstChapter = page
      .locator(".chapter-item")
      .filter({ has: page.locator("button") })
      .first();
    await expect(firstChapter, "The imported fixture needs a downloadable chapter row.").toBeVisible();
    const targetChapterLabel = ((await firstChapter.locator(".chapter-number").textContent()) || "").trim();
    expect(targetChapterLabel).toMatch(/^Chapter\s+\d+/);

    await firstChapter.getByRole("button", { name: /Download|Retry/ }).click();
    await expect
      .poll(() => downloadResponses.length, { timeout: 15_000 })
      .toBeGreaterThan(0);
    expect(downloadResponses.at(-1)?.status).toBeLessThan(500);

    await expect
      .poll(
        async () => {
          await page.reload();
          const status = page
            .locator(".chapter-item")
            .filter({ hasText: targetChapterLabel })
            .locator(".chapter-status");
          return (await status.textContent())?.trim() || "UNKNOWN";
        },
        { timeout: 180_000, intervals: [2_000, 4_000, 8_000] },
      )
      .toSatisfy((status: string) => terminalStatuses.has(status));

    const finalStatus = (await page
      .locator(".chapter-item")
      .filter({ hasText: targetChapterLabel })
      .locator(".chapter-status")
      .textContent())?.trim();
    expect(terminalStatuses.has(finalStatus || ""), `Unexpected final chapter status: ${finalStatus}`).toBeTruthy();
    expect(downloadResponses.some((response) => response.status >= 500), downloadResponses.map((response) => `${response.status} ${response.url}`).join("\n")).toBeFalsy();
  });
});
