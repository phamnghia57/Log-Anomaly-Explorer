import { expect, test } from "@playwright/test";

// Can it nhat 1 cluster da ton tai trong backend (xem playwright.config.ts).
test("bam vao 1 cum -> xem Incident View -> bam trace -> nhay sang Search loc dung", async ({ page }) => {
  await page.goto("/");

  const firstCard = page.locator("a[href^='/clusters/']").first();
  await expect(firstCard).toBeVisible({ timeout: 15000 });
  await firstCard.click();

  await expect(page).toHaveURL(/\/clusters\/.+/);
  await expect(page.getByText("Anomaly score")).toBeVisible();
  await expect(page.getByText("Log trong cụm")).toBeVisible();

  const traceButtons = page.locator("button").filter({ hasText: /^[0-9a-f]{16}$/ });
  const traceCount = await traceButtons.count();
  test.skip(traceCount === 0, "Cum nay khong co trace nao de test tiep");

  const traceId = await traceButtons.first().textContent();
  await traceButtons.first().click();

  await expect(page).toHaveURL(/\/search\?trace_id=/);
  if (traceId) {
    await expect(page.locator("#trace_id")).toHaveValue(new RegExp(`^${traceId}`));
  }
});
