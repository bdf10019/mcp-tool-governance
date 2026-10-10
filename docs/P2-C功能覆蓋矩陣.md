# P2-C 功能互動覆蓋矩陣

| 功能 | 角色 | 頁面／互動 | 後端契約 | 測試／證據 | 狀態 |
|---|---|---|---|---|---|
| MCP 四工具 discovery | 已登入者 | 工具目錄與健康 | 官方 SDK、固定 stdio | discovery＋E2E | 完成 |
| 本機分工帳號 | admin | 帳號治理、角色卡 | 密碼雜湊、角色／scope 白名單 | API＋E2E | 完成 |
| 提案草稿 | operator | 表單、Profile 必填差異 | canonical payload、資料與政策版本快照 | API＋元件＋E2E | 完成 |
| 送審 | 原提出者 | 草稿卡「送出審核」 | 最新版本、24 小時期限 | API＋E2E | 完成 |
| 單人核准 | reviewer | service 收件匣 | 不得自審、append-only | 後端＋E2E | 完成 |
| 雙人核准 | 兩名 reviewer | asset 進度 0/2→1/2→2/2 | reviewer 唯一約束 | 後端 | 完成 |
| 要求修改／退回 | reviewer | 三種審核按鈕與理由 | 狀態轉移、理由至少 8 字 | 後端契約 | 完成 |
| 提案改版 | operator | API 已完成；正式編輯 UI 待 P2-D | 新版本、舊版 invalidated | 後端測試 | 部分完成 |
| 執行前重驗 | operator | 建立工單按鈕、asset 確認 | active／role／scope／proposal／approval／data／policy | 漂移與撤權測試 | 完成 |
| MCP 寫入 | operator | 執行狀態與回饋 | `create_maintenance_order`＋一次性 `_meta` | 真實 stdio E2E | 完成 |
| 原子交易 | 系統 | 工單結果卡 | execution＋order＋proposal＋outbox＋Trace | DB assertions | 完成 |
| 冪等重送 | operator | 查核原執行結果 | unique environment/tool/key＋request SHA | 重送與平行測試 | 完成 |
| 結果未知恢復 | operator | 安全錯誤與查核按鈕 | execution ledger | response-loss 測試 | 完成 |
| 工單探索 | viewer／operator／reviewer | 已建立工單區 | Profile 與設備交集 | E2E | 完成 |
| Write Trace | 相關 actor | Trace 頁 | 授權、MCP、commit 節點 | 後端 | 完成 |
| 帳號停用／範圍編輯 | admin | 尚無 | 後端撤權重驗已具備 | 直接資料變更測試 | 規劃（P2-D） |
| Profile 草稿／套用／還原 | admin／reviewer | 尚無 | 尚未實作 | 無 | 規劃（P2-D） |
| 備份／隔離還原 | admin | 尚無 | 尚未實作 | 無 | 規劃（P2-D） |
| 獨立介紹網站 | 訪客 | 尚無 | 無產品 API | 無 | 規劃（P2-E） |

`完成` 只代表本機合成資料與目前測試證據；不代表外部 IAM、生產部署、正式企業資料或合規認證。
