# 12. Design System & Component Library

本文件規範 ItemTrace V3 的 Design Tokens 清單與核心 UI 元件規格，為前端實作者提供嚴謹的像素級與語意級契約。

---

## 1. Design Tokens 規範（CSS Custom Properties）

```css
:root {
  /* ── 語意色彩 (Semantic Colors) ── */
  --color-brand: hsl(222, 47%, 20%);
  --color-brand-hover: hsl(222, 47%, 15%);
  --color-primary: hsl(217, 91%, 50%);
  --color-primary-hover: hsl(217, 91%, 42%);
  --color-primary-light: hsl(217, 90%, 96%);

  --color-ai: hsl(265, 85%, 62%);
  --color-ai-surface: hsl(265, 100%, 98%);
  --color-ai-border: hsl(265, 80%, 82%);
  --color-ai-text: hsl(265, 80%, 35%);

  --color-success: hsl(152, 69%, 36%);
  --color-success-surface: hsl(152, 80%, 96%);
  --color-success-text: hsl(152, 80%, 22%);

  --color-warning: hsl(38, 92%, 50%);
  --color-warning-surface: hsl(38, 100%, 96%);
  --color-warning-text: hsl(38, 90%, 25%);

  --color-danger: hsl(0, 72%, 51%);
  --color-danger-surface: hsl(0, 85%, 97%);
  --color-danger-text: hsl(0, 75%, 35%);

  /* ── 中性灰階 (Neutral Palette) ── */
  --bg-app: hsl(210, 20%, 98%);
  --bg-surface: hsl(0, 0%, 100%);
  --bg-muted: hsl(215, 20%, 94%);
  --bg-subtle: hsl(215, 20%, 96%);

  --border-default: hsl(215, 20%, 88%);
  --border-muted: hsl(215, 20%, 92%);
  --border-focus: var(--color-primary);

  --text-primary: hsl(220, 25%, 15%);
  --text-secondary: hsl(220, 15%, 45%);
  --text-tertiary: hsl(220, 10%, 65%);
  --text-inverse: hsl(0, 0%, 100%);

  /* ── 字體 (Typography) ── */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang TC", "Microsoft JhengHei", sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;

  /* ── 間距系統 (Spacing Scale: 4px Base) ── */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;

  /* ── 圓角 (Radii) ── */
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-full: 9999px;

  /* ── 陰影 (Elevation) ── */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.08), 0 2px 4px -1px rgba(0, 0, 0, 0.04);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -2px rgba(0, 0, 0, 0.04);
  --shadow-modal: 0 20px 25px -5px rgba(0, 0, 0, 0.15), 0 10px 10px -5px rgba(0, 0, 0, 0.04);

  /* ── 圖層順序 (Z-Index Hierarchy) ── */
  --z-base: 1;
  --z-nav: 50;
  --z-dropdown: 100;
  --z-sticky: 200;
  --z-sheet: 400;
  --z-modal: 500;
  --z-toast: 600;
}
```

---

## 2. 核心元件規格清單（Component Specifications）

### 2.1 按鈕元件（Button: `.btn`）

* **變體 (Variants)**：
  - `.btn-primary`：實心主色背景（`var(--color-primary)`），白色文字。用於主要完成、建檔、列印。
  - `.btn-secondary`：白色背景，灰邊框（`var(--border-default)`）。用於次要動作、取消。
  - `.btn-ghost`：透明背景，懸停呈現淺灰背景。用於圖示按鈕、關閉。
  - `.btn-danger`：紅色警告樣式。用於作廢、刪除未提交照片。
  - `.btn-shutter`：**全域懸浮相機快門鈕**（圓形 56px / 手機底部中央），白色中心環與主色同心圓，具備按壓縮放回饋（Scale 0.94）。
* **尺寸規程**：
  - `sm`：高 32px，字級 12px，內距 8px 12px。
  - `md`（預設）：高 40px，字級 14px，內距 10px 16px。
  - `lg`：高 48px，字級 16px，內距 12px 24px（手機端主力尺寸）。

---

### 2.2 輸入框與欄位（Input & Field: `.input`, `.field`）

