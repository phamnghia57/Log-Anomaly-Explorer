import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Generate ephemeral test credentials once; workers inherit them. Never use deployment secrets.
process.env.AUTH_E2E_USERNAME = "integration-admin";
process.env.AUTH_E2E_PASSWORD ??= randomBytes(32).toString("base64url");
process.env.AUTH_E2E_SECRET ??= randomBytes(48).toString("base64url");

export default defineConfig({
  testDir: "./e2e/integration",
  workers: 1,
  fullyParallel: false,
  projects: base.projects?.map((project) => ({ ...project,
    use: { ...project.use, channel: process.env.CI ? undefined : "chrome" },
  })),
  use: { baseURL: "http://127.0.0.1:5174", trace: "off", screenshot: "off", video: "off" },
  webServer: [
    {
      command: "python -m query-api.tests.auth_test_server",
      cwd: "..",
      url: "http://127.0.0.1:8023/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: { STORAGE_BACKEND: "memory", OTEL_EXPORTER_OTLP_ENDPOINT: "", JWT_EXPIRY_SECONDS: "4", USERS_INDEX: "auth-test-users", AUTH_COOKIE_SECURE: "false" },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 30_000,
      env: { VITE_API_BASE_URL: "/api", API_PROXY_TARGET: "http://127.0.0.1:8023" },
    },
  ],
});
