import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,
  testMatch: "**/story-audio-exports.spec.ts",
  use: { ...base.use, baseURL: "http://127.0.0.1:4188", channel: undefined, video: "off" },
  reporter: "line",
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], channel: undefined } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], channel: undefined } },
    { name: "webkit", use: { ...devices["Desktop Safari"], channel: undefined } },
  ],
  webServer: { command: "node e2e/exports-vite-server.mjs", url: "http://127.0.0.1:4188", reuseExistingServer: false, timeout: 30_000 },
});
