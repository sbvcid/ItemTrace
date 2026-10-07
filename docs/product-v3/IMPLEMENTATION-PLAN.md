# 14. Implementation Plan, Risks & Trade-offs

本文件定義 ItemTrace V3 的未來實作分期計畫、階段性驗收標準、重大風險緩解策略與權衡取捨紀錄。
**本文件是下一個 Agent 開始執行代碼實作時的完整施工藍圖。**

---

## 1. 施工階段規劃（Phases & Milestones）

為確保開發過程嚴謹、步步為營且隨時可獨立測試驗證，實作工程分為五個循序漸進的階段：

```text
Phase 0: 後端增量準備與 SPA 基礎設施 (Backend Level 1)
   ↓
Phase 1: 核心前端骨架與基礎設施 (Core SPA & Design System)
   ↓
Phase 2: 核心主線跑通 (Capture & Dossier & QR Labels)
   ↓
Phase 3: 專注審核與進階工作台 (Review Queue & Compare & Attention Strip)
   ↓
Phase 4: 輸出交付與完備驗收 (Evidence Package & Data Tools & Hardening)
```

---

### Phase 0：後端增量準備（Backend Level 1 Preparation）
* **任務目標**：
  1. 在 `shop/api.py` 掛載 SPA 靜態路由回退（B1-1），支援 HTML5 History API。
  2. 擴充 Template Bindings，加入 `item.qr` 與 `item.url`（B1-2）。
  3. 新增建議「修改後接受」端點 `POST /api/suggestions/{id}/accept-value`（B1-4）。
  4. 新增未提交暫存照片刪除端點 `DELETE /api/inbox/photos/{path}`（B1-7）。
  5. 新增資料備份與檢查端點 `POST /api/settings/backup` 與 `GET /api/settings/verify`（B1-8）。
  6. 建立平滑遷移腳本，為 `observations` 增加 `purpose` 欄位（B2-3）。
* **完成判準**：
  - 後端所有既有測試（`tests/test_api.py`、`test_repo_*.py` 等）100% 通過。
  - 針對新增的 Level 1 端點撰寫單元測試並全數綠燈。

---

### Phase 1：核心前端骨架與設計系統（Design System & Core Shell）
* **任務目標**：
  1. 建立 `web/` 目錄結構、`index.html` 與完整 Design Tokens 之 `app.css`。
  2. 實作原生輕量路由器 `core/router.js`、狀態管理 `core/store.js` 與 API 客戶端 `core/api.js`。
  3. 建立繁體中文與英文字典（`web/i18n/zh-TW.js` 與 `en.js`）與 `core/i18n.js`。
  4. 實作基礎導覽外框：手機端底部導覽列（含懸浮快門按鈕）、桌機端側邊欄與全域頂部列。
  5. 撰寫語系鍵值完整性比對測試 `tests/test_v3_i18n.py`。
* **完成判準**：
  - 啟動伺服器後，桌機與手機瀏覽器皆能載入乾淨的應用程式外框。
  - 語系切換正常，前進後退路由無刷新運作。

---

### Phase 2：核心主線跑通（The Core Flywheel — Capture, Dossier & Labels）
* **任務目標**：
  1. **手機拍照建檔全螢幕（`/capture`）**：
     - 連拍托盤、相機觸發、IndexedDB 暫存與 `POST /api/inbox/intake` 原子落盤。
  2. **物品履歷完整檢視（`/i/:id`）**：
     - 高解析照片牆、身分與屬性展示、關鍵識別碼與來源照片標記、統一時間軸與快照渲染。
  3. **實體標籤列印對話框**：
     - 整合後端 Headless Chromium 預覽，產生含專屬 QR Code 的標籤，並支援 Windows 本機列印。
* **完成判準**：
  - 實機驗收：手機進入 `/capture` 拍 3 張照片，按下建立，立即產生新物品。
  - 桌機開啟該物品履歷，列印標籤貼紙，手機掃碼直接秒開該物品履歷。

---

### Phase 3：專注審核與進階工作台（Review, Compare & Attention）
* **任務目標**：
  1. **首頁物品庫（`/`）**：
     - 整合「注意事項列」（Attention Strip）、分類下拉選單、狀態分段（在手上/已離手/已作廢）與卡片網格。
     - 全文與半截序號模糊搜尋即時下拉預覽。
  2. **專注審核工作台（`/review` 與 `/review/:id`）**：
     - 左側照片特寫、右側建議清單、快捷鍵操作、修改後接受與逐筆序號審核。
  3. **快照並排比對器（`/i/:id/compare`）**：
     - 雙視窗同步縮放與平移檢視。
  4. **未整理照片拖放匯入（`/unsorted`）**。
