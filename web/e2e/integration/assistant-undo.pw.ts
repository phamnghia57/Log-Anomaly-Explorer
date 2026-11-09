import { writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("F-E2E real admin login, Send, Undo and reload restore durable exact history", async ({ page, request }) => {
  const api = process.env.VT013_E2E_API_URL!;
  const conversationUrl = `${api}/assistant/clusters/vt013-integration-cluster/conversation`;
  expect(api).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  expect((await request.get(conversationUrl)).status()).toBe(401);

  await page.goto("/clusters/vt013-integration-cluster");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Tên đăng nhập").fill("vt013-admin");
  await page.getByLabel("Mật khẩu").fill(process.env.VT013_E2E_PASSWORD!);
  const login = page.waitForResponse(`${api}/auth/login`);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  expect((await login).status()).toBe(200);
  await expect(page.getByRole("heading", { name: /^Log trong cụm/ })).toBeVisible();
  await expect(page.getByText("Original durable answer", { exact: true })).toBeVisible();
  const undoButton = page.getByRole("button", { name: "Hoàn tác lượt gửi", exact: true });
  await expect(undoButton).toBeDisabled();

  // APIRequestContext uses the same real JWT obtained by the browser login.
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem("log-anomaly-explorer.auth")!).token as string);
  const beforeResponse = await request.get(conversationUrl, { headers: { Authorization: `Bearer ${token}` } });
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  const message = "VT-013 browser Send";
  await page.getByRole("textbox", { name: "Câu hỏi cho AI Assistant" }).fill(message);
  const sendResponse = page.waitForResponse(`${conversationUrl}/messages`);
  await page.getByRole("button", { name: "Gửi câu hỏi", exact: true }).click();
  const sentResponse = await sendResponse;
  expect(sentResponse.status()).toBe(200);
  expect(Boolean(sentResponse.request().headers().authorization?.startsWith("Bearer "))).toBe(true);
  expect(sentResponse.request().postDataJSON()).toEqual({ message });
  const sent = await sentResponse.json();
  expect(sent.messages.slice(0, before.messages.length)).toEqual(before.messages);
  expect(sent.undo_available).toBe(true);
  await expect(page.getByText("Deterministic integration answer.", { exact: true })).toBeVisible();
  await expect(undoButton).toBeEnabled();

  const undoResponse = page.waitForResponse(`${conversationUrl}/undo`);
  await undoButton.click();
  const undoneResponse = await undoResponse;
  expect(undoneResponse.status()).toBe(200);
  expect(Boolean(undoneResponse.request().headers().authorization?.startsWith("Bearer "))).toBe(true);
  expect(undoneResponse.request().postDataJSON()).toEqual({ expected_revision: sent.revision });
  const undone = await undoneResponse.json();
  expect(undone.messages).toEqual(before.messages);
  expect(undone.revision).not.toBe(sent.revision);
  expect(undone.undo_available).toBe(false);
  await expect(page.getByText(message, { exact: true })).toHaveCount(0);
  await expect(page.getByText("Original durable answer", { exact: true })).toBeVisible();
  await expect(undoButton).toBeDisabled();

  const reloadResponse = page.waitForResponse((r) => r.url() === conversationUrl && r.request().method() === "GET");
  await page.reload();
  const reloadedResponse = await reloadResponse;
  expect(reloadedResponse.status()).toBe(200);
  const reloaded = await reloadedResponse.json();
  expect(reloaded).toEqual(undone);
  await expect(page.getByText("Original durable answer", { exact: true })).toBeVisible();
  await expect(page.getByText(message, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Hoàn tác lượt gửi", exact: true })).toBeDisabled();
  // No route interception, credentials, JWTs or browser trace are saved.
  await writeFile(process.env.VT013_E2E_PROOF!, JSON.stringify({
    before, sent, undone, reloaded, authenticated_request_headers_verified: true,
    real_http_statuses: { login: 200, send: 200, undo: 200, reload_get: 200 },
  }, null, 2) + "\n");
});
