# 13. Frontend Architecture Specification

本文件定義 ItemTrace V3 未來前端實作的工程架構、技術選型、目錄組織、狀態管理、檔案傳輸佇列與自動化測試策略。

---

## 1. 架構原則與技術選型（Architecture Principles & Tech Stack）

### 1.1 核心原則
1. **零編譯步驟（No Build Step / Zero-Bundler）**：
   - 延續 SPEC-v1 的極簡與敏捷原則：前端程式碼直接以現代標準瀏覽器原生支援的 **ES Modules (ESM)** 撰寫。
   - 不需要 `npm run build`、不需要 Webpack/Vite/Babel。修改 JS/CSS 檔案後，重新整理瀏覽器即可立即可見。
   - 這讓任何 Coding Agent、開發者或 Fork 專案的人皆可立即除錯，避免被現代龐雜的 npm 依賴鏈阻礙。
2. **本機優先與超輕量加載（Local-First & Featherweight）**：
   - 首頁 HTML + CSS + JS 初次載入體積壓制在 100KB 以內。
   - 即使在樹莓派或老舊筆電上執行伺服器，頁面在手機端依然能以 60fps 秒開流暢渲染。
3. **組件化純原生 Web 標準（Componentized Vanilla Web Standards）**：
   - 採用純原生 DOM API 與現代 CSS（CSS Grid, Flexbox, Container Queries, CSS Custom Properties）。
   - 以乾淨的函數式 View Functions 與自定義事件（CustomEvent）構建響應式介面。

---

## 2. 目錄結構規劃（Future Directory Structure）

未來施工時，前端程式碼將座落於專屬之 `web/` 目錄中，並由 FastAPI 靜態服務：

```text
web/
├── index.html               # 唯一的單頁應用 (SPA) 骨架
├── app.css                  # 全域樣式、Design Tokens 與所有元件樣式
├── i18n/
│   ├── zh-TW.js             # 繁體中文語系字典 (單純 Object)
│   └── en.js                # 英文語系字典
│
├── core/                    # 核心基礎設施
│   ├── api.js               # 統一封裝的 Fetch HTTP Client (帶錯誤處理與 Redaction)
│   ├── router.js            # 基於 HTML5 History API 的輕量客戶端路由器
│   ├── store.js             # 集中式微型狀態儲存 (Pub/Sub 模式)
│   ├── i18n.js              # 國際化翻譯引擎 (t() 函數與 DOM 綁定)
│   └── idb.js               # 手機照片離線與暫存專用之 IndexedDB 模組
│
├── components/              # 可重用之純 UI 元件
│   ├── button.js            # 按鈕與懸浮快門
│   ├── card.js              # 物品卡片、審核卡片
│   ├── viewer.js            # 深度高解析照片檢視器
│   ├── timeline.js          # 時間軸與快照渲染器
│   ├── attention.js         # 首頁注意事項列
│   └── toast.js             # 撤銷與操作提示條
│
├── views/                   # 完整畫面檢視
│   ├── library.js           # 物品庫首頁 (/ & /?q=...)
│   ├── capture.js           # 手機拍照建檔全螢幕 (/capture)
│   ├── dossier.js           # 物品履歷完整檢視 (/i/:id)
│   ├── review.js            # 專注審核工作台 (/review & /review/:id)
│   ├── unsorted.js          # 未整理照片批次匯入 (/unsorted)
│   ├── compare.js           # 快照雙視窗並排比對 (/i/:id/compare)
│   └── settings.js          # 系統設定子頁面 (/settings/*)
│
└── app.js                   # 應用程式入口：初始化路由、狀態與事件監聽
```

---

## 3. 客戶端路由架構（Client-Side Router）

採用無依賴之純原生 History API 路由器（`core/router.js`），大小小於 100 行：

* **監聽機制**：
  - 攔截所有 `<a href="...">` 點擊事件，若屬於內部連結則呼叫 `history.pushState()` 並觸發視圖切換，避免全頁重新載入。
  - 監聽 `window.addEventListener('popstate', ...)` 實現瀏覽器前進/後退按鈕的原生體驗。
* **路由比對與參數提取**：
  - 支援路徑變數（例如 `/i/:id` 解析出 `{ id: 'ITM-0042' }`）。
  - 自動解析 URL Query Strings（例如 `/?q=4070&status=in_hand`）。
