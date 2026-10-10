import { expect, test } from "@playwright/test";

test("desktop: setup, real MCP read, result and trace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "建立第一位管理者" })).toBeVisible();
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "建立並進入" }).click();
  await expect(page.getByRole("heading", { name: /先看清楚/ })).toBeVisible();
  await expect(page.getByText("2026-07-28", { exact: true })).toBeVisible();
  await page.getByLabel("選擇工作方式").selectOption("service-v1");
  await page.getByLabel(/設備編號/).selectOption("EQ-PUMP-001");
  await page.getByRole("button", { name: "執行唯讀查詢" }).click();
  await expect(page.getByRole("heading", { name: "查詢結果" })).toBeVisible();
  await expect(page.getByText("degraded", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Trace/ }).click();
  await expect(page.getByText("mcp.call_completed", { exact: true })).toBeVisible();
  await expect(page.getByText(/local.toolworkbench\/authContext/)).toHaveCount(0);
  await page.screenshot({ path: "../reports/p2b-desktop.png", fullPage: true });
});

test("mobile: navigation remains usable and profile cannot expand scope", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page.getByRole("heading", { name: /先看清楚/ })).toBeVisible();
  await page.getByRole("button", { name: /污染與邊界/ }).click();
  await expect(page.getByRole("heading", { name: /資料不只要安全/ })).toBeVisible();
  await expect(page.getByText("fixture_demo｜只存在瀏覽器，不呼叫 MCP")).toBeVisible();
  await expect(page.locator(".env-card")).toBeHidden();
  const navigationButton = await page.getByRole("button", { name: /工具與查詢/ }).boundingBox();
  expect(navigationButton?.height).toBeLessThan(60);
  await page.screenshot({ path: "../reports/p2b-mobile.png", fullPage: true });
});

test("desktop: admin creates separated roles and service proposal becomes one order", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /帳號治理/ }).click();

  await page.getByLabel("帳號", { exact: true }).fill("e2e-operator");
  await page.getByLabel("初始密碼").fill("workflow-pass-1234");
  await page.getByLabel("主要角色").selectOption("operator");
  await page.getByRole("button", { name: "建立帳號" }).click();
  await expect(page.getByText(/已建立 e2e-operator/)).toBeVisible();

  await page.getByLabel("帳號", { exact: true }).fill("e2e-reviewer");
  await page.getByLabel("初始密碼").fill("workflow-pass-1234");
  await page.getByLabel("主要角色").selectOption("reviewer");
  await page.getByRole("button", { name: "建立帳號" }).click();
  await expect(page.getByText(/已建立 e2e-reviewer/)).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page.getByRole("heading", { name: "登入工具工作台" })).toBeVisible();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-operator");
  await page.getByLabel("密碼").fill("workflow-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByLabel("選擇工作方式").selectOption("service-v1");
  await page.getByRole("button", { name: /提案與核准/ }).click();
  await page.getByLabel(/1 日/).check();
  await page.getByRole("button", { name: "建立草稿" }).click();
  await expect(page.getByText(/草稿已建立/)).toBeVisible();
  await expect(page.getByText("1 日", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "送出審核" }).click();
  await expect(page.getByText(/等待獨立 reviewer/)).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page.getByRole("heading", { name: "登入工具工作台" })).toBeVisible();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-reviewer");
  await page.getByLabel("密碼").fill("workflow-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByLabel("選擇工作方式").selectOption("service-v1");
  await page.getByRole("button", { name: /提案與核准/ }).click();
  await page.getByLabel("審核理由").fill("已確認設備範圍、問題摘要與資料版本一致。");
  await page.getByRole("button", { name: "核准", exact: true }).click();
  await expect(page.getByText(/審核已記錄/)).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page.getByRole("heading", { name: "登入工具工作台" })).toBeVisible();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-operator");
  await page.getByLabel("密碼").fill("workflow-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByLabel("選擇工作方式").selectOption("service-v1");
  await page.getByRole("button", { name: /提案與核准/ }).click();
  await page.getByRole("button", { name: "建立本機工單" }).click();
  await expect(page.getByText(/本機工單已交易提交/)).toBeVisible();
  await expect(page.getByText(/^MO-\d{8}-\d{6}$/)).toBeVisible();
  await page.screenshot({ path: "../reports/p2c-write-workflow.png", fullPage: true });
});

test("desktop: admin account lifecycle controls revoke and restore access", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /帳號治理/ }).click();

  const operatorCard = page.locator(".user-card").filter({ hasText: "e2e-operator" });
  await operatorCard.getByRole("button", { name: "停用帳號" }).click();
  await expect(page.getByText(/已停用 e2e-operator/)).toBeVisible();
  await operatorCard.getByRole("button", { name: "重新啟用" }).click();
  await expect(page.getByText(/已重新啟用 e2e-operator/)).toBeVisible();

  await operatorCard.getByRole("button", { name: "編輯權限" }).click();
  await operatorCard.getByLabel("新密碼").fill("workflow-pass-5678");
  await operatorCard.getByRole("button", { name: "重設密碼" }).click();
  await expect(page.getByText(/已重設 e2e-operator/)).toBeVisible();
  await page.screenshot({ path: "../reports/p2d1-account-governance.png", fullPage: true });

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page.getByRole("heading", { name: "登入工具工作台" })).toBeVisible();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-operator");
  await page.getByLabel("密碼").fill("workflow-pass-5678");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page.getByRole("heading", { name: /先看清楚/ })).toBeVisible();
});

