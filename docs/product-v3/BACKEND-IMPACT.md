# 9. Backend Impact & API Specification

本文件詳細評估 ItemTrace V3 對後端（`shop/` 模組、資料庫架構與 HTTP API）的影響。
所有變更嚴格按照 **Level 0 至 Level 3** 進行分級，並明訂不可動搖的成熟核心資產。

---

## 1. 核心結論（Executive Verdict）

> **ItemTrace V3 實現卓越的使用者體驗，完全不需要任何 Level 3（核心資料庫破壞性改動）！**

過去實作的資料模型（SPEC-v1 §2）在概念劃分、不可變證據與可觀測性方面設計得極為扎實。
過去的問題不在於後端能力不足，而在於「前端以工程師視角將資料表平鋪直敘為網頁」。
因此，V3 的工程策略為：**最大化重複利用成熟後端資產，以 Level 0（前端革新）為主、輔以一組乾淨自足的 Level 1 與 Level 2 增量端點。**

---

## 2. 變更分級架構（Impact Levels）

```text
Level 0: 純前端即可實現（Zero backend change）
Level 1: 小型非破壞性後端調整（新增端點、擴充 schema 欄位序列化）
Level 2: 中型非破壞性後端能力（背景非同步工作佇列、PDF 報告生成、可選欄位平滑遷移）
Level 3: 破壞性資料庫模型變更（SCHEMA 重建 / 外鍵重組）──【V3 確定為 0 項！】
```

---

## 3. Level 0：純前端即可完成的體驗重塑

以下重大產品變更**完全不需要後端寫入任何一行 Python 程式碼**：

1. **時間軸整合（Unified Timeline）**：
   - 前端發起 `GET /api/items/{id}/observations` 與 `GET /api/items/{id}/events`。
   - 前端根據時間戳（`captured_at` / `created_at`）將快照與變更事件在記憶體中合併排序，並進行視覺降噪聚合。
2. **選用事實（Attributes）的結構化呈現**：
   - 直接利用現有 `items.attributes` JSON 字典。
   - 前端定義標準欄位語意：
     ```json
     {
       "acquired_date": "2026-05-12",
       "acquired_source": "PChome 24h",
       "acquired_price": "NT$ 18,900",
       "warranty_until": "2029-05-12",
       "location": "防潮箱 B 層"
     }
     ```
   - 透過現有 `PATCH /api/items/{id}` 儲存，既有搜尋 API 已自動支援 `attributes` 全文比對。
3. **完整度評級（Completeness Rating）**：
   - 純前端根據目前物品的各欄位填充率、照片數量與是否有確認識別碼計算呈現。
4. **專注審核工作台鍵盤互動**：
   - 快捷鍵綁定、照片與識別碼特寫連動等純前端邏輯。

---

## 4. Level 1：小型非破壞性後端調整規格

Level 1 變更均為**純增量（Additive）**，不修改既有表結構與舊有端點之回傳契約。

### B1-1. 單頁應用（SPA）路由靜態掛載
* **問題**：使用者在手機或桌機直接重新整理 `/i/ITM-0042` 或 `/capture` 時會遇到 404。
* **規格**：在 `shop/api.py` 的靜態服務中，加入 HTML5 History API 支援，將所有非 `/api/*` 與 `/files/*` 的客戶端路由重定向至主 `index.html`。

### B1-2. 標籤專屬 QR Code Template Bindings
* **問題**：標籤樣式需印出指向本物品履歷之 QR Code。
* **規格**：
  - 在 `shop/template_validator.py` 與 `shop/template_renderer.py` 的 `ALLOWED_BINDINGS` 加入：
    - `item.qr`（產生 QR Code SVG 或 base64 Data URL）
    - `item.url`（完整網址字串）
  - QR Code 內容為：`http://{server_ip}:{server_port}/i/{item.id}`。

### B1-3. 物品列表搜尋結果標記（Search Match Context）
* **問題**：使用者搜尋序號時，列表只顯示商品名稱，看不出是因為哪一個序號命中。
* **規格**：擴充 `ItemListOut` 輸出綱要，附加 `matched_identifier: Optional[str]`。後端在執行 SQL 搜尋時，若命中 identifiers，則順帶帶回該序號值。

### B1-4. 修改後接受端點（Edit & Accept Suggestion）
* **問題**：AI 序號差一個字元時，使用者需要能修改後一次性接受。
* **規格**：
  - 新增端點：`POST /api/suggestions/{id}/accept-value`
  - 請求體：`{"value": "6LWMF1234567"}`
  - 行為：將傳入的自訂 `value` 寫入主表（或 identifier），更新該 suggestion 之 `status='accepted'`，並在 `events` 的 payload 記錄 `{"original_ai_value": "...", "edited_value": "..."}`。

### B1-5. 重新辨識建議失效化（Supersede Suggestions）
* **規格**：在 `POST /api/items/{id}/ai/analyze` 產生新建議前，先將該物品所有既有處於 `status='pending'` 的建議更新為 `status='superseded'`。

### B1-6. 證據包 ZIP 一鍵打包下載端點
* **規格**：
  - 新增端點：`GET /api/items/{id}/evidence/download`
  - 行為：調用既有 `shop.evidence.build_bundle()` 產生檔案夾後，利用 Python 內建 `zipfile` 模組將其即時壓縮為 `ItemTrace-Evidence-{id}-{timestamp}.zip`，以串流方式回傳 `StreamingResponse(media_type="application/zip")`。

