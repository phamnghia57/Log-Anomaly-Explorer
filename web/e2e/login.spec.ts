import { expect, test } from "@playwright/test";

const STORAGE_KEY = "log-anomaly-explorer.auth";

test("login persists a session, redirects to dashboard and restores it after reload", async ({ page }, testInfo) => {
  const session = { token: "browser-test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() };
  let authenticatedQueries = 0;
  await page.route("**/auth/login", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ username: "test-admin", password: "test-password" });
    await route.fulfill({ json: session, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.route("**/clusters", async (route) => {
    expect(route.request().headers()["authorization"]).toBe(`Bearer ${session.token}`);
    authenticatedQueries += 1;
    await route.fulfill({ json: { total: 0, clusters: [] }, headers: { "Access-Control-Allow-Origin": "*" } });
  });

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("login-desktop.png"), fullPage: true });
  await page.getByLabel("Tên đăng nhập").fill("test-admin");
  await page.getByLabel("Mật khẩu").fill("test-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await expect.poll(() => authenticatedQueries).toBe(1);
  expect(await page.evaluate((key) => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY)).toEqual(session);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await expect.poll(() => authenticatedQueries).toBe(2);
});

test("mobile login shows a generic failure and keeps passwords out of storage", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/auth/login", (route) => route.fulfill({
    status: 401, json: { detail: "username does not exist", token: "invalid" },
    headers: { "Access-Control-Allow-Origin": "*" },
  }));
  await page.goto("/login");
  await page.getByLabel("Tên đăng nhập").fill("test-admin");
  await page.getByLabel("Mật khẩu").fill("test-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();

  await expect(page.getByRole("alert")).toContainText("Đăng nhập không thành công.");
  await expect(page.getByRole("alert")).not.toContainText("username does not exist");
  await expect(page.getByLabel("Mật khẩu")).toHaveValue("");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("login-mobile-error.png"), fullPage: true });
});

test("an expired persisted session prompts a new login", async ({ page }) => {
  await page.addInitScript((key) => {
    localStorage.setItem(key, JSON.stringify({ token: "expired-test-token", expires_at: "2020-01-01T00:00:00Z" }));
  }, STORAGE_KEY);

  await page.goto("/login");

  await expect(page.getByRole("status")).toHaveText("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeEnabled();
});
