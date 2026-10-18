import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  metadata: { productionOffline: true },
  testDir: "./e2e",
  testMatch: "production-offline.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4178",
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "npm run build && node e2e/offline-fixture-server.mjs",
    url: "http://127.0.0.1:4178",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
