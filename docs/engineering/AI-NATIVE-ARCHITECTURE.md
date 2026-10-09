# ItemTrace AI-Native Architecture Study

- 狀態：**研究階段（architecture study）** —— 本文件不變更產品程式碼、schema、資料或測試。
- 日期：2026-10-09
- 基線：`main @ 98edc0c`（領先 `origin/main` 4 commits，未 push）；`pytest -q` 實測 **928 passed / 0 failed / 0 skipped**。
- 文件性質：研究與建議。文中明確區分 **【已驗證】**（可直接指向程式碼/測試）、**【推論】**（由證據導出但未經實驗證實）、**【建議】**（本研究提出的方向）、**【未解】**（需要更多證據才能決定）。

> 本研究的問題：**如何讓 ItemTrace 的 AI 行為可以持續演化，而不用反覆重構整個應用？**
> 目標不是「更完整的固定 schema」，而是找出**最小、可靠、可演進的軟體基礎**。

---

## 0. 研究方法與限制

【已驗證】本文件的事實依據來自實際閱讀（非僅文件轉述）：

- 資料層：`shop/schema.sql`、`shop/models.py`、`shop/repo.py`、`shop/db.py`、`shop/events.py`、`shop/ids.py`
- 檔案與媒體：`shop/photos.py`、`shop/inbox.py`、`shop/evidence.py`
- AI 層：`shop/ai_client.py`、`shop/ai_config.py`、`shop/settings.py`、`tools/analyze_item.py`
- API：`shop/api.py`（全部路由）、`shop/schemas.py`
- 前端：`web/app.js`、`web/core/{router,api}.js`、`web/views/{capture,home,record-detail,settings}.js`、i18n
- 規格與產品文件：`SPEC-v1.md`、`docs/product-v3/*`、`docs/engineering/*`
- 測試：`tests/`（抽查 void/刪除語意、search、suggestions、AI provider 錯誤、v3 端到端）
- 基線重跑：`pytest -q`（928/0/0）

限制（誠實聲明）：

- 未呼叫任何外部 AI provider，未做模型實測；效能數字引用現有規格/測試結論，未重新 benchmark。
- 未執行瀏覽器端到端測試（本研究只讀程式碼；前一 Phase 的瀏覽器煙霧測試結果見 STATUS）。
- 未檢視未追蹤/未 commit 的任何外部工作。

---

## 1. 已驗證的現狀（Verified Current State）

### 1.1 資料模型：Item 是唯一的「紀錄」實體

【已驗證】`shop/schema.sql` 定義六張核心表 + `templates` + `schema_meta`，全部 STRICT：

- `items`（:4-18）：固定欄位 `name/brand/model/category/quantity/condition/notes` 皆 `NOT NULL DEFAULT ''`，外加 `attributes TEXT NOT NULL DEFAULT '{}'`（JSON）、`status CHECK IN ('active','archived','void')`、`created_at/updated_at`。
- `observations`（:20-29）：`item_id NOT NULL REFERENCES items(id)`；kind `intake|recheck|manual`。
- `photos`（:31-50）：`item_id NOT NULL REFERENCES items(id)`；`role original|derived`；`sha256`、尺寸、`captured_at`、`angle`。
- `identifiers`（:52-70）：`item_id NOT NULL REFERENCES items(id)`；kind `serial|imei|barcode|custom`；`normalized`；`UNIQUE(item_id, kind, value)`（刻意不做全域唯一，撞號由 API 回 409）。
- `suggestions`（:72-86）：`item_id NOT NULL REFERENCES items(id) ON DELETE CASCADE`；`field` 自由文字（驗證在程式層）；`confidence`、`model_name`、`source_photo_id`、`status pending|accepted|rejected|superseded`。
- `events`（:88-102）：`entity_type/entity_id/type/actor/field/prev_value/next_value/payload`，entity_type 白名單見 `shop/events.py:16`。

**關鍵結構事實**：任何照片、觀測、識別碼、建議都必須隸屬於某個 `items` 列（FK `NOT NULL`）。「每張照片都對應一個 Item」是 schema 層的硬約束，不是慣例。

【已驗證】`items.attributes` 已是官方擴充點：

- `ITEM_EDITABLE_FIELDS` 包含 `attributes` 與 `status`（`shop/repo.py:62-65`），`ItemPatch` 亦開放兩者（`shop/schemas.py:60-72`）。
- 搜尋涵蓋 attributes 字串（`shop/repo.py:209`）。
- DECISIONS D2（`docs/engineering/DECISIONS.md`）已接受「JSON 動態屬性 + 固定欄位分離」策略。

### 1.2 保存語意與資料安全（現行刪除行為）

【已驗證】刪除語意高度保守（`shop/repo.py:14-28` 明確記載）：

