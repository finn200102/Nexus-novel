import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,testMatch:"**/saved-searches.spec.ts",reporter:"line",workers:1,
  outputDir:"/tmp/nexus-saved-searches-results",
  use:{...base.use,baseURL:"http://127.0.0.1:4199",channel:undefined,video:"off"},
  projects:[{name:"chromium",use:{...devices["Desktop Chrome"],channel:undefined}},{name:"firefox",use:{...devices["Desktop Firefox"],channel:undefined}},{name:"webkit",use:{...devices["Desktop Safari"],channel:undefined}}],
  webServer:{command:"node e2e/saved-searches-vite-server.mjs",url:"http://127.0.0.1:4199",reuseExistingServer:false,timeout:30_000},
});
