import config from "./playwright.config";

export default {
  ...config,
  use: {
    ...config.use,
    baseURL: process.env.NEXUS_E2E_BASE_URL || "http://localhost:8180",
  },
  webServer: undefined,
};