### B1-7. Capture Session 暫存檔案安全刪除端點
* **規格**：
  - 新增端點：`DELETE /api/inbox/photos/{relative_path:path}`
  - 行為：嚴格驗證該路徑必須位於 `inbox/` 子目錄內，將未提交的拍錯照片自磁碟刪除，回傳 204 No Content。

### B1-8. 資料維護 API（Backup & Verify HTTP 介面）
* **規格**：
  - 新增端點：`POST /api/settings/backup`（呼叫 `shop.db.backup()`，回傳產生的備份路徑與時間戳）。
  - 新增端點：`GET /api/settings/verify`（呼叫 `shop.db.verify()`，回傳 SQLite 與照片檔案之完整性檢查報告）。

---

## 5. Level 2：中型後端能力擴充規格

### B2-1. AI 背景非同步分析（Background Worker）
* **背景**：Vision 模型回應常需 10~30 秒，不能讓 HTTP 連線長時間阻塞，更不能阻礙使用者在手機端拍下一件物品。
* **規格**：
  - 引入簡易的背景執行緒或 `asyncio.create_task`。
  - 當建立物品或發起分析時，後端立即回傳 `{"status": "queued", "task_id": "..."}`。
  - 背景 Worker 執行完畢後寫入 `suggestions` 表並記錄事件。
  - 前端透過現有 `GET /api/items/{id}` 輪詢或在切換頁面時自動感知狀態。

### B2-2. 人類可讀之 PDF 證據報告書生成（PDF Evidence Report）
* **背景**：爭議發生時，外部人員無法閱讀 JSON 格式。
* **規格**：
  - 擴充 `shop/evidence.py`：在打包 bundle 時，調用既有已經十分成熟的 `shop/template_renderer.py` 與 `shop/print_backend.py`（Chromium Headless 管線）。
  - 載入內建的 `report_template.html`，將商品資訊、照片 Data URL、序號特寫、時間軸事件與防篡改 Hash 清單渲染為精美的 `report.pdf`，一同包入 Evidence ZIP。

### B2-3. 快照目的欄位擴充與平滑遷移（Snapshot Purpose）
* **背景**：區分「建檔」、「寄出前」、「收回」等情境。
* **規格**：
  - 在 `observations` 表新增欄位：`purpose TEXT NOT NULL DEFAULT 'intake'`。
  - 遷移策略：採用 SQLite 安全平滑遷移：
    ```sql
    ALTER TABLE observations ADD COLUMN purpose TEXT NOT NULL DEFAULT 'intake';
    ```
  - 向下相容保證：若舊資料庫尚未遷移，後端以原本的 `kind`（`intake` / `recheck` / `manual`）自動降級映射為目的顯示，絕不拋出異常。

### B2-4. 局域網連線診斷輔助
* **規格**：新增 `GET /api/system/network`，回傳主機目前啟用的區域網路 IP 位址（如 `192.168.1.100`）與連接埠，讓前端 QR Code 能自動且精準地填入正確的手機連線網址。

---

## 6. Level 3：破壞性變更審查（Verdict: NONE）

經全方位推演，ItemTrace V3 **完全不需發起任何 Level 3 變更**：
* ❌ 不需要變更 `items` 主鍵結構（`ITM-0001` 完美適用）。
* ❌ 不需要破壞 `photos` 檔案存儲架構（`files/<item-id>/original/` 是最佳實踐）。
* ❌ 不需要重構外鍵關聯或引進重型 ORM。
* ❌ 不需要引入多使用者租戶概念。

---

## 7. 嚴格保留不動之後端核心資產清單

| 資產模組 / 特性 | 為什麼絕對不可改動 |
|---|---|
| **六張核心表及約束** (`schema.sql`) | 經過 SQLite 3.49.1 嚴格實測，嚴謹的 STRICT 模式與外鍵保證了資料庫的絕對穩定性。 |
| **原始照片只增不減原則** (`shop/photos.py`) | 這是系統可信度的法理基石。任何「允許覆寫/原地裁切原圖」的改動都會直接摧毀證據力。 |
| **推論與事實分離設計** (`shop/repo.py`) | `suggestions` 表與主表獨立，是 Human-in-the-loop 的架構支柱。 |
| **序號正規化與撞號 409 語意** (`shop/ids.py`) | 去除連字號與空白的大寫正規化，以及衝突時明確由人裁決的哲學，已經完美解決硬約束導致吞錯誤的問題。 |
| **事件驅動的精確復原** (`shop/events.py`) | 復原作為新事件寫回、保留前後值的機制，滿足最高級別的可觀測性要求。 |
| **Chromium + GDI 印表機管線** (`shop/print_backend.py`) | 毫秒級 PDF 尺寸校正與 Windows 本機列印程式碼已經過精密驗證，一動不如一靜。 |
| **API Key 記憶體隔離與 Redaction** (`shop/ai_config.py`) | 密鑰永不透過 API 回傳給瀏覽器，錯誤訊息自動正則脫敏，安全模型堅不可摧。 |