* **結構**：
  - Label：500 字重，13px，色彩 `var(--text-secondary)`。
  - Input：高 40px，圓角 `var(--radius-sm)`，邊框 `var(--border-default)`。
  - 聚焦（Focus）：外發光 `box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15)`，邊框 `var(--color-primary)`。
* **識別碼專用輸入框（`.input-mono`）**：
  - 字型採用 `var(--font-mono)`，字元間距微幅拉寬（`letter-spacing: 0.05em`），自動將輸入內容轉換為大寫顯示。

---

### 2.3 物品卡片（Item Card: `.item-card`）

* **外觀**：
  - 白色背景，圓角 `var(--radius-md)`，邊框 `var(--border-default)`，微陰影 `var(--shadow-sm)`。
  - 上半部：4:3 比例縮圖容器，`overflow: hidden`，圖片採用 `object-fit: cover`。
  - 下半部：內距 12px。
    - 第一行：`ITM-0042`（Mono 12px）+ 狀態膠囊。
    - 第二行：商品名稱（截斷為單行，加粗 14px）。
    - 第三行：序號與最後更新時間（Caption 12px 灰色）。
* **懸停態**：邊框變為 `var(--color-primary)`，微幅向上懸浮（`translateY(-2px)`），陰影提升至 `var(--shadow-md)`。

---

### 2.4 AI 建議標籤框（AI Suggestion Pill: `.ai-pill`）

* **外觀**：
  - 背景：`var(--color-ai-surface)`，邊框：`1px dashed var(--color-ai-border)`，圓角 `var(--radius-sm)`。
  - 內含：
    - `✨` 圖示與建議文字（13px 字級，色彩 `var(--color-ai-text)`）。
    - 信心百分比（如 `88%`）。
    - 動作群組：`[ ✓ 接受 ]`（微型綠按鈕）、`[ ✎ 修改 ]`、`[ ✕ 略過 ]`。

---

### 2.5 注意事項列（Attention Strip: `.attention-strip`）

* **外觀**：
  - 位於首頁頂部，背景色淡灰藍（`hsl(215, 60%, 97%)`），邊框 `hsl(215, 40%, 88%)`，圓角 `var(--radius-md)`。
  - 條列項目間以圓形點點分隔，點擊任何項目立即路由至對應處理工作台（例如 `/review`）。
  - 右側帶有小型關閉按鈕。

---

### 2.6 時間軸節點（Timeline Node: `.timeline-node`）

* **結構**：
  - 左側骨幹軸線：`2px solid var(--border-default)`。
  - 骨幹圓點：
    - 快照節點：直徑 12px 實心主色圓點，外帶白色 2px 描邊。
    - 變更節點：直徑 8px 空心灰色圓點。
  - 右側內容卡片：
    - 快照：展示標題（目的標籤）、時間戳、註記文字，以及橫向可滾動的照片縮圖列表（高 80px）。
    - 變更：單行展示「由誰於何時修改了什麼」，帶有可展開的摺疊微按鈕。

---

### 2.7 深度照片檢視器（Deep Photo Viewer: `.photo-viewer`）

* **外觀**：
  - 全螢幕暗色遮罩（`rgba(15, 23, 42, 0.95)`），高對比展示高解析原圖。
  - 頂部工具列：照片編號、拍攝時間（EXIF/mtime）、拍攝角度徽章、關閉按鈕。
  - 底部工具列：上一張/下一張、縮放比例滑桿、重設視角、原始尺寸下載。
  - 支援手勢：手機支援雙指縮放（Pinch-to-zoom）與左右滑動切換。

---

### 2.8 提示條與即時撤銷（Toast & Undo Bar: `.toast`）

* **外觀**：
  - 懸浮於畫面底部中央（`var(--z-toast)`），深黑半透明底色（`hsl(222, 47%, 15%)`），白色文字，圓角 `var(--radius-full)`，內距 10px 20px。
  - 右側內嵌高對比的 `[ 復原 / Undo ]` 按鈕（琥珀黃文字）。
  - 顯示 6 秒後自然淡出，點擊復原即刻執行逆向操作。

