# MCP 工具治理 Showcase

作品二的獨立離線互動介紹網站。主題為 `pump-demo-v1` 循環水泵異常維修；不呼叫核心產品 API、MCP 或資料庫。

## 啟動

三作品合輯展示建議從工作根目錄執行：

```powershell
.\2026_10月合輯\scripts\showcase.ps1 -Action Status
.\2026_10月合輯\scripts\showcase.ps1 -Action Start
```

中央腳本只停止它自行啟動且能確認歸屬的程序。完整說明見 `2026_10月合輯/docs/展示啟動與復原手冊.md`。

```powershell
pnpm install --frozen-lockfile
pnpm build
pnpm preview
```

開啟 `http://127.0.0.1:4179/`。工作台 `8130` 只由訪客主動點擊，不自動探查。

重新示範：使用頁首「重置示範」；重新載入頁面也能清除本站記憶體內的互動狀態。

## 驗證

```powershell
pnpm test
pnpm test:e2e
```

公開證據由上層 `scripts/build_showcase_evidence.py` 白名單產生；不要手動複製整個 `reports` 目錄。
