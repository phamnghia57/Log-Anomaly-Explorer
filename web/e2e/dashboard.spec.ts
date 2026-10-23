import { expect, test } from "@playwright/test";

test("dashboard tai duoc va hien sidebar + tieu de", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Log Anomaly Explorer")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("doi filter status khong lam vo trang (Alerted/Anomalous/Normal)", async ({ page }) => {
  await page.goto("/");
  for (const label of ["Alerted", "Anomalous", "Normal", "Tất cả"]) {
    await page.getByRole("tab", { name: label }).click();
    await expect(page.getByText("Cụm bất thường")).toBeVisible();
  }
});