| 對象 | 目前允許的操作 | 證據 |
|---|---|---|
| `items` | 只能 `void`（`status='void'`），資料與檔案全保留；無 `deleted_at`；**沒有任何 item 刪除路徑** | `repo.py:332-334`、`SPEC-v1.md:173-198` |
| `photos` | 只可刪 `role='derived'`；`original` 需先改 role 才可刪（明確表態） | `repo.py:508-526`、`api.py:417-420` |
| `identifiers` | 可刪，但 `identifier.deleted` 事件保留完整快照 | `repo.py:612-623` |
| `observations` / `suggestions` | 不刪；suggestion 接受/拒絕皆保留（推論與事實分離） | `repo.py:14-28`、`repo.py:782-801` |
| 永久刪除 | 規格允許「使用者明確決定的一次性刪除」，但 **API/UI 尚未實作** | `SPEC-v1.md:180-192`、`repo.py:24-28`、`tests/test_phase10_docs.py:106` |

其他不可破壞的保證：

- 原始照片位元組保存：檔名碰撞加流水號、永不覆寫（`inbox.py:293-307`）；SHA-256 去重與撞號回報（`inbox.py:250-277`、`repo.py:803-816`）。
- 資料與事件同交易（`db.py:45-64`）；單欄位復原（`events.py:97-117`、`repo.py:856-878`）。
- 檔名相對路徑 + 資料夾自足（`repo.py:1175-1188`、`config.py`）。
- 備份/驗證只有 CLI（`shopctl.py`：init/stats/verify/backup），**無 HTTP 端點**。

### 1.3 AI 層：單一固定契約的「整理員」

【已驗證】目前的 AI 能力是一個非常窄、非常嚴格的介面：

- **單一 prompt**（`shop/ai_client.py:42-63`）：定位為「商品建檔的輔助」，只列 8 個欄位（name/brand/model/category/condition + identifier:serial/imei/barcode）；規則要求「不確定就不要輸出」，完全讀不到就回空陣列。
- **白名單強驗證**：`ALLOWED_FIELDS`（`ai_client.py:31-40`）；`parse_suggestions` 逐筆驗證 field/value/confidence/source_photo_index，**任何一筆不合規就整批失敗**（`ai_client.py:484-555`）。
- **回應格式**：`RESPONSE_SCHEMA` 以 JSON Schema 固定列舉欄位（`ai_client.py:133-153`）；只有 OpenRouter 端送 `response_format`（`ai_client.py:220-228`）。
- **單次呼叫、無工具、無重試**：一次請求一批照片（≤8 張，`:70`），temperature 0（`:218`），失敗即失敗（`:380-384`）。
- **AI 不能寫事實**：輸出只能是 pending suggestions；接受才由 `accept_suggestion` 寫入主表（`repo.py:735-780`）。`suggestions.field` 驗證限於 `SUGGESTABLE_FIELDS` 或 `identifier:<kind>`（`repo.py:1218-1235`）——**AI 今天無法提議任意屬性**（例如發票的 vendor/amount/date）。
- **外部 adapter 的結構性邊界**：`tools/analyze_item.py` 的 client 只允許 4 條路由（GET item、GET suggestions、GET files、POST suggestions），accept/PATCH 沒有呼叫途徑（`analyze_item.py:114-179`），並在收尾時驗證「items 欄位未被修改」（`:243-257`）。
- **模型可換、後果可追溯**：provider/base_url/model 存於 `tools/ai_config.local.json`（`ai_config.py:39-48`），suggestions 記錄 `model_name`（`schema.sql:79`）——換模型不影響既有紀錄，且每筆 AI 值可回溯是哪個模型提的。
- **安全**：key 不回傳前端（`settings.py:1-25`）、寫入端點限 loopback 或信任區網（`settings.py:54-67`）、錯誤訊息 redact（`ai_config.py:380-388`）。
- **`superseded` 狀態已定義但從未被賦值**（`models.py:46` 是唯一出現處）——B1-5「重新分析時舊 pending 失效化」是計畫，尚未實作。

### 1.4 搜尋：完全由 LIKE 決定，無索引、無 AI

【已驗證】`repo.list_items` 的 `q` 是對 `name/brand/model/category/notes/attributes` 與 identifiers 的 `value/normalized` 做 LIKE 子字串比對（`repo.py:199-219`）；半截序號用正規化 LIKE（`repo.py:231-250`）。SPEC-v1 §7.2 以實測否決 FTS5（兩字中文 0 命中）。**沒有任何搜尋索引實體存在** —— 搜尋是每次即時計算，無需維護、天然可重建（擴充點提到的 FTS5 屬 Phase 4/5）。搜尋不含 AI 改寫、同義詞或語意擴展。

### 1.5 API 面

【已驗證】主要端點（`shop/api.py`、`settings.py`）：

