import { expect, test } from "@playwright/test";


test.beforeEach(async ({ page }) => {
  await page.goto("/");
});


test("首頁讓非技術訪客理解水泵治理故事且沒有產品 API 請求", async ({ page }) => {
  const forbidden: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("127.0.0.1:8130") || url.includes("/api/") || url.startsWith("ws:")) forbidden.push(url);
  });
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("AI 可以提議");
  await expect(page.getByText(/AI 使用公司工具的標準插座/)).toBeVisible();
  await expect(page.getByRole("img", { name: /循環水泵構造示意/ })).toBeVisible();
  expect(forbidden).toEqual([]);
});


test("設備管理水泵提案需要雙人核准且冪等重送", async ({ page }) => {
  await page.getByRole("button", { name: /風險治理/ }).click();
  const approval = page.locator("#approval");
  await approval.getByRole("button", { name: /建立並凍結提案/ }).click();
  await approval.getByRole("button", { name: "Reviewer A 核准" }).click();
  await expect(approval.getByText(/仍需另一位不同 reviewer/)).toBeVisible();
  await approval.getByRole("button", { name: "Reviewer B 核准" }).click();
  await expect(approval.getByText(/核准完成/)).toBeVisible();
  const idempotency = page.locator("#idempotency");
  await idempotency.getByRole("button", { name: "第一次送出" }).click();
  await idempotency.getByRole("button", { name: "模擬並行" }).click();
  await expect(idempotency.getByText(/唯一約束保留 WO-DEMO-001/)).toBeVisible();
});


test("跨設備被阻擋且隔離還原不帶回權威", async ({ page }) => {
  const scope = page.locator("#scope");
  await scope.getByRole("button", { name: "嘗試跨設備" }).click();
  await expect(scope.getByText(/NOT_FOUND_OR_FORBIDDEN/)).toBeVisible();
  const restore = page.locator("#restore");
  await restore.getByRole("button", { name: "建立隔離還原" }).click();
  await expect(restore.getByText("零權威驗證通過")).toBeVisible();
  await expect(restore.getByText(/MCP 呼叫 0/)).toBeVisible();
});


test("下載公開證據可用而工作台只是一個主動連結", async ({ page, request }) => {
  const json = await request.get("/downloads/evidence-summary.json");
  const markdown = await request.get("/downloads/%E4%BD%9C%E5%93%81%E8%AD%89%E6%93%9A%E6%91%98%E8%A6%81.md");
  expect(json.ok()).toBeTruthy();
  expect(markdown.ok()).toBeTruthy();
  const payload = await json.json();
  expect(payload.core_version).toBe("0.5.0");
  const link = page.locator("[data-real-workbench]");
  await expect(link).toHaveAttribute("href", "http://127.0.0.1:8130/");
  await expect(page.getByText(/本站不探查服務狀態/)).toBeVisible();
});


test("桌機與手機沒有水平溢位且可使用鍵盤", async ({ page }, testInfo) => {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip-link")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeVisible();
  const output = testInfo.project.name === "mobile" ? "reports/showcase-mobile.png" : "reports/showcase-desktop.png";
  await page.screenshot({ path: output, fullPage: true });
});
