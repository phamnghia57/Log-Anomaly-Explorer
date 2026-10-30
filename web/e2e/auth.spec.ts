import { expect, test } from "@playwright/test";

const STORAGE_KEY = "log-anomaly-explorer.auth";
const cors = { "Access-Control-Allow-Origin": "*" };
const session = () => ({ token: "browser-test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });

test("deep link returns after login, navigation works, and logout blocks history access", async ({ page }, testInfo) => {
  const current = session();
  let searches = 0;
  await page.route("**/auth/login", (route) => route.fulfill({ json: current, headers: cors }));
  await page.route("**/search?*", (route) => {
    if (route.request().isNavigationRequest()) return route.continue();
    searches++;
    expect(route.request().headers().authorization).toBe(`Bearer ${current.token}`);
    return route.fulfill({ json: { total: 0, results: [] }, headers: cors });
  });
  await page.route(/\/clusters(?:\?.*)?$/, (route) => route.fulfill({ json: { total: 0, clusters: [] }, headers: cors }));
  await page.goto("/search?trace_id=abc#results");
  await expect(page).toHaveURL("/login");
  expect(searches).toBe(0);
  await page.getByLabel("Tên đăng nhập").fill("test-admin");
  await page.getByLabel("Mật khẩu").fill("test-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();

  await expect(page).toHaveURL("/search?trace_id=abc#results");
  await expect(page.locator("#trace_id")).toHaveValue("abc");
  await expect.poll(() => searches).toBeGreaterThanOrEqual(1);
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await expect(page.getByText("Tài khoản admin")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("admin-menu.png"), fullPage: true });
  await page.getByRole("menuitem", { name: "Đăng xuất" }).click();
  await expect(page).toHaveURL("/login");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  await page.goBack();
  await expect(page).toHaveURL("/login");
  await expect(page.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
});

test("401 clears auth, redirects to login, and a failed login stays on the form", async ({ page }) => {
  await page.addInitScript(({ key, current }) => localStorage.setItem(key, JSON.stringify(current)), { key: STORAGE_KEY, current: session() });
  let queries = 0;
  await page.route(/\/clusters(?:\?.*)?$/, (route) => {
    queries++;
    return route.fulfill({ status: 401, json: { detail: "Unauthorized" }, headers: cors });
  });
  await page.route("**/auth/login", (route) => route.fulfill({ status: 401, json: { detail: "Invalid credentials" }, headers: cors }));
  await page.goto("/");

  await expect(page).toHaveURL("/login");
  await expect(page.getByRole("status")).toContainText("Phiên đăng nhập đã hết hạn.");
  // Dev StrictMode co the huy request mount dau tien va tao request moi.
  // Sau 401/redirect, khong co retry query khi gui form login.
  const initialQueries = queries;
  expect(initialQueries).toBeGreaterThanOrEqual(1);
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  await page.getByLabel("Tên đăng nhập").fill("test-admin");
  await page.getByLabel("Mật khẩu").fill("wrong-test-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Đăng nhập không thành công.");
  await expect(page).toHaveURL("/login");
  expect(queries).toBe(initialQueries);
});

test("expiration removes a protected page without waiting for an API request", async ({ page }) => {
  const now = Date.now();
  await page.clock.install({ time: now });
  const current = { token: "expiring-browser-test-token", expires_at: new Date(now + 3_600_000).toISOString() };
  await page.addInitScript(({ key, current }) => localStorage.setItem(key, JSON.stringify(current)), { key: STORAGE_KEY, current });
  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "Search log", exact: true })).toBeVisible();

  await page.clock.fastForward(3_600_001);

  await expect(page).toHaveURL("/login");
  await expect(page.getByRole("status")).toContainText("Phiên đăng nhập đã hết hạn.");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
});

test("mobile admin menu logs out and synchronizes another open tab", async ({ page, context }, testInfo) => {
  await page.goto("/login");
  await page.evaluate(({ key, current }) => localStorage.setItem(key, JSON.stringify(current)), { key: STORAGE_KEY, current: session() });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search");
  const otherTab = await context.newPage();
  await otherTab.goto("/search");
  await expect(otherTab.getByRole("heading", { name: "Search log", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await expect(page.getByRole("menuitem", { name: "Đăng xuất" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("admin-menu-mobile.png"), fullPage: true });

  await page.getByRole("menuitem", { name: "Đăng xuất" }).click();

  await expect(page).toHaveURL("/login");
  await expect(otherTab).toHaveURL("/login");
  await otherTab.close();
});
