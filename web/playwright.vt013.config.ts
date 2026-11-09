import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The evidence runner owns all services. Never reuse a project/shared backend.
export default defineConfig({
  testDir: "./e2e/integration",
  // .pw.ts is opt-in: existing auth integration must not collect this scenario.
  testMatch: "assistant-undo.pw.ts",
  workers: 1,
  retries: 0,
  fullyParallel: false,
  timeout: 45_000,
  reporter: [["list"], ["junit", { outputFile: path.resolve(import.meta.dirname,
    "../docs/assignments/VT-013/evidence/frontend/e2e.junit.xml") }]],
  outputDir: path.resolve(import.meta.dirname, "../docs/assignments/VT-013/evidence/frontend/e2e-output"),
  use: { baseURL: process.env.VT013_E2E_WEB_URL, trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
});
