import { defineConfig, devices } from "@playwright/test";

// E2E chay voi backend thuc (VITE_API_BASE_URL trong .env.local) - khong
// mock API, xem web/README.md muc "Test". Can co du lieu that (it nhat 1
// cluster) de cac test duoi day pass - chay demo-app/scripts/trigger_fault_window.py
// hoac goi GET /demo/simulate-error truoc khi chay.
export default defineConfig({
  testDir: "./e2e",
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
