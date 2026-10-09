import { test, expect } from "./fixtures";
import { installMockApi } from "./mockApi";

test.describe("catalog and operations resilience", () => {
  test("previews a crossover, creates a job, and exposes progress", async ({ signedInPage }) => {
    await signedInPage.goto("/scrape-jobs");
    await signedInPage.getByRole("button", { name: /^crossover$/i }).click();
    await signedInPage.getByRole("combobox", { name: "Fandom A" }).fill("Game of Thrones");
    await signedInPage.getByRole("combobox", { name: "Fandom B" }).fill("Harry Potter");
    await signedInPage.getByRole("button", { name: /preview results/i }).click();
    await expect(signedInPage.getByText("A Fixture Story")).toBeVisible();
    await expect(signedInPage.getByText(/1 ready to import/)).toBeVisible();
    await signedInPage.getByRole("button", { name: /create job from preview/i }).click();
    await expect(signedInPage.getByRole("heading", { name: "Job progress" })).toBeVisible();
    await expect(signedInPage.getByText(/Scanning page \d/).first()).toBeVisible();
    await expect(signedInPage.getByText("1", { exact: true }).first()).toBeVisible();
    // Candidates are listed for import; the per-candidate "Ignore" action was
    // removed from the page in 5b6c0be.
    await expect(signedInPage.getByRole("checkbox", { name: "Select A Fixture Story" })).toBeVisible();
  });

  test("keeps the catalog page usable after a preview timeout and recovers on retry", async ({ page }) => {
    await installMockApi(page, { admin: true, previewFailure: "timeout" });
    await page.goto("/login");
    await page.getByLabel("Username").fill("e2e-user");
    await page.getByLabel(/^Password/).fill("NexusE2E-1234");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.goto("/scrape-jobs");
    await page.getByRole("button", { name: /preview results/i }).click();
    await expect(page.getByText(/timed out|could not preview|could not reach the service/i)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Catalog jobs" })).toBeVisible();
    await page.getByRole("button", { name: /preview results/i }).click();
    await expect(page.getByText("A Fixture Story")).toBeVisible();
  });

  test("retains operations UI during metadata outage and supports retry/archive controls", async ({ signedInPage }) => {
    await signedInPage.goto("/operations");
    await expect(signedInPage.getByRole("heading", { name: "Status", exact: true })).toBeVisible();
    await expect(signedInPage.getByText("Source timed out")).toBeVisible();
    await expect(signedInPage.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(signedInPage.getByText("fanfiction · degraded")).toBeVisible();
    await signedInPage.getByRole("button", { name: "History" }).click();
    await expect(signedInPage.getByRole("heading", { name: "Archived catalog jobs" })).toBeVisible();
  });

  test("non-admin catalog API failure is shown as a permission error", async ({ page }) => {
    await installMockApi(page, { admin: false });
    await page.goto("/login");
    await page.getByLabel("Username").fill("e2e-user");
    await page.getByLabel(/^Password/).fill("NexusE2E-1234");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.goto("/scrape-jobs");
    await expect(page.getByText(/administrator access is required|permission/i)).toBeVisible();
  });
});
