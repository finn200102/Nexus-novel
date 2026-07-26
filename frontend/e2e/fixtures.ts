import { test as base, expect, Page } from "@playwright/test";

export const test = base.extend<{ signedInPage: Page }>({
  signedInPage: async ({ page }, use) => {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill(process.env.NEXUS_E2E_USER || "user");
    await page.getByLabel(/password/i).fill(process.env.NEXUS_E2E_PASSWORD || "1234");
    const libraryRequest = page.waitForResponse(
      (response) =>
        response.url().includes("/api/library/") &&
        response.request().method() === "GET",
      { timeout: 10_000 }
    );
    await page.getByRole("button", { name: /login|sign in/i }).click();
    const libraryResponse = await libraryRequest;
    expect(libraryResponse.status()).toBe(200);
    if (/login/.test(page.url())) {
      await page.goto("/signup");
      const username = `e2e-${Date.now()}`;
      await page.getByLabel(/username/i).fill(username);
      await page.getByLabel(/password/i).fill("NexusE2E-1234");
      await page.getByRole("button", { name: /submit|sign up|create/i }).click();
    }
    await expect(page).not.toHaveURL(/login|signup/);
    await use(page);
  },
});

export { expect };
