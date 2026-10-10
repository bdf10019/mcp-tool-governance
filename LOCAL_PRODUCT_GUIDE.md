# MCP 工具整合與授權治理

這是一個可在本機操作的 AI 工具治理工作台。它示範如何把 MCP 工具探索、Schema 表單、最小權限、一次性授權、執行追蹤與資料環境隔離，整理成一般使用者也能理解的產品流程。

核心產品版本為 **0.5.0／P2-D-3**，獨立介紹網站為 **Showcase 1.0.0／P2-E**。核心具備三讀一寫、帳號／保存、Profile 設定治理、固定 checksum 的 migration ledger、去內容備份與唯讀隔離還原；介紹站用循環水泵合成案例解釋整個流程，不連接真實企業資料或外部工單系統。

## 可以實際操作的內容

- 首次啟動自行建立管理者帳號，再由管理者建立 operator／reviewer 分工帳號；沒有內建展示密碼。
- 由 MCP Server 動態探索四個工具與輸入 Schema。
- 依使用者權限與工作設定檔取交集，不允許設定檔放大權限。
- 使用固定本機 `stdio` 啟動 MCP Server，不接受使用者輸入命令或路徑。
- 每次呼叫簽發短效、單次使用、綁定參數與環境的授權上下文。
- 顯示結果來源、環境識別與 Trace；Trace 不保存授權憑證。
- operator 建立版本化提案；service Profile 需一名 reviewer，asset Profile 需兩名不同 reviewer。
- 提出者不得自審，admin 不會自動取得 reviewer／operator；執行前重新驗證撤權、資料與政策版本。
- 寫入工單、執行紀錄與 outbox 事件在同一 SQLite 交易提交；重送與平行請求由冪等鍵及唯一約束收斂為同一工單。
- 回應遺失時不盲目重試，可用原提案查回已提交結果。
- 管理者可停用／啟用帳號、重設密碼及編輯角色、設備與 Profile；變更會立即撤銷該帳號既有工作階段。
- 建立提案時明確選擇 1 或 7 日保存；到期後清除提案內容、審核理由、工單業務欄位與執行 Trace 摘要，並阻擋核准、執行及結果重播。
- admin 建立設定草稿後必須通過白名單驗證與差異預覽，再由不同 reviewer 核准；admin 不能代審。
- 套用設定會實際改變品牌、術語、設備範圍、核准人數、必填欄位及預設保存日數；舊提案保留原版本並失效，不會被靜默改寫。
- 還原不覆寫歷史，而是從曾啟用版本建立下一個新草稿，重新走完整核准流程。
- 固定 migration registry 會記錄每一步的 checksum、狀態與時間；已套用腳本發生漂移時拒絕啟動，不會默默改寫 ledger。
- admin 可先預覽備份白名單與排除內容，再以明確確認文字建立原子寫入、具 SHA-256 的去內容備份。
- 隔離還原只會建立新的 `restore_isolation` 資料庫；設定成為待驗證候選，業務關係為唯讀，Session、auth context、有效核准、自動重放與 MCP 呼叫均為 0。
- 測試備份與還原依來源環境指紋分區，且寫入測試資料庫自己的暫存根，不會混入正式產品資料。
- 以 `local_product`、`development`、`automated_test`、`restore_isolation` 分隔資料。
- 提供桌機與手機介面，以及資料污染與邊界說明頁。
- 提供獨立離線 Showcase：兩種客戶模式、四工具、scope、單／雙核准、冪等重送、設定版本、零權威還原與 Trace 均可互動；不呼叫產品 API。

## 快速開始（Windows PowerShell）

需求：Python 3.11、Node.js 24、pnpm 11。

```powershell
Set-Location 'C:\chatgpt_work\2026_10_AI 產品工程版\MCP 工具整合與授權治理\產品工程版'
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

瀏覽器開啟 <http://127.0.0.1:8130>，首次使用時建立自己的本機管理者帳號。

### 獨立介紹網站

```powershell
Set-Location .\showcase
pnpm install
pnpm build
pnpm preview
```

瀏覽器開啟 <http://127.0.0.1:4179>。介紹站完全離線展示，不需要登入；`8130` 只是一個由使用者主動點擊的工作台連結。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location .\frontend
pnpm run test
pnpm run build
pnpm exec playwright test
Set-Location ..\showcase
pnpm run test
pnpm run build
pnpm exec playwright test
```

端到端測試每次使用新的 `automated_test` 資料庫，不讀寫正式本機資料。測試結束後的暫存檔與資料庫均被 Git 排除。

## 資料與安全邊界

- 目前資料全部是專案內建立的合成資料，並標記 `source_kind: synthetic_seed`。
- API 會先建立使用者、工作設定檔、工具、資源與環境的有效交集，再簽發一次性授權。
- 工具參數中的 `role`、`user_id`、`approved` 等身分或核准欄位會被拒絕。
- 環境資料庫具有環境指紋；路徑越界、環境不符與資料庫符號連結會被阻擋。
- 此版本沒有對外部署、沒有雲端服務，也沒有真實公司或個人資料。

## 專案結構

- `backend/app`：登入、政策、提案／核准／執行、冪等、Trace、migration ledger、去內容備份與隔離還原。
- `backend/mcp_server`：使用官方 Python SDK 的固定本機 MCP Server。
- `frontend`：React／TypeScript 互動介面。
- `tests`：權限、污染邊界、真實 stdio MCP、核准、平行冪等、逾時與結果恢復測試。
- `docs`：驗收、功能覆蓋與後續階段說明。
- `showcase`：獨立 React／TypeScript 離線介紹網站、公開證據摘要及桌機／手機驗收。
- `state`、`tmp`：本機與測試資料；不提交 Git。

## 目前限制

- 帳號生命週期、提案內容保存、設定版本、migration ledger、去內容備份與唯讀隔離還原已完成本機驗收。
- 備份是白名單治理投影，不是完整災難復原；沒有雲端、排程、金鑰代管或跨機正式復原。
- P2-E 介紹網站已完成本機驗收，但不是公開託管服務，也不會建立真實工單或探查工作台狀態。
- 尚未做 Docker／Linux 部署、遠端 MCP、正式資料庫與外部身分系統整合。
- 合成資料只能證明產品流程與安全邊界，不能代表真實企業成效。

詳細設計見 [第一階段計畫書](./第一階段計畫書.md)，唯讀基線見 [P2-B 驗收](./docs/P2-B驗收.md)，安全寫入證據見 [P2-C 驗收](./docs/P2-C驗收.md)，帳號與保存治理見 [P2-D-1 驗收](./docs/P2-D-1驗收.md)，設定版本治理見 [P2-D-2 驗收](./docs/P2-D-2驗收.md)，資料遷移與備份治理見 [P2-D-3 驗收](./docs/P2-D-3驗收.md)及[契約](./docs/去內容備份與隔離還原契約.md)，介紹網站見 [P2-E 最終驗收](./docs/P2-E最終驗收.md)。
