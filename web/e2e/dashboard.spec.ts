import { expect, test } from "@playwright/test";

test("dashboard tai duoc va hien sidebar + tieu de", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Log Anomaly Explorer")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("doi facet trang thai khong lam vo trang (Alerted/Anomalous/Normal)", async ({ page }) => {
  await page.goto("/");
  for (const label of ["Alerted", "Anomalous", "Normal", "Tất cả"]) {
    await page.getByRole("button", { name: label }).click();
    await expect(page.getByText("Cụm bất thường")).toBeVisible();
  }
});
