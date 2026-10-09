# 9. Backend Impact & Preserved Assets

本文件詳細評估 ItemTrace V3 對後端（`shop/` 模組、資料庫與 HTTP API）的影響。

---

## 1. 核心結論（Executive Verdict）

> **成熟的後端資產是 V3 堅實的「Infrastructure（第四層底層資產）」；V3 確定零 Level 3（破壞性資料庫變更）！**

過去實作的資料模型（`schema.sql`、`repo.py`、`events.py`、`photos.py`）具備極高的工程完整性與防禦性。
V3 的產品重心轉向「拍下來，AI 幫忙記住，以後找得到」，**完全不需要推翻或重構成熟後端**，而是讓前端輕裝上陣，直接調用現有端點與少數增量 API。

---

## 2. 變更分級架構（Impact Levels）

```text
Level 0: 純前端重塑 (Zero backend code changes)
Level 1: 小型非破壞性後端端點增補 (Additive endpoints & schema outputs)
Level 2: 中型非破壞性背景支援 (Background worker & PDF packaging)
Level 3: 核心資料庫破壞性改動 (SCHEMA 重建) ──【V3 確定為 0 項！】
```

---

## 3. Level 0：純前端完成的重構項目

以下重大體驗升級**完全無需改動任何一行後端 Python 程式碼**：
1. **AI 整理結果主管驗收**：前端在使用者點擊「存起來」時，平行發起 `accept` 呼叫將整理結果寫入主表。
2. **選用生活備忘（Attributes）結構化**：直接存取現有 `items.attributes` JSON 字典（購買日期、保固到期日、存放位置），現有 `PATCH /api/items/{id}` 與全文搜尋完全通用。
3. **時間軸自然語言化**：前端將 `observations` 與 `events` 合併排序，以白話中文呈現變更與照片歷程。
4. **即時文字與序號模糊搜尋**：現有 `GET /api/items?q=` 與 `lookup_identifiers` 已完美支援兩字中文與半截序號。

---

## 4. Level 1：小型非破壞性增補端點

所有 Level 1 變更皆為純增量（Additive），不改動既有表結構或破壞既有契約：

* **B1-1. SPA 路由回退掛載**：在 `shop/api.py` 掛載靜態服務，將非 `/api/*` 與 `/files/*` 請求導向前端 `index.html`。
* **B1-2. 標籤 QR Code Template Bindings**：在 `shop/template_renderer.py` 新增 `item.qr` 與 `item.url` 支援。
* **B1-3. 搜尋結果識別碼命中標示**：在 `ItemListOut` 增補 `matched_identifier` 欄位。
* **B1-4. 整理結果微調後儲存端點**：`POST /api/suggestions/{id}/accept-value`（帶入使用者局部微調後的值）。
* **B1-5. 重新辨識建議失效化**：新一輪分析時，將舊 pending 建議標記為 `superseded`。
* **B1-6. 一鍵下載紀錄封存包 ZIP**：`GET /api/items/{id}/evidence/download`（直接串流輸出包含報告與照片的 zip）。
* **B1-7. Capture 暫存刪除端點**：`DELETE /api/inbox/photos/{path}`（清理拍攝中拍壞的照片）。
* **B1-8. 資料維護 HTTP 端點**：`POST /api/settings/backup` 與 `GET /api/settings/verify`。

---

## 5. Level 2：中型背景與進階能力

* **B2-1. AI 背景非同步分析 Worker**：拍完照片後非阻塞返回，背景執行緒處理 Vision 模型呼叫，完成後寫入資料庫。
* **B2-2. 人類可讀之 PDF 摘要報告生成**：在匯出封存包時，透過既有 Chromium 管線將紀錄渲染為 `report.pdf`。
* **B2-3. 快照目的可選欄位平滑遷移**：為 `observations` 表平滑新增 `purpose` 欄位（向下相容 `kind`）。

---

## 6. 完整保留之後端核心資產

| 後端核心資產 | 為什麼絕對不可改動 |
|---|---|
| **`schema.sql` 核心約束** | 六張核心表經過嚴密測試，STRICT 模式保證資料零壞死。 |
| **`original/` 照片不可變性** | 產品可信度與回憶保存的底層基石。 |
| **推論與事實分離設計** | `suggestions` 與主表物理隔離，守住 Human-in-the-loop 底線。 |
| **序號正規化與 409 衝突處理** | 自動去空白去連字號，由人裁決撞號，避免硬約束吞掉錯誤。 |
| **Events 變更稽核與可逆復原** | 每次修改留有軌跡，支援單欄位精確還原。 |
| **Chromium + GDI 印表機管線** | 毫米級 PDF 尺寸校正與 Windows 本機列印程式碼已經過精密驗證。 |
| **API Key 記憶體隔離與脫敏** | 密鑰絕不回傳給前端，保證本機安全性。 |

