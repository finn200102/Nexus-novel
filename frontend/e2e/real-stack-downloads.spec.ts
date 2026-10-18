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
    test.setTimeout(240_000);
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
    await page.getByLabel("Username").fill(username!);
    await page.getByLabel(/^Password/).fill(password!);
    // Observe the home request caused by sign-in. Navigating again while it
    // completes can discard its response body in Chromium.
    const librariesResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "GET" && /\/library\/?$/.test(response.url()),
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).not.toHaveURL(/\/login(?:$|\?)/);

    // The home page loads the authenticated user's libraries. Reuse that response
    // so the test does not manufacture or mutate a library just for its fixture.
    const librariesResponse = await librariesResponsePromise;
    expect(librariesResponse.ok(), await librariesResponse.text()).toBeTruthy();
    const libraries = (await librariesResponse.json()) as Array<{ id: number }>;
    expect(libraries.length, "The authenticated user needs at least one library.").toBeGreaterThan(0);
    const libraryId = libraries[0].id;

    await page.goto(`/library/${libraryId}`);
    await page.getByRole("button", { name: "Add story", exact: true }).click();
    await page.getByLabel("Story link", { exact: true }).fill(fixtureUrl);

    const importResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/novel\/?$/.test(response.url()),
    );
    await page.getByRole("button", { name: "Add to library" }).click();
    const importResponse = await importResponsePromise;
    expect(importResponse.status(), await importResponse.text()).toBeLessThan(500);
    expect(importResponse.ok(), await importResponse.text()).toBeTruthy();
    const novel = (await importResponse.json()) as { id: number };
    expect(novel.id).toBeTruthy();

    // The old library URL redirects to the story page; chapters live in the Chapters tab.
    await page.goto(`/library/${libraryId}/novels/${novel.id}?tab=chapters`);
    const rows = page.locator(".story-chapter");

    // Metadata/chapter creation is asynchronous after import. Reloading the story
    // page gives us the same visible state a user sees while keeping the wait bounded.
    await expect
      .poll(
        async () => {
          await page.reload();
          await rows.first().waitFor({ state: "visible", timeout: 4_000 }).catch(() => undefined);
          return (await rows.count()) > 0 ? "READY" : "NO_CHAPTER";
        },
        { timeout: 120_000, intervals: [2_000, 4_000, 8_000] },
      )
      .toBe("READY");

    // The fixture manifest intentionally leaves chapters missing. Select the
    // first row that exposes the real UI download/retry control so an already
    // present chapter cannot make this acceptance test skip the request.
    const firstChapter = rows.filter({ has: page.getByRole("button", { name: /Download|Retry/ }) }).first();
    await expect(firstChapter, "The imported fixture needs a downloadable chapter row.").toBeVisible();
    const targetChapter = await firstChapter.getAttribute("data-chapter");
    expect(targetChapter).toMatch(/^\d+$/);

    await firstChapter.getByRole("button", { name: /Download|Retry/ }).click();
    await expect
      .poll(() => downloadResponses.length, { timeout: 15_000 })
      .toBeGreaterThan(0);
    expect(downloadResponses.at(-1)?.status).toBeLessThan(500);

    const target = page.locator(`.story-chapter[data-chapter="${targetChapter}"]`);
    await expect
      .poll(
        async () => {
          await page.reload();
          await target.waitFor({ state: "visible", timeout: 4_000 }).catch(() => undefined);
          return (await target.getAttribute("data-status")) || "UNKNOWN";
        },
        { timeout: 180_000, intervals: [2_000, 4_000, 8_000] },
      )
      .toMatch(/^(PRESENT|FAILED)$/);

    const finalStatus = await target.getAttribute("data-status");
    expect(terminalStatuses.has(finalStatus || ""), `Unexpected final chapter status: ${finalStatus}`).toBeTruthy();
    expect(finalStatus, "The deterministic permitted source fixture must produce readable content.").toBe("PRESENT");
    expect(downloadResponses.some((response) => response.status >= 500), downloadResponses.map((response) => `${response.status} ${response.url}`).join("\n")).toBeFalsy();
    await page.goto(`/library/${libraryId}/novels/${novel.id}/${targetChapter}`);
    await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByText(/1 illustration could not be saved for offline reading/)).toBeVisible();
    await page.getByRole("button", { name: "Open illustration: Fixture island map" }).click();
    const viewer = page.getByRole("dialog", { name: "Chapter illustration" });
    await expect(viewer).toBeVisible();
    await expect.poll(() => viewer.getByRole("img").evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1);
    await page.keyboard.press("Escape");
    await page.goto("/offline");
    const offlineStory = page.getByRole("region", { name: /^Offline files for / }).first();
    await offlineStory.locator("summary").click();
    await expect(offlineStory.getByText("Saved", { exact: true })).toBeVisible();
    await expect(offlineStory.getByText("1 of 2 saved · incomplete · 1 missing", { exact: true })).toBeVisible();
  });
});
