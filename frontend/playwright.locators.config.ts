import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({ ...base,
  testMatch: "**/text-locators.spec.ts",
  use: { ...base.use, channel: undefined },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], channel: undefined } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], channel: undefined } },
    { name: "webkit", use: { ...devices["Desktop Safari"], channel: undefined } },
  ],
});
