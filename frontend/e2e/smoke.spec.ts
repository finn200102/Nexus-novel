import { test, expect } from "./fixtures";

test.describe("Nexus smoke workflows", () => {
  test("signs in and loads the library", async ({ signedInPage }) => {
    await signedInPage.goto("/library");
    await expect(signedInPage).toHaveURL(/\/library/);
    await expect(signedInPage.locator("body")).not.toContainText("Welcome back");
  });

  test("metadata outage leaves a usable error state", async ({ signedInPage }) => {
    await signedInPage.route("**/api/operations/summary**", (route) => route.abort("timedout"));
    await signedInPage.goto("/operations");
    await expect(signedInPage).toHaveURL(/\/admin\/status/);
    await expect(signedInPage.getByRole("heading", { name: "Status", exact: true })).toBeVisible();
  });

  test("catalog page renders capability-driven controls", async ({ signedInPage }) => {
    await signedInPage.goto("/scrape-jobs");
    await expect(signedInPage.getByRole("heading", { name: "Catalog jobs" })).toBeVisible();
    await expect(signedInPage.getByRole("button", { name: /custom url list/i })).toBeVisible();
    await expect(signedInPage.getByRole("button", { name: /^crossover$/i })).toBeVisible();
  });
});
