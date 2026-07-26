import { test, expect } from "@playwright/test";
import { installMockApi, authUser } from "./mockApi";

test.describe("Nexus authentication", () => {
  test("signs in without a library/signup fallback race", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await page.goto("/login");
    await page.getByLabel("Username:").fill(authUser.username);
    await page.getByLabel("Password:").fill(authUser.password);
    await page.getByRole("button", { name: "Login" }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4173/");
    await expect(page.getByRole("link", { name: /Nexus Novel dashboard/i })).toBeVisible();
    await expect(page).not.toHaveURL(/signup/);
  });

  test("shows invalid credentials and stays on login", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await page.goto("/login");
    await page.getByLabel("Username:").fill("invalid");
    await page.getByLabel("Password:").fill("wrong");
    await page.getByRole("button", { name: "Login" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Invalid credentials")).toBeVisible();
  });

  test("creates an account through the explicit signup flow", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await page.goto("/signup");
    await page.getByLabel("Username:").fill("new-e2e-user");
    await page.getByLabel("Password:").fill(authUser.password);
    await page.getByRole("button", { name: "Submit" }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4173/");
  });
});
