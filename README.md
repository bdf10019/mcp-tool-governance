# MCP Tool Governance｜MCP 工具整合與授權治理

A local MCP workbench demonstrating least-privilege tool access, short-lived single-use authorization, independent approval, idempotent writes, traceability, and isolated restore.

**作品二：AI 想做事，先確認它被允許做什麼。** 用循環水泵維修提案示範查詢與工單工具；權限、參數、環境和核准都通過後，才允許在本機合成系統寫入。不直接控制設備。

## 版本與功能

核心產品 **0.5.0**；離線介紹站 **1.1.0**。FastAPI／SQLite 負責帳號、提案、核准與資料治理；固定本機 stdio MCP Server 提供工具；React／TypeScript 提供可視化操作。

- 動態探索 **三個唯讀工具＋一個寫入工具**與輸入 Schema，依使用者／Profile／設備／工具取最小權限交集。
- 固定 stdio 啟動，拒絕使用者自訂命令路徑；授權短效、單次使用，綁定工具參數及環境，不把憑證寫進 Trace。
- operator 提案→獨立 reviewer 核准→執行前重新驗證；阻擋自審、管理者繞過、撤權後使用及過期政策。
- 寫入工單、執行紀錄與 outbox 在同一 SQLite 交易完成；冪等鍵、平行重送及回應遺失查回，避免重複工單。
- 首次自行建立管理者，之後管理 operator／reviewer 的角色、設備與 Profile；停用或變更帳號會撤銷既有 Session。
- 1／7 日內容保存、到期清除業務欄位及阻擋核准／重播；版本化客製設定經白名單、差異預覽、獨立核准才生效。
- checksum migration ledger 防止已套用腳本漂移；去內容備份、SHA-256 核對及唯讀隔離還原，不復活 Session／核准或自動執行工具。
- 產品、開發、測試和隔離還原各有環境指紋與資料邊界。

## 使用情境與客製化

輸入為水泵設備編號、查詢工具參數或版本化維修提案；處理為 Schema／scope／環境驗證→一次性授權→人工核准→冪等執行；輸出為工具結果、工單或拒絕原因及去憑證 Trace。

| 服務版 | 設備版 |
| --- | --- |
| 一名獨立 reviewer 核准 | 兩名不同 reviewer 核准 |
| 維修術語與服務設備範圍 | 設備術語、較嚴必填與設備範圍 |
| 可配置保存期限與提案欄位 | 同核心、不同 Profile 契約 |

設定不能放大登入者權限；舊提案保留原設定版本且失效，不被新規則悄悄覆寫。還原舊設定須建立新草稿重新核准，不刪歷史。

## 啟動核心產品

需求：Windows PowerShell、Python 3.11、Node.js 24、pnpm 11。

```powershell
.\scripts\bootstrap.ps1
.\scripts\start.ps1
```

開啟 <http://127.0.0.1:8130/>，自行建立管理者。沒有展示密碼、企業帳號、雲端工單或外部資料。相依 SDK 初次安裝需網路，實際產品操作使用本機合成資料及 MCP。

## 查看互動介紹站

```powershell
cd showcase
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm preview
```

<http://127.0.0.1:4179/>：可切客戶模式、探索四工具、scope、單／雙核准、冪等、設定、Trace 與零權威還原；僅變更瀏覽器內示範狀態，不呼叫核心 API。頁首「重置示範」可重播。

## 測試與證據

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
pnpm install --frozen-lockfile
pnpm test
pnpm build
# 本機具備 Edge 時：pnpm test:e2e
```

測試使用獨立 automated_test 資料庫，涵蓋權限、真實 stdio MCP、核准、自審、平行冪等、逾時恢復、帳號撤權、保存清理、設定治理、遷移與隔離還原。當次公開副本重跑見 [PUBLIC_VERIFICATION](docs/PUBLIC_VERIFICATION.md)，展示證據來自 [公開白名單](docs/P2-E公開資料白名單.md)，不公開原始 Trace／工單／備份。

## 限制與授權

本機 SQLite、固定 stdio MCP、合成資料不能代表企業效能；未做 Docker／Linux、遠端 MCP、正式資料庫、SSO 或真實外部工單整合。備份是治理投影，不是完整災難復原。此公開版不另外賦予原創程式開源授權，保留作者權利；第三方依既有授權，見 [LICENSE_INFORMATION](LICENSE_INFORMATION.md)及 [相依授權盤點](docs/P2-E相依授權.md)。

## 公開範圍與資料安全

此儲存庫是 2026-10-10 整理的公開來源快照，不包含舊 Git 歷史、帳號／Session、正式 SQLite、上傳文件、原始複核證據、工單內文、備份、模型權重、私有引擎或完整本機 reports。測試內固定密碼／角色是**合成測試資料**，不會植入產品帳號。執行後建立的私人狀態由 .gitignore 排除，請勿強制加入 Git。

GitHub 上公開的是原始碼與文件；本次沒有啟用 GitHub Pages，也沒有公開核心後端服務。README 中的 127.0.0.1 只適用於執行者自己的電腦。既有鎖版依賴與授權摘要保留，不宣稱完整供應鏈、資安或生產部署認證。

[公開交付契約](docs/PUBLIC_RELEASE.md) · [原產品操作資料](LOCAL_PRODUCT_GUIDE.md)

## 系列作品 / Portfolio

同一個合成情境：`EQ-PUMP-001` 循環水泵。三個產品**各自運作**，不是已串接的自動維修系統，也不控制真實設備。

| 儲存庫 | 英文｜中文名稱 | 責任 |
| --- | --- | --- |
| [pump-portfolio-showcase](https://github.com/bdf10019/pump-portfolio-showcase) | Pump Portfolio Showcase｜循環水泵互動展示 | 影片式入口與捲動式 3D 說明 |
| [ai-model-service-mlops](https://github.com/bdf10019/ai-model-service-mlops) | AI Model Service & MLOps｜AI 模型服務與維運治理 | 判斷資訊與管理模型 |
| [mcp-tool-governance](https://github.com/bdf10019/mcp-tool-governance) | MCP Tool Governance｜MCP 工具整合與授權治理 | 經授權及核准執行工具 |
| [multimodal-document-review](https://github.com/bdf10019/multimodal-document-review) | Multimodal Document Review｜多模態文件理解與人工複核 | 對照來源並整理文件 |