- Items：`GET/POST /api/items`、`GET/PATCH /api/items/{id}`、`POST /api/items/{id}/void`；列表預設 `created_at DESC`（Phase 1B-A）。
- Observations/Photos：觀測 CRUD（無刪除）、照片上傳（multipart，重複入 skipped 不失敗）、`DELETE /api/photos/{id}`（限 derived）。
- Identifiers：CRUD、`GET /api/identifiers/lookup?value=`（正規化模糊）、新增撞號 409 + 既有清單（`api.py:438-477`）。
- Suggestions：建立（外部）、列表、`accept`/`reject`、`POST /api/items/{id}/ai/analyze`（照片→provider→嚴格解析→寫 pending 建議；`api.py:557-627`）。
- Events：`GET /api/items/{id}/events`、`POST /api/events/{id}/revert`。
- Evidence：`GET /api/items/{id}/evidence/export`（產生 bundle 目錄）+ `/file?path=`（讀單檔）；**不是 ZIP、無 PDF**（`evidence.py`、`api.py:665-697`）。
- Inbox：`GET /api/inbox`、`POST /api/inbox/photos`、`POST /api/inbox/intake`、`POST /api/inbox/group`。
- Settings：AI 設定讀寫/測試、列印設定；**無 backup/verify HTTP**。
- 系統：`GET /api/health`、`GET /api/stats`。

### 1.6 前端流程

【已驗證】零建置 ESM SPA（router + api client + 4 views + 2 locales）：

- Capture（`web/views/capture.js`）：拍照/選檔 → `POST /api/inbox/photos` → `POST /api/inbox/intake`（一次拍 = 一個 item）→ `POST ai/analyze`（**失敗非致命**，`:296-302`）→ 審閱畫面（顯示「看見/推測」信心徽章、序號可對照來源照片、可局部編輯）→ 儲存 = 並行 `accept` 所有建議 → PATCH 手動修改 → 必要時 `addIdentifier` → toast + 回首頁 `/?fresh=<id>`（`:481-532`）。
- 觀察（【已驗證】並列為可靠性缺口）：`accept` 失敗只 `console.warn` 後照常繼續（`capture.js:489-494`）；保存成功提示可能與部分建議未寫入並存。
- Home：搜尋（`GET /api/items?q=`）、最新一筆 featured、其餘緊湊卡；`home.js:207` 讀 `item.matched_identifier`，但 API 從未回傳此欄位（B1-3 未實作），目前永遠退回顯示 model。
- Detail（`record-detail.js:119-157`）：只渲染 brand/model/category/serial/condition/notes；**不渲染 attributes、沒有編輯、沒有歷史、沒有追加觀測、沒有 `⋯` 選單**。
- Settings：語言、provider/model/key、連線測試。

### 1.7 文件 vs 實作的事實核對

【已驗證】`BACKEND-IMPACT.md` 宣示「V3 零 Level 3（破壞性 DB 變更）」（:9-23）與 Level 1 增補清單（:41-48）。對照實作：

| 計畫（BACKEND-IMPACT.md） | 實作現況 |
|---|---|
| B1-1 SPA 路由回退 | ✓ 已實作（`api.py:137-156`） |
| B1-2 Template QR/URL 綁定 | 未逐項驗證（本研究的非核心） |
| B1-3 `ItemListOut.matched_identifier` | ✗ 未實作；前端已先讀（`home.js:207`） |
| B1-4 `accept-value` 端點 | ✗ 未實作；改以 accept+PATCH 組合達成（`capture.js:497-512`） |
| B1-5 舊 pending 標 `superseded` | ✗ 未實作（狀態值閒置） |
| B1-6 evidence ZIP 下載 | ✗ 未實作（目錄 bundle + 單檔端點替代） |
| B1-7 inbox 照片刪除端點 | ✗ 未實作 |
| B1-8 backup/verify HTTP | ✗ 未實作（只有 `shopctl.py` CLI） |
| `core/store.js`（IMPLEMENTATION-PLAN.md:38） | ✗ 不存在；狀態是各 view 區域變數 |
| AI 產出生活隨拍的「生活化標題與描述」（AI-EXPERIENCE.md:54-58） | ✗ prompt 沒有 description 欄位；非商品照片 AI 回空陣列，使用者需手動命名 |

【推論】產品文件描述的是目標體驗；資料/API 基礎大致就緒，**缺口集中在「AI 提案的表達力」與「前端可視化/可編輯性」**，而非資料模型本身。

---

## 2. 限制 AI 自主性的假設（與其正當性）

逐項檢驗任務指定的六個假設。【已驗證】= 程式碼證據；判定區分「必要約束（integrity/security/usability/technical）」與「歷史設計選擇」。

### A1. 每張保存的照片都必須代表一個 Item

