import { expect, test as base } from "@playwright/test";

// Cac spec dung backend that dang nhap qua UI; credentials chi lay tu environment.
export const test = base.extend({
  page: async ({ page }, runTest) => {
    const username = process.env.E2E_ADMIN_USERNAME;
    const password = process.env.E2E_ADMIN_PASSWORD;
    base.skip(!username || !password, "Can E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD va backend da seed admin.");
    await page.goto("/login");
    await page.getByLabel("Tên đăng nhập").fill(username!);
    await page.getByLabel("Mật khẩu").fill(password!);
    await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
    await expect(page).toHaveURL("/");
    await runTest(page);
  },
});

export { expect };
