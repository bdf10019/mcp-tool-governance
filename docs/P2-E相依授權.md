# P2-E 相依與授權盤點

版本鎖定於 `showcase/package.json` 與 `pnpm-lock.yaml`。網站沒有外部字型、CDN、遠端圖片、分析服務或付費 API。

| 相依 | 用途 | 授權 |
|---|---|---|
| React／React DOM 19.3.0 | 執行時 UI | MIT |
| Vite 8.3.0／@vitejs/plugin-react 6.1.1 | 建置 | MIT |
| TypeScript 7.0.2 | 型別檢查 | Apache-2.0 |
| Vitest 5.0.0 | 元件測試 | MIT |
| Testing Library、jest-dom、user-event | UI 測試 | MIT |
| Playwright 1.63.0 | 桌機／手機 E2E | Apache-2.0 |
| jsdom 30.0.1 | 測試 DOM | MIT |
| @types/react／@types/react-dom | 型別 | MIT |

產品圖形為專案內自行製作的 HTML／CSS／SVG，未使用第三方照片、Logo 或插圖。本文件只盤點頂層直接相依；完整轉移相依由 lockfile 固定，正式對外發布前仍應再執行組織要求的授權與弱點掃描。
