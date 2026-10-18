import { expect, test } from "@playwright/test";

test("reviewed plugin catalog survives a lost acknowledgement and imports query-distinct works once", async ({ page, request }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_PLUGIN_PACKAGE, "Requires the explicitly selected disposable signed source and fixture transport.");
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login = page.waitForResponse(response => response.url().endsWith("/api/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const headers = { Authorization: `Bearer ${(await (await login).json()).access_token}` };
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/admin/jobs");
  const workspace = page.getByRole("region", { name: "Scheduled source packages", exact: true });
  await expect(workspace.getByLabel("Scheduled source package")).toBeVisible();
  await workspace.getByLabel("Scheduled source package").selectOption("plugin-reference-author-serial");
  await workspace.getByLabel("Package job name").fill("Plugin catalog acceptance");
  await workspace.getByLabel("Result limit", { exact: true }).fill("10");
  await workspace.getByLabel("Maximum pages", { exact: true }).fill("2");
  await workspace.getByLabel("Pages per run", { exact: true }).fill("2");
  const previewResponse = page.waitForResponse(response => response.url().endsWith("/api/catalog-scrapes/preview") && response.request().method() === "POST", { timeout: 15_000 });
  await workspace.getByRole("button", { name: "Preview source package job", exact: true }).click();
  expect((await previewResponse).ok()).toBeTruthy();
  await expect(workspace.getByRole("heading", { name: "Review package job", exact: true })).toBeVisible();
  await expect(workspace.getByText(/2 first-page matches/)).toBeVisible();

  let createBody: Record<string, unknown> | undefined;
  let acknowledged: Record<string, unknown> | undefined;
  let attempts = 0;
  // Execute the actual server write, but lose its first browser response.
  // A retry must replay the persisted receipt, not create a second definition.
  await page.route("**/api/catalog-scrapes", async route => {
    if (route.request().method() !== "POST") return route.continue();
    attempts += 1;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    if (!createBody) createBody = body;
    else expect(body).toEqual(createBody);
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    if (!acknowledged) acknowledged = await response.json();
    if (attempts === 1) return route.abort("failed");
    await route.fulfill({ response });
  });
  await workspace.getByRole("button", { name: "Create reviewed package job", exact: true }).click();
  await expect(workspace.getByRole("button", { name: "Retry plugin job confirmation", exact: true })).toBeEnabled();
  await workspace.getByRole("button", { name: "Retry plugin job confirmation", exact: true }).click();
  await expect(workspace.getByText(/Action confirmed/)).toBeVisible();
  expect(attempts).toBe(2);
  expect(createBody?.operation_id).toBeTruthy();
  const definition = acknowledged!.definition as { id: number; query: { source_options: { plugin_version: string; plugin_digest: string } } };
  const job = acknowledged!.job as { id: string };
  expect(definition.query.source_options.plugin_version).toBe("1.1.0");
  expect(definition.query.source_options.plugin_digest).toMatch(/^[0-9a-f]{64}$/);
  await expect.poll(async () => {
    const response = await request.get(`/api/catalog-scrapes/jobs/${job.id}`, { headers });
    expect(response.ok()).toBeTruthy();
    return (await response.json()).status;
  }, { timeout: 90_000, intervals: [1000, 2000] }).toBe("completed");
  await expect.poll(async () => {
    const response = await request.get(`/api/catalog-scrapes/jobs/${job.id}/candidates`, { headers });
    expect(response.ok()).toBeTruthy();
    const rows = await response.json() as { source_url: string; candidate_status: string; import_job_id: string }[];
    expect(rows.map(row => row.source_url).sort()).toEqual([
      "https://example.org/plugin-story?p=1", "https://example.org/plugin-story?p=2",
    ]);
    expect(new Set(rows.map(row => row.import_job_id)).size).toBe(2);
    return rows.map(row => row.candidate_status).sort();
  }, { timeout: 90_000, intervals: [1000, 2000] }).toEqual(["imported", "imported"]);
  const replay = await request.post("/api/catalog-scrapes", { headers, data: createBody });
  expect(replay.ok()).toBeTruthy();
  expect(await replay.json()).toEqual(acknowledged);
  const definitions = await request.get("/api/catalog-scrapes", { headers });
  expect(definitions.ok()).toBeTruthy();
  expect((await definitions.json() as { name: string; id: number }[]).filter(row => row.name === "Plugin catalog acceptance").map(row => row.id)).toEqual([definition.id]);
});

test("editing a paused plugin definition preserves its calendar and does not launch a run", async ({ page, request }) => {
  test.skip(process.env.NEXUS_E2E_MODE !== "real" || !process.env.NEXUS_E2E_PLUGIN_PACKAGE, "Requires the explicitly selected disposable signed source and fixture transport.");
  test.setTimeout(90_000);
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login = page.waitForResponse(response => response.url().endsWith("/api/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const headers = { Authorization: `Bearer ${(await (await login).json()).access_token}` };
  await expect(page).not.toHaveURL(/\/login/);
  const capabilities = await request.get("/api/catalog-scrapes/capabilities", { headers });
  expect(capabilities.ok()).toBeTruthy();
  const source = (await capabilities.json()).sources.find((row: { plugin_id?: string }) => row.plugin_id === "reference-author-serial");
  expect(source).toBeTruthy();
  const query = { version: 2, mode: "newest", intent: "newest", run_mode: "scheduled_check", limit: 10, max_pages: 2, max_pages_per_run: 2, daily_request_budget: 20,
    source_options: { plugin_id: source.plugin_id, plugin_digest: source.plugin_digest, plugin_version: source.plugin_version, operation: "listings" } };
  const preview = await request.post("/api/catalog-scrapes/preview", { headers, data: { site: source.site, query }, timeout: 15_000 });
  expect(preview.ok()).toBeTruthy();
  const reviewed = await preview.json();
  const calendar = { kind: "weekly", timezone: "Europe/Berlin", weekday: 1, time_of_day: "03:15" };
  const created = await request.post("/api/catalog-scrapes", { headers, data: { site: source.site, query: reviewed.query,
    name: "Plugin edit acceptance", enabled: false, schedule: calendar, review_token: reviewed.review_token,
    operation_id: `acceptance-edit-${Date.now()}` } });
  expect(created.ok()).toBeTruthy();
  const original = await created.json();
  expect(original.job).toBeNull();
  expect(original.definition.last_job_id).toBeNull();
  await page.goto("/admin/jobs");
  const workspace = page.getByRole("region", { name: "Scheduled source packages", exact: true });
  await workspace.getByRole("button", { name: "Edit package job Plugin edit acceptance", exact: true }).click();
  await expect(workspace.getByLabel("Package schedule", { exact: true })).toHaveValue("preserve");
  await workspace.getByLabel("Package job name").fill("Edited plugin acceptance");
  await workspace.getByLabel("Listing requests per day", { exact: true }).fill("21");
  const previewResponse = page.waitForResponse(response => response.url().endsWith("/api/catalog-scrapes/preview") && response.request().method() === "POST", { timeout: 15_000 });
  await workspace.getByRole("button", { name: "Preview source package job", exact: true }).click();
  expect((await previewResponse).ok()).toBeTruthy();
  let attempts = 0;
  let updateBody: Record<string, unknown> | undefined;
  await page.route(`**/api/catalog-scrapes/${original.definition.id}`, async route => {
    if (route.request().method() !== "PATCH") return route.continue();
    attempts += 1;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    if (!updateBody) updateBody = body;
    else expect(body).toEqual(updateBody);
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    if (attempts === 1) return route.abort("failed");
    await route.fulfill({ response });
  });
  await workspace.getByRole("button", { name: "Save reviewed package changes", exact: true }).click();
  await expect(workspace.getByRole("button", { name: "Retry plugin job confirmation", exact: true })).toBeEnabled();
  await page.reload();
  await workspace.getByRole("button", { name: "Retry plugin job confirmation", exact: true }).click();
  await expect(workspace.getByText(/Action confirmed/)).toBeVisible();
  expect(attempts).toBe(2);
  expect(updateBody).not.toHaveProperty("schedule");
  expect(updateBody).not.toHaveProperty("schedule_interval_minutes");
  const result = await request.get(`/api/catalog-scrapes/${original.definition.id}`, { headers });
  expect(result.ok()).toBeTruthy();
  expect(await result.json()).toMatchObject({ id: original.definition.id, name: "Edited plugin acceptance", enabled: false,
    schedule: calendar, last_job_id: null, query: { daily_request_budget: 21 } });
  const active = await request.get(`/api/catalog-scrapes/${original.definition.id}/active-jobs?limit=1&offset=0`, { headers });
  expect(active.ok()).toBeTruthy();
  expect(await active.json()).toMatchObject({ items: [], total: 0, offset: 0, limit: 1 });
});
