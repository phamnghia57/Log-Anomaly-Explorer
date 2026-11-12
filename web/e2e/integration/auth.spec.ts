import { expect, test, type Page } from "@playwright/test";

const STORAGE_KEY = "log-anomaly-explorer.auth";
const paths = ["/search", "/clusters", "/clusters/auth-test-cluster", "/clusters/auth-test-cluster/history"];

async function login(page: Page, destination = "/search") {
  await page.goto(destination);
  await expect(page).toHaveURL("/login");
  await page.getByLabel("Tên đăng nhập").fill(process.env.AUTH_E2E_USERNAME!);
  await page.getByLabel("Mật khẩu").fill(process.env.AUTH_E2E_PASSWORD!);
  const response = page.waitForResponse((res) => res.url().endsWith("/api/auth/login"));
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  await expect(page).toHaveURL(destination);
  return result.json() as Promise<{ token: string; expires_at: string; session_id: string }>;
}

test("login uses HttpOnly cookie through proxy; logout revokes copied access", async ({ page, context }) => {
  const access = await login(page);
  const cookies = await context.cookies();
  const refresh = cookies.find((cookie) => cookie.name === "lae_refresh");
  expect(refresh).toMatchObject({ httpOnly: true, sameSite: "Lax", path: "/api/auth" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("lae_refresh");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  const headers = { Authorization: `Bearer ${access.token}` };
  for (const path of paths) expect((await context.request.get(`/api${path}`, { headers })).status()).toBe(200);
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await page.getByRole("menuitem", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL("/login");
  expect((await context.request.get("/api/search", { headers })).status()).toBe(401);
  expect((await context.cookies()).find((cookie) => cookie.name === "lae_refresh")).toBeUndefined();
});

test("reload and simultaneous tabs rotate safely; logout synchronizes all tabs", async ({ page, context }) => {
  await login(page);
  const other = await context.newPage();
  await other.goto("/search");
  await expect(other.getByRole("heading", { name: "Search log", exact: true })).toBeVisible();
  await Promise.all([page.reload(), other.reload()]);
  for (const tab of [page, other]) {
    await expect(tab.getByRole("heading", { name: "Search log", exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await page.getByRole("menuitem", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL("/login");
  await expect(other).toHaveURL("/login");
  await other.reload();
  await expect(other).toHaveURL("/login");
});

test("logout revokes the current token when the refresh cookie is missing", async ({ page, context }) => {
  const access = await login(page);
  await context.clearCookies({ name: "lae_refresh" });
  const logout = page.waitForResponse((response) => response.url().endsWith("/api/auth/logout"));
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await page.getByRole("menuitem", { name: "Đăng xuất", exact: true }).click();
  expect((await logout).status()).toBe(204);
  await expect(page).toHaveURL("/login");
  expect((await context.request.get("/api/search", {
    headers: { Authorization: `Bearer ${access.token}` },
  })).status()).toBe(401);
});

test("access expiry automatically refreshes without sending the user to login", async ({ page, context }) => {
  const before = await login(page);
  const response = await page.waitForResponse((res) => res.url().endsWith("/api/auth/refresh")
    && res.status() === 200, { timeout: 12_000 });
  const after = await response.json();
  expect(after.token).not.toBe(before.token);
  expect(after.session_id).toBe(before.session_id);
  await expect(page).toHaveURL("/search");
  expect((await context.request.get("/api/search", { headers: { Authorization: `Bearer ${after.token}` } })).status()).toBe(200);
});

test("auth POST rejects cross-site and missing CSRF headers through proxy", async ({ request }) => {
  const data = { username: process.env.AUTH_E2E_USERNAME, password: process.env.AUTH_E2E_PASSWORD };
  for (const path of ["login", "refresh", "logout"]) {
    const response = await request.post(`/api/auth/${path}`, { data });
    expect(response.status()).toBe(403);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const foreign = await request.post(`/api/auth/${path}`, { data,
      headers: { "X-CSRF-Protection": "1", Origin: "https://evil.example" } });
    expect(foreign.status()).toBe(403);
  }
});

test("logout failure is visible and can be retried without false success", async ({ page }) => {
  await login(page);
  let attempts = 0;
  await page.route("**/api/auth/logout", (route) => {
    attempts++;
    return route.fulfill({ status: 503, json: { detail: "Authentication unavailable" } });
  });
  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await page.getByRole("menuitem", { name: "Đăng xuất", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Chưa xác nhận đăng xuất");
  await expect(page).toHaveURL("/search");
  expect(attempts).toBe(1);
  await page.unroute("**/api/auth/logout");
  await page.getByRole("menuitem", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL("/login");
});

test("Incident View acknowledges, closes and opens a new episode after a recurrence", async ({ page, request }) => {
  test.skip(!process.env.AUTH_E2E_OPENSEARCH_URL, "Requires the disposable OpenSearch test cluster");
  await login(page, "/clusters/auth-test-cluster");
  await page.getByRole("button", { name: "Tiếp nhận", exact: true }).click();
  await expect(page.getByText("Đã tiếp nhận", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Đóng sự cố", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Kết luận").selectOption("confirmed_incident");
  await dialog.getByLabel("Nguyên nhân gốc hoặc lý do báo động giả").fill("Lỗi mạng trong môi trường kiểm thử");
  const resolution = page.waitForResponse((response) =>
    response.url().endsWith("/api/clusters/auth-test-cluster") && response.request().method() === "PATCH" && response.ok());
  await dialog.getByRole("button", { name: "Lưu kết luận", exact: true }).click();
  const closed = await resolution;
  const { resolved_at } = await closed.json() as { resolved_at: string };
  await expect(dialog).toBeHidden();
  await page.reload();
  await expect(page.getByText("Đã đóng", { exact: true })).toBeVisible();
  await expect(page.getByText("Lỗi mạng trong môi trường kiểm thử", { exact: true })).toBeVisible();

  const next = new Date(Date.parse(resolved_at) + 1000).toISOString();
  const index = `${process.env.AUTH_E2E_INDEX_PREFIX}-history`;
  const url = new URL(`/${index}/_doc?refresh=wait_for`, process.env.AUTH_E2E_OPENSEARCH_URL);
  const inserted = await request.post(url.toString(), { data: {
    cluster_id: "auth-test-cluster", score: 4, status: "anomalous",
    recorded_at: next, first_seen: next, last_seen: next,
  } });
  expect(inserted.ok()).toBe(true);
  await page.reload();
  await expect(page.getByText("Chưa tiếp nhận", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tiếp nhận", exact: true })).toBeVisible();
});