- 證據：`photos.item_id NOT NULL`（`schema.sql:33`）；intake 一律建 item+observation（`inbox.py:180-187`）。
- 判定：**技術/完整性約束的殼，歷史語意的芯**。媒體必須有歸屬（可搜尋、可匯出、可稽核、防孤兒），這個 FK 是合理的完整性手段；但「Item＝物品」是 v1 語意。V3 產品原則 P5 要的是「彈性產物」（`PRODUCT-VISION.md:60-61`），而現行非商品照片＝欄位全空的 Item（測試已驗證可行：`tests/test_v3_core_slice.py` Scenario C）。**修正成本最低的路是把 Item 重新詮釋為「紀錄信封（record envelope）」，而不是拆掉 FK 或另立 Record 實體。**

### A2. 每筆紀錄都應該有相同欄位

- 證據：`items` 固定欄位全 `NOT NULL DEFAULT ''`；但 `attributes` JSON 已是任意鍵值擴充點（`schema.sql:13`）；PATCH 可寫 attributes。
- 判定：**已被現有設計部分否證**。真正僵固的不是儲存（JSON 可存任何屬性），而是「AI 只能提議固定欄位」——`_validate_suggestion` 把 AI 的 field 限制在 8 個值內（`repo.py:1218-1235`）。這是**歷史選擇**，不是完整性要求；放寬有明確、可驗證的安全邊界（命名空間 + 值驗證 + 大小限制）。

### A3. 分類/分類法必須由設計者窮舉

- 證據：`category` 是自由文字；prompt 只給例子（`ai_client.py:48`）；`distinct_categories()` 從已用資料反推（`repo.py:290`）；沒有 taxonomy 表。
- 判定：**現況並未這樣假設**（好事）。代價是沒有同義詞整併（「電腦零件/主機板」vs「主機板」並存），這屬 Phase 4 的正規化問題，不是 AI 自主性的阻塞點。

### A4. AI 必須遵循預先決定的步驟序列

- 證據：管線固定為 拍照→intake→單次 analyze（單一 prompt、一次呼叫）（`api.py:557-627`、`ai_client.py:371-409`）；沒有工具選擇、沒有多步、沒有「再看一眼標籤」的能力。
- 判定：**當前最大的自主性限制，且不是技術必然**。provider 層是通用 OpenAI 相容 chat（可支援 tools/多輪），現行只是「單呼叫 + 嚴格驗證」最簡實作。限制的另一面是安全：任何擴權都必須經 capability 端點，不得給任意 DB/FS 存取（SPEC-v1 §12 明確不做 agent runtime）。

### A5. 每個新用例都需要新欄位或明確工作流

- 證據：`notes` 是後加的（`models.py:51-53` 註解「Phase 8A 起加上」）；發票/寵物/待辨識零件今天沒有表達途徑——AI 只能從 8 欄位作答，使用者只能手打 name/notes。前端也無屬性編輯 UI。
- 判定：**成立，且是歷史耦合的產物**。但修復它不需要動 schema：把「提案表達力」從固定欄位放寬為「固定欄位 ∪ 命名空間屬性」即可吸收多數新用例。

### A6. 搜尋行為必須事先完全指定

- 證據：LIKE 欄位清單寫死（`repo.py:199-219`）；SPEC-v1 §7 以表格凍結驗收案例。
- 判定：**部分必要（可預測性/可測試性），部分歷史**。因為 attributes 也在 LIKE 範圍內，只要 AI/使用者把文字寫進這些欄位，檢索就自動涵蓋——「擴充檢索範圍」目前等同「擴充可見文字」，成本低。缺的是：AI 無法在查詢端補同義詞/口語改寫；資料量大後的索引策略未定（Phase 5）。

### A7.（補充）AI 產出必須逐筆由人接受才成為事實

- 證據：suggestions 隔離（`SPEC-v1.md:29`）；`accept_suggestion` 才寫主表（`repo.py:735-780`）；外部 adapter 結構上無法 accept（`analyze_item.py:114-127`）。
- 判定：**這是刻意的產品/安全底線（Human-in-the-loop）**，BACKEND-IMPACT 也列為不可改動資產（:60-70）。本研究建議維持，但可討論「低風險欄位自動接受」的政策（見 §8 Q3）。注意實作缺口：前端 `accept` 失敗被吞（`capture.js:489-494`），使「已確認」可能部分成立——這是可靠性問題，應在任何擴充前修好。

---

## 3. 現實用例評估（Architecture Options × Use Cases）

以「不用過度打字、不頻繁改 schema、不丟失資訊」為判準，評估現況（A）與候選方向（B/C/D 見 §4）：

