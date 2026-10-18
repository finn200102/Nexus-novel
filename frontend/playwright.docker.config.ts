import {join} from "node:path";
import config from "./playwright.config";

export default {
  ...config,
  outputDir: process.env.NEXUS_E2E_ARTIFACT_DIR ? join(process.env.NEXUS_E2E_ARTIFACT_DIR, "test-results") : "artifacts/docker-test-results",
  use: {
    ...config.use,
    baseURL: process.env.NEXUS_E2E_BASE_URL || "http://localhost:8180",
  },
  webServer: undefined,
};
