# 13. Frontend Architecture: Zero-Build & Open Source Friendly

本文件定義 ItemTrace V3 前端實作的工程架構、目錄組織與開源友善原則。

---

## 1. 核心原則：開源、透明、零建置（Zero-Build Strategy）

ItemTrace 是為開源社群與個人自用打造的軟體。我們選擇**完全摒棄大型的前端編譯工具鏈**（如 Webpack/Vite/Babel/npm），全面採用瀏覽器原生支援的 **ES Modules (ESM)**：

1. **開箱即用**：任何人 git clone 下來，不需要執行 `npm install` 裝幾百個依賴套件，直接啟動 Python 伺服器就能跑。
2. **極致透明**：每一行 JS 和 CSS 都是可讀的原始碼，任何開發者或 Coding Agent 打開就能看懂、改了立刻見效。
3. **十年長青**：不受前端打包工具生命週期變更（如工具棄用、版本破壞性升級）的困擾。

---

## 2. 目錄組織規劃（`web/` Directory Structure）

未來實作階段，前端程式碼將座落於乾淨的 `web/` 目錄：

```text
web/
├── index.html               # 唯一的現代單頁應用 (SPA) 容器
├── app.css                  # 全域樣式、Design Tokens 與所有元件樣式
├── i18n/
│   ├── zh-TW.js             # 繁體中文語系字典 (純 JS 物件)
│   └── en.js                # 英文語系字典
│
├── core/                    # 輕量基礎核心
│   ├── api.js               # 統一 Fetch HTTP Client 封裝
│   ├── router.js            # 純原生 History API 路由器 (< 80 行)
│   ├── store.js             # 簡易 Pub/Sub 狀態容器
│   └── idb.js               # 手機相機照片暫存專用之 IndexedDB 模組
│
├── components/              # 輕量純原生 UI 元件函式
│   ├── shutter.js           # 手機相機大快門按鈕
│   ├── card.js              # 紀錄大圖卡片
│   ├── draft-box.js         # AI 整理結果盒 (含放大鏡)
│   └── search-bar.js        # 全域搜尋列
│
├── views/                   # 畫面視圖
│   ├── library.js           # 紀錄首頁 (/ & 搜尋)
│   ├── capture.js           # 拍照記錄 (/capture)
│   ├── item-detail.js       # 紀錄詳細與生活備忘 (/i/:id)
│   └── settings.js          # 系統設定 (/settings)
│
└── app.js                   # 入口檔案：啟動路由與全局事件監聽
```

---

## 3. 核心基礎設施實作規格

### 3.1 輕量客戶端路由器（`core/router.js`）
* 攔截內部 `<a>` 連結點擊，調用 `history.pushState()` 切換視圖。
* 監聽 `window.onpopstate` 原生支援瀏覽器上一頁/下一頁。
* 自動解析動態路徑參數（例如 `/i/:id` 解析出 `{ id: 'ITM-0042' }`）。

### 3.2 手機拍照暫存佇列（`core/idb.js`）
* 手機觸發快門後，影像 Blob 立即寫入瀏覽器 IndexedDB，產生物件 URL 供托盤秒顯。
* 背景非同步傳送至伺服器暫存；若遇斷線，本地保留暫存，連線恢復自動續傳。

### 3.3 國際化翻譯（`core/i18n.js`）
* 字典使用純物件結構，偏好儲存在 `localStorage['itemtrace.locale']`。
* 提供全域輔助函式 `t('key')` 與標籤屬性 `data-i18n="key"`，切換語言無刷新重新渲染。