| # | 用例 | 現況（A）已驗證行為 | 缺口 | 由哪個選項解決 |
|---|---|---|---|---|
| 1 | 可辨識商品（品牌/型號/序號） | 完整支援（Scenario A 測試；prompt 針對此設計） | 無 | A 已足夠 |
| 2 | 無法辨識的零件＋不確定屬性 | AI 可給 name/category/condition；不確定就留空 | 無法記錄「疑似 M.2 2280，不確定」這類自訂屬性 | D（attribute 提案） |
| 3 | 收據/文件 | AI 幾乎無用（不在欄位白名單）；只能塞 notes 或手打 | 無 vendor/amount/date 表達與檢索 | D |
| 4 | 寵物/人物/風景/地點 | 可保存（Scenario C）；AI 回空陣列，使用者手動命名 | AI 不產生生活化標題/描述（與 AI-EXPERIENCE 2.2 不符） | D（description/title 提案） |
| 5 | 多張照片指向同一對象（跨場次） | 同場次＝一個 item；跨場次＝多個 item；同 item 內以 sha256 擋完全重複 | 無近似重複/合併/關聯 | D 之後的關係提案（propose-only）；證據先行（§8 Q6） |
| 6 | 保存後追加脈絡 | 後端完備（observations、上傳、PATCH、events/revert） | V3 前端完全沒有入口（detail 是唯讀） | 前端工作（與架構無關） |
| 7 | 不完整/口語搜尋 | LIKE 子字串 + 序號正規化（涵蓋 attributes） | 無同義詞/口語改寫；「充電頭」找不到「電源供應器」 | D（查詢端 AI 擴充，後期）；索引策略 Phase 5 |
| 8 | 修正 AI 判讀 | 審閱畫面可局部編輯；保存後可 PATCH；建議可 reject | 保存後前端無編輯入口；無「來源照片對照」UI；accept 失敗被吞 | 前端工作 + D（來源可溯性已有資料基礎：suggestion row + events） |
| 9 | 還原/永久刪除 | void ↔ active（PATCH status）；**無永久刪除** | 無垃圾桶 UI/還原 UI；永久刪除屬 Phase 3 規格 | 屬 ROADMAP Phase 3，本研究不變更 |
| 10 | 換 AI provider/model 且保留紀錄 | 設定檔切換；每筆 suggestion 記 model_name；既有已接受值不受影響 | 無評測/回歸比較工具 | D（S4 評測 harness） |

【推論】現行架構在第 1、4、9、10 類已足夠或接近足夠；第 2、3、7、8 類的核心瓶頸都是同一件事：**AI 提案的表達力（可用哪些欄位/屬性）與其可視化**，而不是儲存模型。

---

## 4. 架構選項比較

### 選項定義

**A. 維持 Item-centric，按需擴充白名單**
保持六表與「AI 提議固定欄位」不變；每遇到新用例就把新欄位加進 `ALLOWED_FIELDS`/prompt/UI/測試。

**B. Record-first：通用 Record 為主體，Item 資訊退化為可選擴充**
新的主保存單位 Record（含 kind/media/描述），Item 變成 Record 的一種 typed extension。需要重寫 FK 拓撲、ID/資料夾命名、API 契約與前端。

**C. 最小持久基礎 + 執行期 AI 詮釋**
持久層只保證媒體與最小信封；AI 在執行期產生/修訂 typed interpretations（屬性集、描述、分類），版本化保存。

**D.（本研究建議）穩定信封 + 版本化型別提案層 —— 在現有 schema 上實現 C 的精神**
保留六表與所有安全保證；把 `suggestions` 從「固定欄位提案」升級為「命名空間提案」（固定欄位 ∪ `attribute:<key>` ∪ 描述），啟用既有但閒置的 `superseded` 狀態做修訂，維持「人接受才成事實」；以評測 harness 管模型替換。**不新增 Record 實體、不新增詮釋資料表**，除非證據要求（見下）。

### 比較（以本研究驗證過的事實為基礎）

| 維度 | A（現況） | B（Record-first） | C（通用最小基礎） | D（信封＋提案層） |
|---|---|---|---|---|
| 概念複雜度 | 低 | 中高（兩層實體＋遷移期雙心智） | 中（interpretation 為新概念） | 低中（沿用既有 6 表與 suggestions 概念） |
| 實作成本 | 每用例小但重複 | 極高（一次性全面改） | 中（新儲存＋驗證＋UI） | 低（契約＋驗證＋UI；無 schema 變更） |
| 可搜尋性 | 好（LIKE 已涵蓋 attributes；`repo.py:209`） | 需把 Record+extensions 映射進檢索（更多工作） | 需為 interpretation 建立檢索策略 | 好（沿用現行 LIKE；屬性自動可搜） |
| 可擴充性 | 差（每欄位＝程式碼變更） | 好 | 最好 | 好（命名空間＋版本化契約；欄位演化不需 schema 改動） |
| 遷移風險 | 無 | 高（FK/ID/資料夾/API/前端全套） | 中（新表＋雙寫或回填） | 極低（全部 additive；attributes 已是正式欄位） |
| 模型獨立性 | 好（單一相容層） | 同 | 同 | 好＋（每筆 model_name 已存在；補評測回歸） |
| 可測試性 | 高 | 遷移期低 | 中 | 高（contract tests + fixtures；928 測試不受影響） |
| 失敗復原 | 完善（events/交易/原始檔） | 遷移正確性風險 | 需設計 | 完善（沿用；無資料搬家） |

