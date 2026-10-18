import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";

const baseURL = process.env.NEXUS_E2E_BASE_URL || "http://127.0.0.1:4183";
export default defineConfig({
  ...base,
  testMatch: "**/audio-handoff.spec.ts",
  use: { ...base.use, baseURL, channel: undefined, video: "off" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], channel: undefined } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], channel: undefined } },
    { name: "webkit", use: { ...devices["Desktop Safari"], channel: undefined } },
  ],
  webServer: process.env.NEXUS_E2E_BASE_URL ? undefined : {
    command: "npm run dev -- --host 127.0.0.1 --port 4183",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
