import { createHmac, timingSafeEqual } from "node:crypto";
import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8023";
const STORAGE_KEY = "log-anomaly-explorer.auth";
const paths = ["/search", "/clusters", "/clusters/auth-test-cluster", "/clusters/auth-test-cluster/history"];

function signedToken(exp: number, secret = process.env.AUTH_E2E_SECRET!) {
  const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
  const body = Buffer.from(JSON.stringify({ sub: process.env.AUTH_E2E_USERNAME, role: "admin", exp })).toString("base64url");
  const signature = createHmac("sha256", secret).update(`${header}.${body}`).digest("base64url");
  return `${header}.${body}.${signature}`;
}

test("seeded admin logs in via web, accesses every protected API, then logs out", async ({ page, request }) => {
  for (const path of paths) expect((await request.get(`${API}${path}`)).status()).toBe(401);
  expect((await request.get(`${API}/health`)).status()).toBe(200);
  for (const [path, method, headers] of [["/auth/login", "POST", "content-type"], ["/search", "GET", "authorization"]]) {
    const preflight = await request.fetch(`${API}${path}`, { method: "OPTIONS", headers: {
      Origin: "http://127.0.0.1:5174", "Access-Control-Request-Method": method,
      "Access-Control-Request-Headers": headers,
    } });
    expect(preflight.status()).toBe(200);
    expect(preflight.headers()["access-control-allow-origin"]).toBe("*");
  }

  await page.goto("/clusters/auth-test-cluster");
  await expect(page).toHaveURL("/login");
  await page.getByLabel("Tên đăng nhập").fill(process.env.AUTH_E2E_USERNAME!);
  await page.getByLabel("Mật khẩu").fill(process.env.AUTH_E2E_PASSWORD!);
  const responsePromise = page.waitForResponse(`${API}/auth/login`);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  const login = await responsePromise;
  expect(login.status()).toBe(200);
  const session = await login.json() as { token: string; expires_at: string };
  const [header, payload, signature] = session.token.split(".");
  const expected = createHmac("sha256", process.env.AUTH_E2E_SECRET!).update(`${header}.${payload}`).digest();
  expect(timingSafeEqual(Buffer.from(signature, "base64url"), expected)).toBe(true);
  const claims = JSON.parse(Buffer.from(payload, "base64url").toString());
  expect(claims.sub).toBe(process.env.AUTH_E2E_USERNAME);
  expect(claims.role).toBe("admin");
  expect(claims.exp * 1000).toBe(Date.parse(session.expires_at));
  await expect(page).toHaveURL("/clusters/auth-test-cluster");
  await expect(page.getByRole("heading", { name: /^Log trong cụm/ })).toBeVisible();
  const auth = { Authorization: `Bearer ${session.token}` };
  for (const path of paths) expect((await request.get(`${API}${path}`, { headers: auth })).status()).toBe(200);
  const search = await request.get(`${API}/search`, { headers: auth });
  expect(await search.json()).toMatchObject({ total: 1, results: [{ message: "Integration test fault" }] });

  await page.getByRole("button", { name: "Menu quản trị" }).click();
  await page.getByRole("menuitem", { name: "Đăng xuất" }).click();
  await expect(page).toHaveURL("/login");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
  await page.goto("/clusters/auth-test-cluster");
  await expect(page).toHaveURL("/login");
  for (const path of paths) expect((await request.get(`${API}${path}`)).status()).toBe(401);
  // Client logout is not server-side revocation; document this limitation explicitly.
  expect((await request.get(`${API}/search`, { headers: auth })).status()).toBe(200);
});

test("real API rejects expired/invalid JWTs and its 401 clears the browser session", async ({ page, request }) => {
  const now = Math.floor(Date.now() / 1000);
  const expired = signedToken(now - 60);
  const invalid = signedToken(now + 3600, "invalid-test-signing-key-with-32-bytes");
  for (const token of [expired, invalid, "malformed-token"]) {
    for (const path of paths) {
      const response = await request.get(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
      expect(response.status()).toBe(401);
      expect(response.headers()["www-authenticate"]).toBe("Bearer");
    }
  }
  await page.addInitScript(({ key, token }) => localStorage.setItem(key, JSON.stringify({
    token, expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  })), { key: STORAGE_KEY, token: expired });
  const rejection = page.waitForResponse((response) => response.url() === `${API}/clusters` && response.status() === 401);
  await page.goto("/");
  await rejection;
  await expect(page).toHaveURL("/login");
  await expect(page.getByRole("status")).toContainText("Phiên đăng nhập đã hết hạn.");
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
});
