# 12. Design System & Component Library

本文件規範 ItemTrace V3 的 Design Tokens 清單與生活化核心 UI 元件規範。

---

## 1. Design Tokens 清單

```css
:root {
  /* 語意色彩 */
  --color-brand: hsl(220, 45%, 20%);
  --color-primary: hsl(217, 91%, 50%);
  --color-primary-hover: hsl(217, 91%, 42%);
  --color-ai: hsl(265, 85%, 62%);
  --color-ai-surface: hsl(265, 100%, 98%);
  --color-ai-border: hsl(265, 80%, 85%);
  --color-success: hsl(152, 69%, 36%);
  --color-warning: hsl(38, 92%, 50%);
  --color-danger: hsl(0, 72%, 51%);

  /* 表面與中性色 */
  --bg-app: hsl(210, 20%, 98%);
  --bg-surface: hsl(0, 0%, 100%);
  --bg-subtle: hsl(215, 20%, 95%);
  --border-default: hsl(215, 20%, 88%);
  --text-primary: hsl(220, 25%, 15%);
  --text-secondary: hsl(220, 15%, 45%);
  --text-muted: hsl(220, 10%, 65%);

  /* 字體 */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang TC", "Microsoft JhengHei", sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;

  /* 圓角 */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-full: 9999px;

  /* 陰影 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.07);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
}
```

---

## 2. 核心元件規格清單

### 2.1 大相機快門按鈕（Floating Shutter: `.btn-shutter`）
* **外觀**：圓形，直徑 56px，位於手機螢幕底部中央。
* **樣式**：外層 3px 白色描邊，內層主色實心填充，中央帶有白色的相機或同心圓圖示。
* **微互動**：觸控點擊時微幅縮小（Scale 0.92），回彈時觸發相機原生調用。

### 2.2 紀錄卡片（Record Card: `.item-card`）
* **外觀**：白色表面，圓角 `var(--radius-md)`，邊框 `var(--border-default)`。
* **佈局**：
  - 上方：4:3 比例照片縮圖，`overflow: hidden`。
  - 下方（內距 12px）：
    - 粗體品名（14px）。
    - 副標題：品牌 · 型號（12px 次要灰）。
    - 底部：序號小標記（Mono 字型）與存放位置標籤。

### 2.3 AI 整理結果盒（AI Draft Box: `.ai-draft-box`）
* **外觀**：淡紫底色（`var(--color-ai-surface)`），邊框 `1px dashed var(--color-ai-border)`，圓角 `var(--radius-lg)`。
* **頂部標題**：帶有 `✨ AI 自動整理完成` 標題。
* **內容呈現**：整潔呈現各欄位鍵值對，序號旁附帶微型放大鏡按鈕。
* **底部動作**：全寬大尺寸主按鈕「✓ 存起來」。

### 2.4 全域搜尋列（Omni Search Bar: `.search-bar`）
* **外觀**：高度 42px，白色底色，圓角 `var(--radius-full)`，左右內距 16px。
* **佔位文字**：`🔍 搜尋品名、型號、序號、特徵...`。
* **右側捷徑標籤**：桌面端右側呈現微型鍵盤提示 `[/]`。

### 2.5 序號對齊微型放大鏡（Serial Inspector Pill）
* **外觀**：位於序號後方的小膠囊標籤。
* **互動**：點擊後在游標或畫面中央彈出半透明浮層，局部放大顯示當時拍到的標籤貼紙照片，方便使用者一眼對照字元。
