import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }], ["line"]],
  use: {
    baseURL: process.env.NEXUS_E2E_BASE_URL || "http://127.0.0.1:4173",
    channel: process.env.NEXUS_E2E_CHANNEL || "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // NEXUS_E2E_VIDEO=off skips recording where the ffmpeg build is not installed.
    video: process.env.NEXUS_E2E_VIDEO === "off" ? "off" : "retain-on-failure",
    // The production PWA service worker can intercept fetches before the test
    // fixture router sees them. Acceptance tests must use their deterministic
    // API fixtures rather than a persisted browser cache.
    serviceWorkers: "block",
    navigationTimeout: 15_000,
    actionTimeout: 10_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Local E2E runs use Vite and intercepted API responses. Docker acceptance
  // keeps using the separately configured stack and disables this server.
  webServer: process.env.NEXUS_E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1 --port 4173",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
});