### 為什麼不是 Record-first（B）

【推論】證據不支持現在改：

1. 現行 `items` 實質上已是「信封＋固定欄位＋JSON 擴充」，B 能給的語意好處（非物品紀錄不是二等公民）其實可以靠**語意重新詮釋＋提案表達力**取得，不需要動拓撲。
2. B 的成本是全專案級的：photos/observations/identifiers/suggestions 的 FK、`ITM-xxxx` ID 與資料夾名、`/api/items/*` 契約、主頁/詳情/搜尋/匯出/列印全部受影響；928 個測試與 `files/` 版面相容都是風險面。
3. 「Record」若只是改名，是無收益風險；若真是新實體，它必須先滿足「多種紀錄各自擁有子表」的證據（今天沒有）。
4. SPEC-v1 的路線圖已預告擴充方式是「加表不改表」（`SPEC-v1.md:557-558`），與 D 相容。

**會改變結論的證據**（明確列出）：
- 出現 ≥2 種「擁有自己子表/自己的刪除與保留策略」的一級紀錄型態（例如文件、對話、批次），用 attributes 表達開始造成查詢/驗證/UI 的系統性例外；
- 使用者資料顯示大量非商品紀錄（例如 >30% 的 items 是空 brand/model 的生活照）且現行 Item 語意漏進 UI/搜尋造成實際困擾（需要可觀測的使用者回饋或本機統計）；
- 產品決定支援「不屬於任何信封的媒體」（孤兒媒體合法化）——此與現行防孤兒完整性原則衝突，需先解安全性問題。

### 為什麼 D 是「剛好最小」的 C

【建議】C 的精神（AI 在執行期決定相關屬性）不需要新實體即可達成，因為：

