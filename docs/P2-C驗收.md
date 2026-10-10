# P2-C 驗收｜安全寫入閉環

日期：2026-09-24  
版本：0.2.0  
結論：**P2-C 本機安全寫入閉環通過；P2-B 唯讀功能維持通過。尚未開始 P2-D 設定治理與備份還原。**

## 1. 完整可操作旅程

1. 第一位 admin 在本機建立 operator 與 reviewer 帳號，不植入展示帳號或共用密碼。
2. operator 選擇 Profile 與授權設備，建立版本化提案草稿並送審。
3. service Profile 由一名不同 reviewer 核准；asset Profile 需要兩名不同 reviewer。
4. asset Profile 另要求維護時段、風險說明及執行前確認。
5. operator 執行前重新驗證帳號角色、設備範圍、提案、核准、設備資料、Profile 與政策版本。
6. 產品透過正式 MCP discovery 所列出的 `create_maintenance_order` 呼叫固定 stdio Server。
7. execution、maintenance order、proposal consumed、outbox event 與 write Trace 在同一 SQLite 交易提交。
8. 相同提案重送或平行請求取得同一 `order_id`；回應遺失時使用原提案查回結果。

## 2. 兩組客製差異

| 能力 | 維修服務 `service-v1` | 設備管理 `asset-v1` |
|---|---|---|
| 術語 | 維修案件 | 設備事件 |
| 設備範圍 | SERVICE-A | ASSET-B |
| 核准人數 | 1 名 reviewer | 2 名不同 reviewer |
| 維護時段 | 選填 | 必填 |
| 風險說明 | 選填 | 10–500 字必填 |
| 執行前確認 | 一般版本重驗 | 額外確認維護時段與風險 |

差異由 Profile 資料驅動，同一套前後端程式執行；切換 Profile 不會改變登入身分或放大設備範圍。

## 3. 安全與失敗驗收

- 提出者自審：拒絕。
- admin 未另具 reviewer：拒絕。
- asset 只有一名 reviewer：保持 `partially_approved`，不可執行。
- 核准後建立新 proposal version：舊核准保留但失效。
- 核准後設備資料版本改變：拒絕，工單數維持零。
- reviewer 角色遭撤回：舊核准不再計入有效人數。
- 單次授權重放：拒絕。
- 平行兩次執行：一筆為新建、一筆為 deduplicated，資料庫只有一張工單。
- 交易提交後模擬回應遺失：API 回 `OUTCOME_UNKNOWN`；查核取得既有工單，不重複寫入。
- MCP 寫入錯誤分為明確拒絕與結果未知，不把逾時一律宣稱「沒有寫入」。

詳細威脅與殘餘風險見 [P2-C 威脅模型](P2-C威脅模型.md)。

## 4. 互動與視覺

- 帳號治理：建立 viewer／operator／reviewer／admin 本機帳號，清楚顯示角色。
- 提案工作區：Schema 化欄位、Profile 差異、資料版本、冪等鍵尾碼與核准進度。
- reviewer 收件匣：核准、要求修改、退回及 append-only 理由歷史。
- operator 執行：asset 維護確認、錯誤回饋、結果查核與工單卡片。
- Trace：顯示 write authorization、context consume、atomic commit 與結果；不顯示完整冪等鍵或授權 token。
- 桌機與 390px 手機既有導覽持續通過。

本機成功流程截圖：`reports/p2c-write-workflow.png`。它來自每次獨立建立的 `automated_test` 資料庫，屬 test evidence，不冒充正式企業資料。

## 5. 驗證結果

| 驗證 | 結果 | 主要覆蓋 |
|---|---:|---|
| 後端 | 21/21 通過 | P2-B 回歸、帳號、單／雙核准、自審、admin、撤權、版本漂移、真實 MCP 寫入、平行冪等、結果恢復 |
| 前端元件 | 5/5 通過 | 首次設定、讀工具、結果、operator 提案頁、admin 帳號治理 |
| 桌面／手機 E2E | 3/3 通過 | 唯讀 Trace、390px 污染頁、admin→operator→reviewer→operator 真實建單 |
| TypeScript／正式建置 | 通過 | 17 modules；JS 250.46 kB、CSS 17.42 kB（未壓縮） |
| Python 相依 | 通過 | `pip check` 無破損相依 |
| 前端 production audit | 通過 | 無已知弱點 |

## 6. P2-D 前的限制

- 帳號可建立但尚無停用、密碼重設、角色／設備範圍編輯 UI。
- Profile 為固定版本種子；尚無草稿、差異、套用、匯入匯出與還原。
- 尚無保存期限執行、污染 quarantine、備份預覽與 `restore_isolation` 真實還原。
- 尚未做公開部署、Docker／Linux、外部 IAM 或外部工單整合。
- 工單目前只能建立與查看，不包含關閉或外部派工。

下一階段 P2-D 必須在不改寫 P2-B／P2-C 歷史證據的前提下，補齊帳號停用、設定版本生命週期、保存／刪除、污染隔離與備份還原；還原結果不得復活核准或自動重送工具。

## 7. 證據索引

- [README](../README.md)
- [P2-C 威脅模型](P2-C威脅模型.md)
- [P2-C 功能覆蓋矩陣](P2-C功能覆蓋矩陣.md)
- [P2-B 驗收](P2-B驗收.md)
- `reports/p2c-verification.json`
- `reports/p2c-write-workflow.png`
