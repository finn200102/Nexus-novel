import { test, expect } from "./fixtures";

test("empty-library paths are explicit and a failed library load can be retried", async ({ signedInPage: page }) => {
  let failed = true, demoCalls = 0;
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/novel/") return failed ? route.fulfill({ status: 503, json: { detail: "Fixture outage" } }) : route.fulfill({ json: [] });
    if (path === "/onboarding/demo") {
      demoCalls++;
      return route.fulfill({ status: 503, json: { detail: "Fixture outage" } });
    }
    return route.fallback();
  });
  await page.goto("/");
  await expect(page.getByText(/Couldn’t load your library/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Try a demo story" })).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Retry library", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add your first story" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Import my library" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Browse Discover" })).toBeVisible();
  expect(demoCalls).toBe(0);
  await page.getByRole("button", { name: "Try a demo story" }).click();
  await expect(page.getByText(/Couldn’t open the demo/)).toBeVisible();
  expect(demoCalls).toBe(1);
});