- 事實儲存已存在且經過測試：`items.attributes`（JSON）＋ `items` 固定欄位；
- 推論隔離已存在：`suggestions`（pending/accepted/rejected/**superseded**）＋ `model_name` ＋ `source_photo_id`；
- 可溯性已存在：`events`（`field.changed` 帶 prev/next、actor）＋suggestion row 本身（accepted 後仍保留，是 AI 值的來源紀錄）；
- 檢索已存在：LIKE 涵蓋 attributes 字串；
- 缺的只是三件事：**(1) 提案欄位的命名空間放寬；(2) 修訂語意（superseded＋不重複堆積）；(3) 前端可視化/可編輯**。全部 additive。

【推論】屬 C 陣營但「新表」：若日後需要「同一紀錄、多個模型、多版本的詮釋並存比較」（例如換模型後保留舊詮釋做 diff），再新增 `interpretations(id, item_id, schema_name, payload, model_name, status, created_at)` 一表即可——這是 C 的完整型態，可以等證據（S4 評測需求）再落。

---

## 5. 決策邊界：什麼交給 AI、什麼必須由軟體強制

【建議】以下是本研究對職責切分的立場。所有「交給 AI」的項目都必須經由**型別化 capability 端點**（沿用 `tools/analyze_item.py:122-127` 的 ALLOWED_ROUTES 模式），**不給任意 DB/SQL 或檔案系統存取**（SPEC-v1 §12 的立場仍然有效）。

### 執行期交給 AI 決定

| 決策 | 今天的狀態 | 建議 |
|---|---|---|
| 理解照片內容（這是什麼） | ✓ 已委派（prompt） | 維持，但允許描述型輸出 |
| 哪些屬性是相關的（該記什麼） | ✗ 被 8 欄白名單鎖住 | 放寬為「固定欄位 ∪ `attribute:<key>`」（S1），key 格式/長度/數量由軟體驗證 |
| 產生生活化標題/描述 | ✗ 未實作 | 允許 `description` 提案（映射至 attributes.description 或 notes）（S1） |
| 值正規化（日期、序號大小寫） | 部分（序號 normalized 由軟體做） | 內文語意層可委派；識別碼正規化維持軟體決定（可測試、安全） |
| 選擇工具/多步策略 | ✗ 不存在 | **暫不**引入（S5 條件式）；先用評測證明單呼叫不足 |
| 搜尋策略（同義詞/口語擴展） | ✗ 靜態 LIKE | 後期以「查詢改寫建議」形式委派（只提示，不自動改語義） |
| 關係/分組提案（同一物合併） | ✗ | 後期 propose-only（只產生建議，人決定）；先有需求證據 |

### 軟體必須穩定強制（不可委派）

1. **原始媒體不可破壞**：original 位元組、SHA-256、永不被流程覆寫（`inbox.py:293-307`）。
2. **推論與事實分離**：AI 產出一律 pending；接受成為事實後 AI 建議仍留檔（`repo.py:735-801`）。
3. **刪除/不可逆操作**：void/永久刪除只能由使用者明確行動；AI 不得具備任何刪除能力（`SPEC-v1.md:180-198`，本研究建議維持）。
4. **交易與稽核**：資料＋events 同交易；每次變更看得見 actor（`db.py:45-64`、`events.py:61-83`）。
5. **形狀驗證**：欄位/屬性 key 模式、值非空、confidence 範圍、photo 上限、大小限制——嚴格、可測試、**失敗要大聲**（維持現行 all-or-nothing 精神，見 S1 設計）。
6. **憑證與權限**：key 只在檔案、不回傳、loopback/信任區網模型（`settings.py`）。
7. **API 相容與契約版本化**：prompt/response schema 要有版本可指涉（供評測回歸）；新增欄位 additive。
8. **模組邊界**：adapter 只能讀與提議（`analyze_item.py` 已示範「結構性而非慣例性」的界線，繼續沿用）。

【建議】不要多代理編排（multi-agent orchestration）：目前沒有任何用例需要，成本/風險不匹配。以「單呼叫 + 型別化提案 + 人確認」為第一版；只在評測明確指出「單呼叫達不到」的失敗模式時，才演進為受控的工具循環。

---

## 6. 最小演進序列（含可觀察驗收）

以下每一步都是 additive、可獨立回退、以現有測試為回歸保護。**S1–S4 不需要任何 schema migration。**

### S1. 命名空間提案（attribute / description）
- 內容：`suggestions.field` 允許 `attribute:<key>`（key 模式如 `[a-z][a-z0-9_]{0,39}`）；`description` 提案映射到 `attributes.description`；`accept_suggestion` 對屬性提案做**單鍵合併**寫入 `items.attributes`（保留既有鍵），events 記錄 payload（含 model_name/source_photo_id；suggestion row 本身即來源紀錄）。prompt 改為「在固定欄位之外，可用 attribute:<key> 表達任何值得記住的屬性」，回應 schema 以 pattern 而非固定 enum（動態 key 不可 enum）。維持嚴格驗證：key 不在模式內、值超長/空、數量超限 → 整批失敗（或明確降級策略，見 Q1）。
- 驗收（可觀察）：
  - 以假 provider 回傳 `attribute:vendor=光華商場`、`attribute:amount=12900`、`attribute:purchase_date=2026-05-10`、`description=…` → accept 後 `GET /api/items/{id}` 的 `attributes` 含這些鍵；`GET /api/items?q=光華` 命中（現行 LIKE 涵蓋 attributes，不需改搜尋）。
  - `events` 有對應 `field.changed`（field=attributes 或帶 key 的 payload）；既有 928 測試全過；新增契約測試（合法/非法 key、合併衝突、數量上限）。

### S2. 修訂語意（supersede）＋可靠性修正
- 內容：重新分析時，把同一 item 的舊 `pending` 建議標為 `superseded`（使用既有狀態值）；`analyze` 回應與前端改為呈現「最新一輪」。同時修正 `capture.js` 吞掉 accept 失敗的問題（至少：失敗要顯示並阻止「全部成功」的假象）。
- 驗收：
  - 連續兩次 analyze（假 provider 不同值）→ 只有第二輪是 pending，第一輪變 superseded；已 accepted/rejected 的不受影響；主表始終未被 analyze 動過。
  - 前端：任一 accept 失敗時儲存流程顯示錯誤並可重試（可用元件測試或 API 行為測試 + 靜態檢查表述）。

### S3. 呈現與可溯性（前端）
- 內容：capture 審閱畫面渲染屬性提案（可編輯、可刪）；detail 渲染 attributes 區塊；AI 來源值可由 suggestion row/events 追溯（先以資料可追溯為驗收；UI 標籤 `✨ AI` vs `✍ 手動` 依來源決定，實作可自 accepted suggestion 比對）。
- 驗收：
  - 收據/寵物照片在 UI 完整呈現 AI 提出的屬性；使用者可修正；修正後 detail 顯示更新值；搜尋仍可命中。

### S4. 模型評測與回歸 harness
- 內容：固定評測案例集（可用合成照片 + 錄製的模型輸出，離線可跑）：商品標籤、序號 O/0 混淆、收據、寵物、無法辨識零件、多照片。`tools/evaluate_models.py` 以 `shop/ai_client.py` 同一份 prompt/解析跑 N 個模型（或重播錄製輸出），產出 JSON 報告（欄位準確率/召回、屬性 key 多樣性、失敗模式、延遲）。**離線 fixture 測試進 pytest；真實 provider 呼叫僅手動**。
- 驗收：報告可重現；換模型只改 `ai_config.local.json`；契約測試在 prompt/schema 變更時能偵測回歸。

### S5.（條件式，需 S4 證據）
- 工具循環（放大標籤、重讀序號）或 `interpretations` 版本表或 `item_relations` 關係表——只有在 S4/使用者證據指出必要時才做。**不在本階段預先實作。**

---

## 7. 遷移與回復（Migration & Rollback）

【已驗證】現有相容性約束：schema 變更必須向下相容、新欄位要有預設值（`docs/engineering/DECISIONS.md` D2/遷移策略；`ROADMAP.md`）。本研究所有步驟在此約束內。

- **S1（無 schema 變更）**：回退＝還原驗證寬容度；已寫入的 attributes 是惰性 JSON 資料（無害——搜尋仍正確、UI 忽略未知鍵即可），不會產生壞資料。失敗模式：AI 提議大量無意義 key → 由 key 數量/長度上限與評測（S4）控制，而非資料庫約束。
- **S2（狀態轉換）**：回退＝停止 supersede；superseded 列只是 status 值，可原路翻回 pending（若需要），零資料損失。
- **S3（前端）**：回退＝版本回滾；無資料面影響。
- **S4（外部工具＋測試）**：與產品資料解耦；可隨時停用。
- **未來若把熱門屬性升級為專欄（promotion）**：只允許 additive `ALTER TABLE ... DEFAULT`＋從 JSON 回填＋雙讀（先讀欄位、再讀 JSON）＋驗證後才切換來源；`schema_meta.version` 遞增；events 格式不變。任何一步失敗都可回到 JSON 單一來源（JSON 永遠保留）。
- **B/C 專屬風險（若未來真的走）**：資料搬家/FK 重指必須有 backup（`shopctl.py backup` 已是完整快照）＋`verify`（`db.py:151-171`）＋可回退 commit 的 checkpoint 流程（AGENT_GUIDE）。

---

## 8. 未解問題與需要的證據（Unresolved）

| # | 問題 | 需要的證據/實驗 |
|---|---|---|
| Q1 | 屬性值型別：純字串（LIKE 友善）vs 數字/日期型別 | 觀察真實收據/保固用例；若搜尋必須比較日期/金額，才引入型別化（影響搜尋與 UI） |
| Q2 | Key 詞彙漂移（vendor/seller/store 同義） | S4 報告統計 AI 提議 key 的分佈；先用建議詞彙（soft vocabulary），不急著硬枚舉 |
| Q3 | 低風險欄位是否可自動接受（降低摩擦） | 使用行為與錯誤率；目前建議維持全 pending（HITL 底線） |
| Q4 | superseded 足夠 vs 需要完整版本表（C の `interpretations`） | 是否需要跨模型並存比對；若只是「最新一版」，status 足夠 |
| Q5 | 搜尋何時需要索引（FTS5/JSON 索引） | 實測資料量與延遲（Phase 5）；目前 LIKE 決策有實測支撐 |
| Q6 | 同一物跨場次的合併/關聯需求強度 | 用量證據（同 sha256 回報率、同序號撞號率已可從既有資料統計）；先 propose-only |
| Q7 | 放寬欄位是否傷害弱模型輸出的穩定性 | S4 對多模型（含免費變體）的失敗率比較 |
| Q8 | 任意屬性在前端的資訊架構（排序、顯示、編輯） | 產品設計；建議先限制顯示數量（例如前 N 個）+ key 顯示名對照表 |
| Q9 | accept 部分失敗（`capture.js:489-494`）的正確行為 | 可靠性設計；建議 S2 一起修（失敗即全批失敗或明確列出未寫入項） |

---

## 附錄 A：本研究的核心結論一句話

【建議】**ItemTrace 不需要換資料模型；它需要把「AI 可以提議什麼」從 8 個固定欄位放寬為一個受驗證的命名空間，然後把「提案→修訂→接受→可追溯」這條已存在但未完成的鏈路補完。** 這是最小、可靠、且能長期承載 AI 行為演化的基礎；Record-first 重寫在現有證據下是無收益的高風險行動。

## 附錄 B：候選概念的正確對待方式

- **Record / Item / Fact / Interpretation 都是候選實作概念，不是必須的抽象。** 本研究的立場：
  - 今天：`items` 就是 Record；`items.attributes` + 固定欄位是 Fact 面；`suggestions` 是 Interpretation 面（pending→accepted/rejected/superseded）。
  - 何時才需要把 Interpretation 獨立成一級實體：當「同一個 Record 需要並存多個互相獨立、可比較的詮釋版本」成為真實需求（Q4）。
  - 何時才需要 Record 與 Item 分家：附錄 §4 的 B 觸發條件。

## 附錄 C：本文件沒有做的事（邊界聲明）

- 未修改任何產品程式碼、schema、資料、遷移、前端或測試。
- 未 push、未重寫任何既有 checkpoint 或規格文件。
- 未執行模型實測與瀏覽器測試（屬後續階段的證據工作，已在 §6/§8 定義）。
