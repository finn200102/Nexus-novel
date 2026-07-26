import { test as base, expect, Page } from "@playwright/test";

export const test = base.extend<{ signedInPage: Page }>({
  signedInPage: async ({ page }, use) => {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill(process.env.NEXUS_E2E_USER || "user");
    await page.getByLabel(/password/i).fill(process.env.NEXUS_E2E_PASSWORD || "1234");
    await page.getByRole("button", { name: /login|sign in/i }).click();
    await expect(page).not.toHaveURL(/login/);
    await use(page);
  },
});

export { expect };
