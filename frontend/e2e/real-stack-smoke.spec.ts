import { test, expect } from "@playwright/test";

const realStack = process.env.NEXUS_E2E_MODE === "real";
const username = process.env.NEXUS_E2E_USER;
const password = process.env.NEXUS_E2E_PASSWORD;

test.describe("Nexus real-stack smoke", () => {
  test.skip(!realStack, "Set NEXUS_E2E_MODE=real to run against the configured API.");

  test("authenticates through the running API and opens the library", async ({ page }) => {
    test.skip(!username || !password, "Real-stack mode requires NEXUS_E2E_USER and NEXUS_E2E_PASSWORD.");

    const apiFailures: string[] = [];
    page.on("requestfailed", (request) => {
      if (request.url().includes("/auth/") || request.url().includes("/library")) {
        apiFailures.push(`${request.method()} ${request.url()} — ${request.failure()?.errorText || "request failed"}`);
      }
    });

    await page.goto("/login");
    await page.getByLabel("Username:").fill(username!);
    await page.getByLabel("Password:").fill(password!);
    await page.getByRole("button", { name: "Login" }).click();

    await expect(page).not.toHaveURL(/\/login(?:$|\?)/);
    // A full reload drops the in-memory access token; the refresh cookie
    // must restore the session.
    await page.reload();
    await expect(page).not.toHaveURL(/\/login(?:$|\?)/);
    await page.getByRole("button", { name: "My library" }).click();
    await expect(page).toHaveURL(/\/library\/\d+/);
    expect(apiFailures, apiFailures.join("\n")).toEqual([]);
  });
});
