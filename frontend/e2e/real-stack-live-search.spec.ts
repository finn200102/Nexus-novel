import { expect, test } from "@playwright/test";

test("catalog and successful sources remain usable while another source waits or fails", async ({ page }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real", "Requires the explicitly selected disposable source fixture.");
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/discover/all");
  await page.getByRole("tab", { name: "Search the sites", exact: true }).click();
  await expect(page.getByRole("group", { name: "Sites to search" }).getByText("Royal Road", { exact: true })).toBeVisible();

  // Preserve real service responses and delay only their browser delivery.
  // Catalog/FFN must be usable before this gate is released; a single merged
  // aggregate response cannot satisfy this scenario.
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let intercepted = false;
  await page.route("**/api/discovery/live/source?**", async route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("source_id") !== "royalroad") return route.continue();
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    intercepted = true;
    await held;
    await route.fulfill({ response });
  });
  try {
    const form = page.getByRole("search", { name: "Search the sites", exact: true });
    await form.getByRole("searchbox").fill("nexus progressive fixture");
    await form.getByRole("button", { name: "Search", exact: true }).click();
    const catalog = page.getByRole("region", { name: "Local catalog results", exact: true });
    const ffn = page.getByRole("region", { name: "FanFiction.net results", exact: true });
    const rr = page.getByRole("region", { name: "Royal Road results", exact: true });
    const ao3 = page.getByRole("region", { name: /(?:AO3|Archive of Our Own) results/ });
    await expect(catalog.getByText(/results on page 1/)).toBeVisible();
    await expect(ffn.getByRole("link", { name: /FFN Fixture Story/ })).toBeVisible();
    await expect(ffn.getByRole("button", { name: "Add FFN Fixture Story", exact: true })).toBeEnabled();
    await expect(ao3.getByRole("button", { name: /^Retry / })).toBeVisible();
    await expect.poll(() => intercepted).toBe(true);
    await expect(rr.getByText("Asking Royal Road…", { exact: true })).toBeVisible();
    await expect(rr.getByRole("link")).toHaveCount(0);
    release();
    await expect(rr.getByRole("link", { name: /Royal Road Fixture Story/ })).toBeVisible();
    await expect(ffn.getByRole("link", { name: /FFN Fixture Story/ })).toBeVisible();
    await expect(page.getByText(/Search complete/)).toBeVisible();
  } finally {
    release();
  }
});
