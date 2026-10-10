# P2-B 驗收｜MCP 唯讀工具與授權治理

日期：2026-09-24  
版本：0.1.0  
結論：**P2-B 本機切片通過；可進入 P2-C 規劃，但尚未實作任何寫入、核准或工單建立。**

## 1. 本階段交付

本階段將 P2-A 的規劃原型實作成可操作產品，完成首次管理者建立、登入、兩組工作 Profile、三個唯讀 MCP 工具、Schema 表單、真實本機 `stdio` 呼叫、結果呈現、Trace 與資料污染治理頁。

MCP 並非由 REST 介面改名冒充。產品後端使用官方 Python SDK `2.2.0` 啟動固定的本機 MCP Server，執行 discovery 與 tool call；實測協議版本為 `2026-07-28`。Server 命令、模組、工作目錄及 Python 執行環境由產品固定，使用者不能輸入或替換。

三個已完成工具：

1. `get_equipment_status`：查詢設備最新狀態。
2. `list_maintenance_history`：查詢授權範圍內的維修紀錄。
3. `check_parts_stock`：查詢合成庫存與設備相容性，不預留或扣庫存。

## 2. 授權實際流程

每次工具呼叫依序經過：

1. 後端由 HttpOnly session 取得真實登入者，寫入操作另驗證 CSRF。
2. 以「帳號設備範圍 ∩ Profile 範圍 ∩ 工具政策」計算有效權限。
3. 後端簽發短效、單次使用且綁定工具、正規化參數、Profile、政策、目標與環境的一次性 context。
4. MCP Client 只在 request `_meta` 的 `local.toolworkbench/authContext` 傳遞該值。
5. MCP Server 以雜湊查找並交易式消耗 context，再次驗證帳號狀態、權限 epoch、參數、工具與環境。
6. 業務查詢完成後寫入可讀 Trace；原始 context 不落入 Trace。

工具輸入若夾帶 `role`、`user_id`、`approved` 等自報身分或核准欄位，會在產品邊界直接拒絕。使用過的 context 無法重放；Profile 只能縮小、不能擴大帳號範圍。

## 3. 資料污染優先驗收

本階段沒有複製作品一的資料庫、報告、holdout、帳號或執行狀態。所有業務資料均為本作品新建的合成種子，回傳值標記 `source_kind: synthetic_seed`。

環境硬分區：

| 環境 | 用途 | 主要阻擋 |
|---|---|---|
| `local_product` | 使用者本機產品操作 | 只能使用自己的資料庫根目錄 |
| `development` | 開發 | 不算正式驗收資料 |
| `automated_test` | 自動化測試 | 每次 E2E 使用全新唯一資料庫 |
| `fixture_demo` | 純前端說明 | 不呼叫 MCP、不寫產品資料 |
| `restore_isolation` | 後續隔離還原 | 不恢復可執行權限 |

設定啟動時會解析真實路徑；路徑逃逸、資料庫環境指紋不符與資料庫符號連結均 fail closed。Trace 同時保留環境、Profile、工具與事件階段，避免把 fixture、test 與 measured local 結果混成同一類證據。

## 4. 互動與視覺驗收

- 桌面：完成建立帳號 → discovery → 選擇 Profile → 真實唯讀查詢 → 結構化結果 → Trace 鑽取。
- 手機 390px：登入、水平導覽、資料邊界頁、卡片與長文字均可操作及閱讀。
- 換頁會回到頁首，不再讓固定導覽遮住新頁標題。
- 手機隱藏桌面環境卡、導覽項目不被壓成直排文字。
- 鍵盤焦點清楚；`prefers-reduced-motion` 時停用動畫與平滑行為。

本機畫面證據：`reports/p2b-desktop.png`、`reports/p2b-mobile.png`。這兩個檔案屬本機生成證據並受 Git 忽略，不代表公開部署。

## 5. 驗證結果

| 驗證 | 結果 | 涵蓋內容 |
|---|---:|---|
| 後端測試 | 13/13 通過 | 首次帳號、登入、CSRF、路徑／環境污染、三個真實 MCP 工具、範圍交集、偽造欄位、單次授權、Trace 去密、stdio 逾時 |
| 前端元件測試 | 3/3 通過 | 首次設定、登入後載入、治理切頁、結構化結果 |
| 桌機／手機 E2E | 2/2 通過 | 真實服務與 MCP、Trace、390px 導覽與污染頁 |
| TypeScript／正式建置 | 通過 | 17 modules；JS 236.93 kB、CSS 13.41 kB（未壓縮） |
| Python 相依檢查 | 通過 | `pip check` 無破損相依 |
| 前端正式相依稽核 | 通過 | `pnpm audit --prod` 無已知弱點 |

驗證使用的是本機合成資料與本機環境，不等同外部滲透測試、正式企業 IAM 驗證或生產容量證據。

## 6. 已知限制與下一階段閘門

- P2-B 只有讀取；不能建立工單、核准、執行或回滾。
- 目前只完成第一位帳號建立與登入，尚無完整帳號停用、密碼重設與角色管理介面。
- SQLite 適合本機作品，沒有多副本或正式企業資料庫證據。
- 沒有 Docker／WSL、遠端 MCP、SSO、外部 IAM、外部工單系統或公開部署。
- 合成資料只能證明產品流程與邊界，不能代表真實維修成效。

進入 P2-C 前，不修改三個讀工具的歷史證據；新增的寫入能力必須採「提案 → 獨立核准 → 執行前重新驗證 → 冪等寫入 → 結果查核」，而且 admin 不得自動取得 reviewer 或 operator 權限。任何寫入都不得共用 fixture、test 或作品一資料庫。

## 7. 主要證據

- [README](../README.md)
- [P2-B 功能覆蓋矩陣](P2-B功能覆蓋矩陣.md)
- [第一階段計畫書](../第一階段計畫書.md)
- `reports/p2b-verification.json`
- `reports/p2b-desktop.png`
- `reports/p2b-mobile.png`

官方技術依據：

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK v2.2.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0)
- [MCP 規格 request `_meta`](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/index.mdx)
