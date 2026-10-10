# P2-E 視覺與無障礙驗收

日期：2026-09-27

版本：Showcase 1.0.0

## 視覺方向

- 使用「授權控制室／安全電路」語彙，以深墨綠、訊號紫、銅色和紙張底色區分允許、核准與警示。
- 首頁水泵為自行製作的 HTML／SVG 示意，不使用外部圖片、字型或 CDN。
- 每章都有可操作元件；深色章節只用於冪等與 Trace，維持長頁閱讀節奏。
- 離線示範、歷史證據與真實入口使用固定文字標籤，不只靠顏色辨識。

## 實測

- Playwright Desktop Chrome：1440 × 1000，沒有水平溢位。
- Playwright Mobile Chrome：390 × 844，沒有水平溢位；四工具、流程、表格與 Trace 改為單欄或垂直時間軸。
- 鍵盤首個焦點是「跳到主要內容」，Enter 可移動至主要區域。
- 所有自訂按鈕、Profile、工具、角色與表單都有可讀名稱及可見焦點。
- 狀態更新使用 `aria-live`；水泵 SVG 有 title 與 description。
- `prefers-reduced-motion` 會停用非必要動畫與平滑捲動。
- 列印樣式移除導覽、動態控制和浮動狀態，保留證據與限制。

## 驗收畫面

- `showcase/reports/showcase-desktop.png`
- `showcase/reports/showcase-mobile.png`

這兩張是介紹網站本身的驗收畫面，不是核心產品即時截圖。既有核心截圖包含測試帳號、隨機 ID 或本機路徑，因此沒有直接公開到 Showcase。
