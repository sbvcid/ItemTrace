# 14. Implementation Plan: Primary Loop First

本文件定義 ItemTrace V3 的未來實作分期計畫與里程碑驗收標準。
我們的策略是：**「優先把『拍照 → AI 整理 → 一鍵確認』的核心靈魂體驗做到極致，進階能力後置。」**

---

## 1. 施工階段劃分（Implementation Phases）

```text
Phase 0: 後端基礎準備與 SPA 掛載 (Backend Level 1)
   ↓
Phase 1: 前端輕量骨架與設計系統 (Core Shell & Tokens)
   ↓
Phase 2: ★ 核心靈魂主線跑通 (The Primary Loop: Capture -> AI -> 1-Tap Save -> Retrieve)
   ↓
Phase 3: 生活支援體驗 (Follow-up Additions & Everyday Attributes & Status)
   ↓
Phase 4: 進階能力與輸出 (Labels, Compare, Archive Package Export & Polish)
```

---

### Phase 0：後端基礎準備（Backend Level 1 Prep）
* **任務**：
  1. `shop/api.py` 掛載 SPA 靜態回退路由（支援客戶端 History API）。
  2. 新增建議修改後接受端點 `POST /api/suggestions/{id}/accept-value`。
  3. 新增相機暫存刪除端點 `DELETE /api/inbox/photos/{path}`。
  4. 新增資料備份端點 `POST /api/settings/backup` 與完整性端點 `GET /api/settings/verify`。
* **驗收標準**：
  - 既有全套後端測試 100% 通過，新增端點具備單元測試。

---

### Phase 1：前端骨架與設計系統（Design System & Core Shell）
* **任務**：
  1. 建立 `web/` 目錄、`index.html` 與 Design Tokens 之 `app.css`。
  2. 實作原生輕量路由器 `core/router.js`、狀態 `core/store.js`、API 封裝 `core/api.js`。
  3. 建立繁中與英文雙語字典（`web/i18n/`）與自動化字典鍵值比對測試 `tests/test_v3_i18n.py`。
  4. 實作手機端底部導覽列（含大快門鈕）與桌面端頂部全域搜尋外框。
* **驗收標準**：
  - 瀏覽器開啟即載入現代清爽外框，語系切換無刷新生效，無任何報錯。

---

### Phase 2：★ 核心靈魂主循環跑通（The Primary Loop Milestone）
這是整個 V3 最具里程碑意義的階段。完成此階段，產品就已經是一款驚豔好用的獨立工具！
* **任務**：
  1. **手機隨手拍照（`/capture`）**：
     - 大快門按鈕連拍 2~4 張，縮圖流暢滑入托盤。
  2. **AI 自動閱讀理解與整理**：
     - 拍完點完成，呼叫 Vision AI，自動提煉品名、品牌、型號、分類、序號與狀況描述（生活隨拍則彈性記錄）。
  3. **超低摩擦一鍵存起來（1-Tap Save）**：
     - 整體卡片呈現整理結果，序號附帶放大鏡對照標籤照片，點擊「✓ 存起來」直接留存。
  4. **紀錄首頁與即時搜尋找回（`/`）**：
     - 大圖卡片展示，頂部搜尋支援兩字中文與半截序號毫秒級篩選。
* **驗收標準**：
  - 實機測試：拿手機拍一件實體物品，30 秒內零打字自動整理留存完畢，首頁搜序號秒跳出！

---

### Phase 3：生活支援體驗（Supporting Experience）
* **任務**：
  1. **追加照片與生活筆記**：在紀錄詳細頁隨手追加照片或新備忘。
  2. **生活備忘維護**：支援購買日期、保固到期日、存放位置具名欄位。
  3. **狀態管理**：在手上 / 已離手狀態切換。
  4. **手機直連引導**：首頁與設定頁展示手機直連專屬 QR Code。
* **驗收標準**：
  - 使用者能隨手修改存放位置，或將賣掉的物品標記為已離手。

---

### Phase 4：進階能力與輸出交付（Advanced Capabilities & Polish）
* **任務**：
  1. **標籤列印與 QR 實體綁定**：在紀錄頁 `⋯` 呼出列印對話框，預覽含 QR 之標籤並送印。
  2. **外觀前後比對器（`/i/:id/compare`）**：雙視窗同步縮放比對。
  3. **一鍵匯出紀錄封存包 ZIP**：包含 `report.pdf`、原始照片與 `manifest.json`。
  4. **相機大批照片匯入（`/unsorted`）**。
* **驗收標準**：
  - 印表機輸出實體貼紙，手機掃碼秒開該紀錄；一鍵下載封存包 ZIP。
  - 全套 pytest 回歸測試全綠。

---

## 2. 重大取捨紀錄（Trade-offs）

1. **核心極簡 vs. 功能面面俱到**：
   - 我們選擇將 80% 的精力投入在 Phase 2（拍照 → AI 整理 → 確認），確保核心神級體驗無可挑剔。特殊需求（如並排比對、紀錄封存包）收攏在進階層級，避免第一階段就背負過重包袱。
2. **開源零建置 vs. 現代打包框架**：
   - 堅守純原生 ES Modules，任何人隨手克隆程式碼即可啟動，保證長期維護極致輕快。
