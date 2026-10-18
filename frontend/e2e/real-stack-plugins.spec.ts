import { test, expect } from "@playwright/test";

test("administrator previews and pins a signed source, rejects unsigned data, and can disable it", async ({ page }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_PLUGIN_PACKAGE, "Requires an isolated real stack and disposable signed package.");
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/admin/plugins");
  await page.getByLabel("Signed source package").setInputFiles({ name: "unsigned.zip", mimeType: "application/zip", buffer: Buffer.from("unsigned package") });
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "Install this version" })).toHaveCount(0);
  await page.getByLabel("Signed source package").setInputFiles(process.env.NEXUS_E2E_PLUGIN_PACKAGE!);
  await expect(page.getByText("5 fixture checks passed.")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Install this version" }).click();
  await expect(page.getByRole("status")).toHaveText("Source package installed.");
  await page.getByRole("button", { name: "Versions", exact: true }).click();
  await expect(page.getByText("1.1.0 · Current")).toBeVisible();
  await page.getByRole("button", { name: "Disable", exact: true }).click();
  await expect(page.getByRole("button", { name: "Enable", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Enable", exact: true }).click();
  await expect(page.getByRole("button", { name: "Disable", exact: true })).toBeVisible();
});
