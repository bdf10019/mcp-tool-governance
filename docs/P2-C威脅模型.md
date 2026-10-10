# P2-C 威脅模型｜核准式 MCP 寫入

日期：2026-09-24  
適用版本：0.2.0  
保護目標：不得未授權建立工單、不得重複建單、不得把測試／展示／其他作品資料寫入產品環境。

## 信任邊界

瀏覽器、表單、角色字串與 MCP 業務參數均不可信。產品後端只信已驗證 session 所對應的資料庫帳號；MCP Server 只接受產品後端簽發的一次性 `_meta` 授權 context，且仍重新查詢帳號、提案、核准、Profile、設備資料版本與環境。

`admin` 只代表帳號治理，不隱含 `operator` 或 `reviewer`。提案者與 reviewer 由不同本機帳號代表，提出者即使同時持有 reviewer 角色仍不得自審。

## 主要威脅與控制

| 威脅 | 控制 | 驗證證據 |
|---|---|---|
| 前端偽造 `role/user_id/approved` | 工具 Schema 不接受授權欄位；角色只讀資料庫 | 偽造欄位測試 |
| operator 自審 | `reviewer_id != proposer_id` 不可繞過規則 | 自審拒絕測試 |
| admin 直接核准／執行 | admin 不隱含業務角色 | admin bypass 測試 |
| 相同 reviewer 重複灌票 | `(proposal_id, version, reviewer_id)` 唯一約束；重複同決定回原紀錄 | 單／雙核准測試 |
| 修改核准後參數 | 核准綁定 canonical SHA；修改建立新 proposal version 並使舊版失效 | 改版失效測試 |
| 設備或政策版本漂移 | 執行交易內重新比較資料、Profile 與政策版本 | data version conflict 測試 |
| reviewer 或 operator 撤權 | 執行交易內重新查詢 active、roles、scope、session epoch | reviewer 撤權測試 |
| 重送／平行執行重複建單 | 後端產生冪等鍵；DB 唯一約束；`BEGIN IMMEDIATE` 交易 | 平行雙請求只產生一單 |
| 交易已提交但回應遺失 | 不重新產生請求；以原提案與原冪等鍵查 execution ledger | response-loss recovery 測試 |
| 寫入一半成功 | execution、order、proposal consumed、outbox、Trace 同一 SQLite 交易 | DB 數量與 E2E 驗證 |
| 跨環境／跨作品污染 | 固定環境根、環境指紋、路徑解析與獨立測試 DB | path／environment mismatch 測試 |
| Fixture 冒充產品寫入 | 產品只接受資料庫提案；showcase 尚未建立，fixture 不含產品 client | 環境與來源標籤 |

## 結果分類

- `definite_rejection`：Server 明確回覆版本、權限、核准或資料衝突；不會把它顯示成成功。
- `succeeded`：交易已提交並回傳 `order_id`。
- `outcome_unknown`：寫入呼叫沒有可信回應；UI 指示查核，不宣稱失敗、取消或回滾。
- `succeeded_recovered`：使用原提案查到已提交 execution 與同一工單；不建立第二張工單。

## 殘餘風險

- SQLite 與單一產品程序適合本機作品，不是多節點正式交易系統。
- 本機管理者仍能直接修改檔案或資料庫；目前的應用層控制不宣稱抵抗擁有作業系統權限的惡意管理者。
- 沒有外部 IAM、不可竄改稽核、TLS 或外部工單系統證據。
- 帳號停用與既有角色／範圍編輯尚未提供正式 UI；撤權測試目前由後端資料變更模擬，列入 P2-D。
- 合成設備與工單只能證明流程與安全契約，不能代表真實維修績效。
