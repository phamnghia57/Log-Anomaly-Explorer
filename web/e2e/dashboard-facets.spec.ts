import { expect, test } from "@playwright/test";

// Cross-filter giua 2 facet: logic dem da co unit test
// (src/components/dashboard/facet-filters.test.ts), nhung chi test o day moi
// bat duoc loi NOI NHAM danh sach vao facet (vd. dua tap da loc theo status
// cho chinh facet status -> cac lua chon con lai deu ve 0).
test("facet Status va Service dem cheo nhau, khong tu loc chinh no", async ({ page }) => {
  const now = new Date().toISOString();
  const make = (id: string, service: string, status: string) => ({
    cluster_id: id, signature: `loi ${id}`, score: 3, status,
    log_ids: ["a"], trace_ids: [], first_seen: now, last_seen: now, service,
  });
  // demo-web: 2 alerted + 1 normal | demo-mobile-api: 1 alerted | billing: 1 normal
  const clusters = [
    make("w1", "demo-web", "alerted"), make("w2", "demo-web", "alerted"),
    make("w3", "demo-web", "normal"), make("m1", "demo-mobile-api", "alerted"),
    make("b1", "billing", "normal"),
  ];
  await page.route("**/api/auth/refresh", (route) => route.fulfill({
    json: {
      token: "local-browser-test", session_id: "test-session", expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    },
  }));
  await page.route(/\/clusters(?:[/?].*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = path.endsWith("/history")
      ? { cluster_id: "x", points: [] }
      : { total: clusters.length, clusters };
    await route.fulfill({ json, headers: { "Access-Control-Allow-Origin": "*" } });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();

  const serviceNav = page.getByRole("navigation", { name: "Lọc theo service" });
  const statusNav = page.getByRole("navigation", { name: "Lọc theo trạng thái" });

  // Chua loc gi: facet service dem tren ca 5 cum.
  await expect(serviceNav.getByRole("button", { name: /^demo-web/ })).toContainText("3");
  await expect(serviceNav.getByRole("button", { name: /^billing/ })).toContainText("1");

  // Chon Alerted -> facet service dem LAI trong pham vi alerted (3 cum).
  await statusNav.getByRole("button", { name: /^Alerted/ }).click();
  await expect(serviceNav.getByRole("button", { name: /^demo-web/ })).toContainText("2");
  await expect(serviceNav.getByRole("button", { name: /^demo-mobile-api/ })).toContainText("1");
  await expect(serviceNav.getByRole("button", { name: /^billing/ })).toHaveCount(0);

  // Chon them demo-web -> facet status dem trong pham vi demo-web (3 cum) va
  // KHONG tu loc theo status dang chon (neu tu loc thi Normal se la 0).
  await serviceNav.getByRole("button", { name: /^demo-web/ }).click();
  await expect(statusNav.getByRole("button", { name: /^Alerted/ })).toContainText("2");
  await expect(statusNav.getByRole("button", { name: /^Normal/ })).toContainText("1");
  await expect(statusNav.getByRole("button", { name: /^Tất cả/ })).toContainText("3");

  // Luoi chi con cum thoa CA HAI facet.
  await expect(page.locator('a[href="/clusters/w1"]')).toBeVisible();
  await expect(page.locator('a[href="/clusters/w3"]')).toHaveCount(0);
});
