import { expect, test } from "@playwright/test";

test("dashboard renders score history and links to the runbook", async ({ page }, testInfo) => {
  const now = new Date().toISOString();
  const cluster = {
    cluster_id: "local-history-check", signature: "downstream connection failed",
    score: 5, status: "alerted", log_ids: [], trace_ids: [],
    first_seen: now, last_seen: now, logs: [], logs_total: 0,
  };
  const points = [1, 3, 5].map((score, i) => ({
    cluster_id: cluster.cluster_id, score, status: i ? "alerted" : "normal",
    recorded_at: new Date(Date.now() - (2 - i) * 60_000).toISOString(),
  }));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/auth/refresh", (route) => route.fulfill({ json: {
    token: "local-browser-test", expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  } }));
  await page.route(/\/clusters(?:[/?].*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = path.endsWith("/history") ? { cluster_id: cluster.cluster_id, points }
      : path.endsWith(cluster.cluster_id) ? cluster : { total: 1, clusters: [cluster] };
    await route.fulfill({ json, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  const docs = page.getByRole("link", { name: "Runbook/Docs" });
  await expect(docs).toHaveAttribute("href", "https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/main/docs/task/runbook.md");
  await expect(docs).toHaveAttribute("target", "_blank");
  const clusterLink = page.locator(`a[href="/clusters/${cluster.cluster_id}"]`);
  const card = clusterLink.locator("..");
  await expect(card).toContainText(cluster.signature);
  await expect(card.locator("canvas")).toBeVisible();
  await expect(card.locator("canvas")).toHaveCSS("height", "64px");
  await expect(card).not.toContainText("Kéo thanh để phóng to thời gian");
  await page.screenshot({ path: testInfo.outputPath("dashboard-history.png"), fullPage: true });
  // The chart handles pointer events; open the incident outside its interactive area.
  await clusterLink.click({ position: { x: 12, y: 12 } });
  await expect(page.getByRole("heading", { name: "Xu hướng anomaly score" })).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.locator("canvas")).toHaveCSS("height", "360px");
  await expect(page.getByText("Kéo thanh để phóng to thời gian")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("incident-history.png"), fullPage: true });
  expect(errors).toEqual([]);
});