* **完成判準**：
  - 建檔後物品出現在「待確認」佇列，進入專注審核可在 30 秒內完成確認。
  - 模擬退貨情境，成功在比對器中並排檢驗兩組快照照片。

---

### Phase 4：輸出交付與工程收尾（Evidence, Settings & Polish）
* **任務目標**：
  1. **證據包一鍵 ZIP 下載**：
     - 產生包含 `report.pdf`、原始照片與 `manifest.json` 的壓縮檔。
  2. **系統設定工作台（`/settings/*`）**：
     - AI 密鑰安全設定與測試、印表機偏好設定、手機連線 QR Code 引導、資料完整性驗證與備份按鈕。
  3. **錯誤與邊界處理打磨**：
     - 斷線離線提示、空狀態插圖、單欄位 Undo Toast 與歷史復原操作。
  4. **全套整合與回歸測試**。
* **完成判準**：
  - 成功下載證據包 ZIP，解壓縮確認照片與報告書完整無缺且 Hash 吻合。
  - `python -m pytest` 全套通過，無任何未處理的 Warning。

---

## 2. 重大風險與緩解策略（Risks & Mitigations）

| # | 風險名稱 | 嚴重度 | 影響層面 | 具體緩解對策 |
|---|---|---|---|---|
| **R1** | **局域網 (LAN) 連線阻礙** | 高 | 手機無法連入，飛輪起點斷裂 | ① 設定頁明確診斷網路狀態（綁定 0.0.0.0 與 IP 顯示）；<br>② 提供圖文並茂的 Windows 防火牆放行指引；<br>③ 前端提供一鍵產生手機直連 QR Code。 |
| **R2** | **外部 AI 模型服務不穩定 / 欠費** | 中 | 建議無法產生，使用者產生挫折 | ① 貫徹「AI 是加速器而非門檻」哲學，沒有 AI 系統依然能手動順暢建檔；<br>② 錯誤訊息明確分類（區分金鑰過期、額度用盡或服務商故障），絕不吞錯；<br>③ 嚴格 Redaction 保證密鑰安全。 |
| **R3** | **實體印表機驅動與紙張尺寸差異** | 中 | 標籤列印跑版或邊界裁切 | ① 沿用 PyMuPDF 毫米級校正引擎；<br>② 預覽圖嚴格與實印同源渲染（WYSIWYG）；<br>③ 提供 PDF 檔案下載作為後備列印手段。 |
| **R4** | **路由器 DHCP 導致主機 IP 變動，使舊 QR 失效** | 中 | 過去印好的實體貼紙掃碼失效 | ① 標籤上除了 QR Code 外，**必定強制印出人眼可讀的 `ITM-0042` 短碼**；<br>② 在標籤設定中允許自訂 Base URL（如指定 mDNS `itemtrace.local` 或固定 IP）；<br>③ 任何掃碼結果貼入搜尋框皆可自動提取 ID。 |
| **R5** | **原始照片只增不減造成硬碟膨脹** | 低 | 長期使用後磁碟空間緊張 | ① 手機拍照上傳時預先進行高畫質 JPEG 壓縮（不傷及細節）；<br>② 設定頁提供容量統計與磁碟監控儀表；<br>③ 允許使用者明確發起例外性的「永久刪除特定作廢物品」（Future）。 |

---

## 3. 權衡取捨紀錄（Trade-offs Summary）

1. **零編譯步驟 vs. 現代前端框架（Vanilla vs. React/Vue）**：
   - *取捨*：放棄了 JSX 與虛擬 DOM 的生態便利性。
   - *收益*：獲得了極致的透明度、零相依性、秒開速度，且任何維護者在未來十年內皆不需要面對 `node_modules` 損壞或建置套件過期的噩夢。
2. **系統相機 vs. 網頁即時取景器（System Camera vs. WebRTC）**：
   - *取捨*：拍照時需跳出至系統相機應用，每次快門多一次返回操作。
   - *收益*：在未配置 HTTPS 憑證的家庭局域網環境下依然 100% 穩定可用，且充分利用手機硬體最頂級的高動態對比（HDR）與光學防手震能力。
3. **強制逐筆核對序號 vs. 一鍵全收（Strict Verification vs. 1-Click All）**：
   - *取捨*：使用者在審核序號時必須多花 3 秒鐘眼睛對齊特寫。
   - *收益*：保證了整個資料庫的絕對真實性，守住了 ItemTrace 作為「可信履歷」的最核心底線。

