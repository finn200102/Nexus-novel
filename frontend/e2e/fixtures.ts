import { test as base, expect, Page } from "@playwright/test";
import { authUser, installMockApi } from "./mockApi";

export const test = base.extend<{ signedInPage: Page }>({
  signedInPage: async ({ page }, use) => {
    await installMockApi(page, { admin: true });
    await page.goto("/login");
    await page.getByLabel(/username/i).fill(process.env.NEXUS_E2E_USER || authUser.username);
    await page.getByLabel(/password/i).fill(process.env.NEXUS_E2E_PASSWORD || authUser.password);
    await page.getByRole("button", { name: /login|sign in/i }).click();
    await expect(page).not.toHaveURL(/login|signup/);
    await use(page);
  },
});

export { expect };
