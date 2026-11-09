import path from "node:path";
import { defineConfig, devices } from "../../../../../web/node_modules/@playwright/test/index.mjs";
const output = process.env.QUALITY_E2E_ARTIFACTS!;
export default defineConfig({
  testDir: path.resolve(process.cwd(), "e2e/integration"),
  testMatch: "assistant-undo.pw.ts", workers: 1, retries: 0, timeout: 45_000,
  reporter: [["list"], ["junit", { outputFile: path.join(output, "e2e.junit.xml") }]],
  outputDir: path.join(output, "playwright-output"),
  use: { baseURL: process.env.VT013_E2E_WEB_URL, trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
});
