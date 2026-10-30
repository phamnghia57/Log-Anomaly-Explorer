import { defineConfig, devices } from "@playwright/test";

// login/auth specs mock API. Dashboard/incident specs dung backend thuc,
// can E2E_ADMIN_USERNAME/PASSWORD va it nhat 1 cluster (xem web/README.md).
export default defineConfig({
  testDir: "./e2e",
  testIgnore: "**/integration/**",
  fullyParallel: true,
  reporter: "html",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      // Dung Chrome co san tren may thay vi tai rieng Chromium cua Playwright.
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
