import { expect, test } from "@playwright/test";

test.use({ timezoneId: "America/New_York" });

for (const editStart of [false, true]) {
  test(`resolve preserves the later DST occurrence ${editStart ? "when only the start is edited" : "when both bounds are unchanged"}`,
    async ({ page }) => {
      const windowFrom = "2026-11-01T01:15:00-05:00";
      const windowTo = "2026-11-01T01:45:00-05:00";
      const incident = {
        episode_id: "c1:1", status: "open", window_from: windowFrom, window_to: windowTo,
      };
      const cluster = {
        cluster_id: "c1", status: "anomalous", score: 4, service: "test",
        signature: "Test incident", first_seen: windowFrom, last_seen: windowTo,
        log_ids: [], trace_ids: [], logs: [], logs_total: 0, incident,
      };
      await page.route("**/api/auth/refresh", (route) => route.fulfill({
        json: { token: "bounds-test-token", session_id: "bounds-test-session",
          expires_at: new Date(Date.now() + 3_600_000).toISOString() },
      }));
      await page.route(/\/api\/clusters\/c1(?:\?.*)?$/, (route) => {
        if (route.request().method() === "PATCH") {
          return route.fulfill({ json: { ...incident, status: "resolved" } });
        }
        return route.fulfill({ json: cluster });
      });
      await page.route("**/api/clusters/c1/history", (route) => route.fulfill({
        json: { cluster_id: "c1", points: [] },
      }));
      await page.route("**/api/assistant/clusters/c1/conversation", (route) => route.fulfill({
        json: { cluster_id: "c1", messages: [] },
      }));

      await page.goto("/clusters/c1");
      await page.getByRole("button", { name: "Đóng sự cố", exact: true }).click();
      const dialog = page.getByRole("dialog");
      if (editStart) await dialog.getByLabel("Bắt đầu").fill("2026-11-01T00:30");
      await dialog.getByLabel("Kết luận").selectOption("confirmed_incident");
      await dialog.getByLabel("Nguyên nhân gốc hoặc lý do báo động giả").fill("Reviewed");
      const patch = page.waitForRequest((request) =>
        request.url().endsWith("/api/clusters/c1") && request.method() === "PATCH");
      await dialog.getByRole("button", { name: "Lưu kết luận" }).click();
      expect((await patch).postDataJSON()).toMatchObject({
        window_from: editStart ? "2026-11-01T04:30:00.000Z" : windowFrom,
        window_to: windowTo,
      });
    });
}
