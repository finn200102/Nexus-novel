import { test, expect, Page } from "@playwright/test";
import { installMockApi, authUser } from "./mockApi";

const signIn = async (page: Page, username = authUser.username) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel(/^Password/).fill(authUser.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
};

test.describe("Nexus authentication", () => {
  test("signs in without a library/signup fallback race", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await signIn(page);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page).not.toHaveURL(/signup/);
  });

  test("keeps no token in localStorage and restores the session after a reload", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await signIn(page);
    const stored = await page.evaluate(() => JSON.stringify({ ...window.localStorage }));
    expect(stored).not.toContain("e2e-token");

    await page.reload();
    await expect(page).toHaveURL("http://127.0.0.1:4173/");
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  });

  test("a revoked session is rejected and returns the reader to sign-in", async ({ page }) => {
    const api = await installMockApi(page, { admin: true });
    await signIn(page);

    api.revokeSessions();
    await page.goto("/downloads");

    await expect(page).toHaveURL(/\/login$/);
  });

  test("shows invalid credentials and stays on login", async ({ page }) => {
    await installMockApi(page, { admin: true });
    await page.goto("/login");
    await page.getByLabel("Username").fill("invalid");
    await page.getByLabel(/^Password/).fill("wrong");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Invalid credentials")).toBeVisible();
  });

  test("creates an account when sign-up is open", async ({ page }) => {
    await installMockApi(page, { admin: true, signupMode: "open" });
    await page.goto("/signup");
    await page.getByLabel("Username").fill("new-e2e-user");
    await page.getByLabel(/^Password/).fill(authUser.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4173/");
  });

  test("sign-up is closed once an administrator exists", async ({ page }) => {
    await installMockApi(page, { signupMode: "closed" });
    await page.goto("/signup");
    await expect(page.getByText(/new accounts are turned off/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Create account" })).toHaveCount(0);
  });

  test("an invite link lets a new reader sign up once", async ({ page }) => {
    const api = await installMockApi(page, { signupMode: "invite" });
    api.addInvite("welcome-code");

    await page.goto("/signup?invite=welcome-code");
    await expect(page.getByLabel("Invite code")).toHaveValue("welcome-code");
    await page.getByLabel("Username").fill("invited-reader");
    await page.getByLabel(/^Password/).fill(authUser.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4173/");

    await page.getByRole("button", { name: /invited-reader/ }).click();
    await page.getByRole("dialog", { name: "Account" }).getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/signup?invite=welcome-code");
    await page.getByLabel("Username").fill("second-try");
    await page.getByLabel(/^Password/).fill(authUser.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("This invite code is not valid.")).toBeVisible();
  });

  test("a password reset link sets a new password once", async ({ page }) => {
    const api = await installMockApi(page);
    api.addResetToken("one-time-token");

    await page.goto("/reset-password?token=one-time-token");
    await page.getByLabel("New password").fill("a-brand-new-password");
    await page.getByLabel("Repeat password").fill("a-brand-new-password");
    await page.getByRole("button", { name: "Set password" }).click();
    await expect(page).toHaveURL(/\/login\?reset=1$/);
    await expect(page.getByText(/password changed/i)).toBeVisible();

    await page.goto("/reset-password?token=one-time-token");
    await page.getByLabel("New password").fill("another-new-password");
    await page.getByLabel("Repeat password").fill("another-new-password");
    await page.getByRole("button", { name: "Set password" }).click();
    await expect(page.getByText(/invalid or has expired/i)).toBeVisible();
  });

  test("administrators manage sign-up, invites and reset links", async ({ page }) => {
    await installMockApi(page, { admin: true, signupMode: "closed" });
    await signIn(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Admin" }).click();
    await page.getByRole("navigation", { name: "Admin sections" }).getByRole("link", { name: "Users" }).click();
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();

    await page.getByLabel("Invite only").check();
    await expect(page.getByText("Sign-up setting saved")).toBeVisible();

    await page.getByRole("button", { name: /create invite/i }).click();
    await expect(page.getByText("fresh-invite-code")).toBeVisible();

    await page.getByTestId("user-row-second-reader").getByRole("button", { name: /reset link/i }).click();
    await expect(page.getByText(/reset-password\?token=reset-from-admin/)).toBeVisible();
  });

  test("readers do not see administrator navigation", async ({ page }) => {
    await installMockApi(page, { admin: false });
    await signIn(page);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Updates" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Admin" })).toHaveCount(0);
    await nav.getByRole("button", { name: new RegExp(authUser.username) }).click();
    await expect(page.getByRole("dialog", { name: "Account" }).getByRole("link", { name: "Settings" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  });
});