* **後端伺服器配合**：
  - 後端 FastAPI 藉由 Level 1 變更（B1-1），將所有非 `/api/*` 與 `/files/*` 的請求一律回傳 `web/index.html`，使重新整理或直接輸入網址均可正確命中對應檢視。

---

## 4. 狀態管理模型（State Management: Pub/Sub Store）

不引入 Redux 或複雜狀態庫，採用輕量的反應式發布/訂閱（Pub/Sub）模式：

```javascript
// core/store.js 架構概念
class Store {
  constructor(initialState) {
    this.state = initialState;
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  setState(partial) {
    this.state = { ...this.state, ...partial };
    this.listeners.forEach((listener) => listener(this.state));
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const store = new Store({
  currentView: 'library',
  activeItem: null,
  reviewQueue: [],
  unsortedCount: 0,
  attentionItems: [],
  networkStatus: 'online'
});
```

---

## 5. 手機上傳佇列與離線韌性（Upload Queue & Offline Resilience）

手機拍照常面臨 Wi-Fi 訊號微弱或暫時斷線，若直接進行阻塞式 HTTP 上傳將導致照片遺失或介面凍結。

### 5.1 上傳佇列工作機制（`core/idb.js` + 上傳管理器）
1. **本地安全落盤（IndexedDB Staging）**：
   - 手機相機快門觸發後，二進位照片 Blob 立即寫入瀏覽器本地 IndexedDB，產生本地 Object URL 供托盤即時展示，**耗時 < 10ms**。
2. **背景並行上傳（Background Worker Queue）**：
   - 上傳管理器以並行限制（最大 2 條連線）將檔案透過 `POST /api/inbox/photos` 傳輸至伺服器。
   - 傳輸成功後，將本地記錄標記為 `staged`。
3. **斷線重試機制（Exponential Backoff）**：
   - 遭遇網路錯誤時，托盤縮圖標記「等待重試」，上傳管理器每隔 3s、6s、12s 自動重試。
4. **提交原子性（Atomic Commit）**：
   - 當使用者點擊「完成並建立物品」時，若所有照片皆已傳輸至暫存區，直接發起 `POST /api/inbox/intake`。
   - 伺服器建檔成功後，清空本地對應之 IndexedDB 暫存記錄。

---

## 6. 國際化多語系架構（i18n Architecture）

* **字典組織**：
  - 字典檔案為乾淨的純 JavaScript 物件（`web/i18n/zh-TW.js` 與 `en.js`），方便版本控制比對。
  - 語系鍵命名遵循模組化階層（例如 `item.name_label`、`capture.shutter_hint`、`actions.accept`）。
* **語言切換**：
  - 偏好儲存於瀏覽器 `localStorage.getItem('itemtrace.locale')`，預設為 `zh-TW`。
  - 切換語言時，全域 Store 觸發更新，畫面無刷新即時重新套用所有翻譯。
* **DOM 自動翻譯屬性**：
  - 靜態標籤使用 `data-i18n="key"`、`data-i18n-placeholder="key"` 等屬性，由引擎自動替換。
  - 動態字串呼叫全域輔助函式 `t('key', { param: '...' })`。

---

## 7. 測試架構與自動化驗證策略（Testing Strategy）

為了維護專案最高的工程水準，前端必須建立可自動化驗證的測試體系：

1. **字典完整性測試 (`tests/test_v3_i18n.py`)**：
   - Python 測試讀取 `zh-TW.js` 與 `en.js`，自動比對所有鍵值是否 100% 一一對應，無遺漏或孤兒鍵。
2. **API 契約測試 (`tests/test_api.py`)**：
   - 確保所有前端調用的 Level 0/1/2 端點皆有嚴密的狀態碼與資料綱要單元測試。
3. **無外掛 DOM 與邏輯單元測試 (Node.js Test Runner)**：
   - 透過 Node.js 內建測試或 jsdom 對 `core/router.js`、`core/store.js`、日期格式化與序號正規化邏輯進行無瀏覽器快速驗證。
4. **端到端流程驗收 (Playwright E2E Tests)**：
   - 在未來的實作階段（Phase 2/3），以 Playwright 走通 J2（拍照建檔）與 J3（審核 AI 草稿）的真實瀏覽器路徑。