test("desktop: profile draft is previewed, independently approved, applied and rolled back as a new draft", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /設定版本/ }).click();
  await page.getByLabel("設定對象").selectOption("service-v1");
  await page.getByLabel("顯示名稱").fill("現場可靠度團隊");
  await page.getByLabel("範圍標籤").fill("RELIABILITY-C");
  await page.getByLabel("業務術語").fill("可靠度事件");
  await page.getByLabel("核准人數").selectOption("2");
  await page.getByLabel("預設保存").selectOption("1");
  await page.getByRole("button", { name: "建立設定草稿" }).click();
  await expect(page.getByText(/設定草稿已建立/)).toBeVisible();
  await page.getByRole("button", { name: "驗證設定草稿" }).click();
  await expect(page.getByText(/安全底線驗證通過/)).toBeVisible();
  await page.getByRole("button", { name: "產生差異預覽" }).click();
  await expect(page.getByText(/差異預覽已固定/)).toBeVisible();
  await page.getByRole("button", { name: "送交獨立核准" }).click();
  await expect(page.getByText(/已送交獨立 reviewer/)).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-reviewer");
  await page.getByLabel("密碼").fill("workflow-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /設定版本/ }).click();
  await page.getByLabel("設定對象").selectOption("service-v1");
  await page.getByLabel("核准理由").fill("已確認設備範圍、核准人數及保存影響符合需求。 ");
  await page.getByRole("button", { name: "核准設定" }).click();
  await expect(page.getByText(/等待管理者套用/)).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await page.getByLabel("帳號", { exact: true }).fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /設定版本/ }).click();
  await page.getByLabel("設定對象").selectOption("service-v1");
  await page.getByRole("button", { name: "套用新版本" }).click();
  await expect(page.getByText(/新設定版本已套用/)).toBeVisible();
  await expect(page.getByLabel("顯示名稱")).toHaveValue("現場可靠度團隊");
  await page.screenshot({ path: "../reports/p2d2-profile-configuration.png", fullPage: true });

  await page.getByRole("button", { name: "建立還原草稿" }).click();
  await expect(page.getByText(/已從歷史版本建立新的還原草稿/)).toBeVisible();
  await expect(page.getByText("1.0.2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "取消候選" }).click();
  await expect(page.getByText(/設定候選已取消/)).toBeVisible();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();
});

test("desktop: admin creates a content-free backup and zero-authority isolated restore", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /備份與還原/ }).click();
  await expect(page.getByRole("heading", { name: /備份資料關係/ })).toBeVisible();
  await expect(page.locator(".migration-row")).toHaveCount(4);
  await expect(page.getByText("一律排除")).toBeVisible();

  await page.getByLabel("輸入確認文字").first().fill("建立去內容備份");
  await page.getByRole("button", { name: "建立去內容備份" }).click();
  await expect(page.getByText(/已完成原子寫入與 SHA-256 驗證/)).toBeVisible();
  await expect(page.locator(".backup-record")).toHaveCount(1);

  await page.getByLabel("輸入確認文字").last().fill("建立唯讀隔離還原");
  await page.getByRole("button", { name: "建立隔離還原" }).click();
  await expect(page.getByText(/沒有恢復執行權威/)).toBeVisible();
  await expect(page.locator(".restore-receipts article")).toHaveCount(1);
  await expect(page.locator(".zero-authority b")).toHaveText(["0", "0", "0", "0", "0"]);
  await expect(page.getByText(/來源資料內容雜湊未改變/)).toBeVisible();
  await page.locator("main.content").screenshot({ path: "../reports/p2d3-backup-restore.png" });
});

test("mobile: backup governance remains readable without restoring authority", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("帳號").fill("e2e-admin");
  await page.getByLabel("密碼").fill("e2e-local-pass-1234");
  await page.getByRole("button", { name: "登入" }).click();
  await page.getByRole("button", { name: /備份與還原/ }).click();
  await expect(page.getByRole("heading", { name: /備份資料關係/ })).toBeVisible();
  await expect(page.locator(".migration-row")).toHaveCount(4);
  const panel = await page.locator(".backup-governance-grid").boundingBox();
  expect(panel?.width).toBeLessThanOrEqual(358);
  await expect(page.locator(".zero-authority b").last()).toHaveText("0");
  await page.locator("main.content").screenshot({ path: "../reports/p2d3-backup-restore-mobile.png" });
});

