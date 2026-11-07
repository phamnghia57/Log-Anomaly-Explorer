import { defineConfig } from "@playwright/test";
import auth from "./playwright.auth-integration.config";

// The existing dashboard/incident specs use the same ephemeral real backend as auth.
process.env.E2E_ADMIN_USERNAME = process.env.AUTH_E2E_USERNAME;
process.env.E2E_ADMIN_PASSWORD = process.env.AUTH_E2E_PASSWORD;

export default defineConfig({
  ...auth,
  testDir: "./e2e",
  testIgnore: "**/integration/**",
});
