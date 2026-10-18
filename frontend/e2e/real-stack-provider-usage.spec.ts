import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";

test("private provider billing recovers a lost confirmation without charging twice", async ({ page, request }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_PROVIDER_USAGE_FIXTURE, "Requires the disposable acceptance stack.");
  test.setTimeout(120_000);
  const fixture = JSON.parse(readFileSync(process.env.NEXUS_E2E_PROVIDER_USAGE_FIXTURE!, "utf8"));
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login = page.waitForResponse(response => response.url().endsWith("/api/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const headers = { Authorization: `Bearer ${(await (await login).json()).access_token}` };
  await expect(page).not.toHaveURL(/\/login/);
  const base = `/api/reader/providers/${fixture.provider_id}/requests`;
  const listing = async () => {
    const response = await request.get(base, { headers });
    expect(response.ok()).toBeTruthy();
    expect(response.headers()["cache-control"]).toBe("private, no-store");
    return response.json();
  };
  expect((await request.get(`/api/reader/providers/${fixture.foreign_provider_id}/requests`, { headers })).status()).toBe(404);
  const inflight = await request.post(`${base}/${fixture.requests.pending}/reconcile`, { headers,
    data: { expected_revision: 0, operation_id: randomUUID(), actual_microusd: 0 } });
  expect(inflight.status()).toBe(409);
  expect((await inflight.json()).detail.code).toBe("request_inflight");
  expect((await listing()).accounting).toEqual({ budget_microusd: 1_000_000, used_microusd: 100, reserved_microusd: 260_033 });
  await page.goto("/settings/providers");
  const open = async () => {
    await page.getByText("Request accounting for Accounting recovery fixture", { exact: true }).first().click();
    const region = page.getByRole("region", { name: "Request accounting for Accounting recovery fixture", exact: true });
    await expect(region.getByRole("button", { name: "Refresh request accounting", exact: true })).toBeEnabled();
    await expect(region.getByText("Original model: reviewed-fixture-model · openai_compatible", { exact: true })).toHaveCount(3);
    return region;
  };
  let region = await open();
  await expect(page.getByText("PRIVATE_OTHER_READER_PROVIDER", { exact: true })).toHaveCount(0);
  await expect(region.getByRole("button", { name: `Reconcile request ${fixture.requests.pending}`, exact: true })).toHaveCount(0);
  await region.getByRole("button", { name: `Reconcile request ${fixture.requests.unknown}`, exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Reconcile provider request", exact: true });
  await dialog.getByLabel("Verified actual charge (USD)", { exact: true }).fill("0.012345");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Review reconciliation", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Confirm provider billing", exact: true });
  const submitted: Array<Record<string, unknown>> = [];
  let dropFirstConfirmation = true;
  await page.route(`**${base}/${fixture.requests.unknown}/reconcile`, async route => {
    submitted.push(route.request().postDataJSON());
    const response = await route.fetch();
    if (dropFirstConfirmation) { dropFirstConfirmation = false; await route.abort("failed"); }
    else await route.fulfill({ response });
  });
  await dialog.getByRole("button", { name: "Confirm reconciliation", exact: true }).click();
  await expect(region.getByText("A recorded reconciliation needs confirmation. Other settlements are paused.", { exact: false })).toBeVisible();
  await expect.poll(async () => (await listing()).accounting.used_microusd).toBe(12_445);
  expect((await listing()).accounting).toEqual({ budget_microusd: 1_000_000, used_microusd: 12_445, reserved_microusd: 10_033 });
  await page.reload();
  region = await open();
  await region.getByRole("button", { name: "Review unconfirmed reconciliation", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Confirm provider billing", exact: true });
  await dialog.getByRole("button", { name: "Retry same reconciliation", exact: true }).click();
  await expect(region.getByText("Reconciliation confirmed. Current provider totals and request history are shown.", { exact: true })).toBeVisible();
  expect(submitted).toHaveLength(2);
  expect(submitted[1]).toEqual(submitted[0]);
  expect(submitted[0].actual_microusd).toBe(12_345);
  const final = await listing();
  expect(final.accounting).toEqual({ budget_microusd: 1_000_000, used_microusd: 12_445, reserved_microusd: 10_033 });
  expect(final.items.find((row: { request_key: string }) => row.request_key === fixture.requests.unknown).status).toBe("reconciled");
  const changedIntent = await request.post(`${base}/${fixture.requests.unknown}/reconcile`, { headers,
    data: { ...submitted[0], actual_microusd: 0 } });
  expect(changedIntent.status()).toBe(409);
  expect((await changedIntent.json()).detail.code).toBe("operation_id_reused");
  expect((await listing()).accounting).toEqual(final.accounting);
});
