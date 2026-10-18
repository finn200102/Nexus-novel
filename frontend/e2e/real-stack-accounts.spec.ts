import { test, expect, request as playwrightRequest, APIRequestContext, Browser, Page } from "@playwright/test";

// Account flows against a running stack (NEXUS_E2E_MODE=real). Needs an
// administrator in NEXUS_E2E_USER / NEXUS_E2E_PASSWORD. The test restores the
// sign-up mode and deletes the account it creates.
const realStack = process.env.NEXUS_E2E_MODE === "real";
const adminName = process.env.NEXUS_E2E_USER;
const adminPassword = process.env.NEXUS_E2E_PASSWORD;

const api = (path: string) => `/api${path}`;

const adminToken = async (request: APIRequestContext) => {
  const response = await request.post(api("/auth/login"), { data: { username: adminName, password: adminPassword } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).access_token as string;
};

const freshPage = async (browser: Browser): Promise<Page> => (await browser.newContext()).newPage();

const signUp = async (page: Page, path: string, username: string, password: string) => {
  await page.goto(path);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
};

test.describe("Nexus real-stack accounts", () => {
  test.skip(!realStack, "Set NEXUS_E2E_MODE=real to run against the configured API.");

  test("closed sign-up, invites, reset links and revoked sessions", async ({ browser, request }) => {
    test.skip(!adminName || !adminPassword, "Real-stack mode requires NEXUS_E2E_USER and NEXUS_E2E_PASSWORD.");
    const token = await adminToken(request);
    const headers = { Authorization: `Bearer ${token}` };
    const originalMode = (await (await request.get(api("/admin/settings"), { headers })).json()).signup_mode;
    const username = `e2e-invited-${Date.now()}`;
    let createdUserId: number | null = null;

    try {
      // Closed: the sign-up page says so and offers no form.
      await request.put(api("/admin/settings"), { headers, data: { signup_mode: "closed" } });
      const visitor = await freshPage(browser);
      await visitor.goto("/signup");
      await expect(visitor.getByText(/new accounts are turned off/i)).toBeVisible();

      // Invite only: an invite link works once.
      await request.put(api("/admin/settings"), { headers, data: { signup_mode: "invite" } });
      const invite = await (await request.post(api("/admin/invites"), { headers, data: { label: "e2e", max_uses: 1, expires_in_days: 1 } })).json();
      const invited = await freshPage(browser);
      await signUp(invited, `/signup?invite=${invite.code}`, username, "first-password-123");
      await expect(invited).not.toHaveURL(/signup|login/);
      const firstUseStarted = Date.now();
      await invited.goto("/");
      await expect(invited.getByRole("heading", { name: "Add your first story", exact: true })).toBeVisible();
      await invited.getByRole("button", { name: "Try a demo story", exact: true }).click();
      await expect(invited.getByRole("heading", { name: "An unexpected light", exact: true })).toBeVisible();
      await expect(invited.locator(".reader__content")).toContainText("Mara kept the last lighthouse");
      expect(Date.now() - firstUseStarted).toBeLessThan(300_000);
      await invited.goto("/");
      const users = await (await request.get(api("/admin/users"), { headers })).json();
      createdUserId = users.find((user: { username: string }) => user.username === username).id;

      const second = await freshPage(browser);
      await signUp(second, `/signup?invite=${invite.code}`, `${username}-2`, "first-password-123");
      await expect(second.getByText("This invite code is not valid.")).toBeVisible();

      // A logged-out refresh cookie is rejected.
      const cookies = await invited.context().cookies();
      const refreshCookie = cookies.find((cookie) => cookie.name === "nexus_refresh");
      expect(refreshCookie?.httpOnly).toBe(true);
      expect(refreshCookie?.sameSite).toBe("Strict");
      expect(await invited.evaluate(() => JSON.stringify({ ...window.localStorage }))).not.toContain("eyJ");
      // Sign out lives in the profile menu since the redesign.
      await invited.getByRole("button", { name: /Settings, theme, sign out/ }).click();
      await invited.getByRole("button", { name: "Sign out", exact: true }).click();
      await expect(invited).toHaveURL(/\/login/);
      const anonymous = await playwrightRequest.newContext({ baseURL: test.info().project.use.baseURL });
      const replay = await anonymous.post(api("/auth/refresh"), { headers: { Cookie: `nexus_refresh=${refreshCookie!.value}` } });
      expect(replay.status()).toBe(401);
      await anonymous.dispose();

      // Reset link: sets a new password once and ends existing sessions.
      const device = await freshPage(browser);
      await device.goto("/login");
      await device.getByLabel("Username").fill(username);
      await device.getByLabel(/^Password/).fill("first-password-123");
      await device.getByRole("button", { name: "Sign in" }).click();
      await expect(device).not.toHaveURL(/login/);
      const link = await (await request.post(api(`/admin/users/${createdUserId}/password-reset`), { headers, data: {} })).json();
      const resetter = await freshPage(browser);
      await resetter.goto(link.path);
      await resetter.getByLabel("New password").fill("second-password-456");
      await resetter.getByLabel("Repeat password").fill("second-password-456");
      await resetter.getByRole("button", { name: "Set password" }).click();
      await expect(resetter).toHaveURL(/\/login\?reset=1/);
      await device.reload();
      await expect(device).toHaveURL(/\/login/);
      await resetter.getByLabel("Username").fill(username);
      await resetter.getByLabel(/^Password/).fill("second-password-456");
      await resetter.getByRole("button", { name: "Sign in" }).click();
      await expect(resetter).not.toHaveURL(/login/);
    } finally {
      if (createdUserId !== null) await request.delete(api(`/admin/users/${createdUserId}`), { headers });
      await request.put(api("/admin/settings"), { headers, data: { signup_mode: originalMode } });
    }
  });
});
