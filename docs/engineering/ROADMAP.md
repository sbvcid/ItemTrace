# ItemTrace Engineering Roadmap

## 目標與範圍

**產品定位：** 「拍下來，AI 幫你記住，以後找得到。」

**核心流程：** Capture → AI Understand & Organize → Save → Retrieve

**工程目標：** 依據 `docs/product-v3/` 的產品規格，分階段實作完整、可驗證、數據安全的工程方案。

---

## 現有技術基線（Baseline）

### 已完成的核心資產
- **後端基礎完整**（`shop/` 模組）：
  - SQLite WAL 模式，STRICT 約束，SCHEMA_VERSION="2"
  - 六張核心表：`items`、`photos`、`observations`、`suggestions`、`identifiers`、`events`
  - 推論與事實分離設計（suggestions 與主表隔離）
  - Event sourcing 與單欄位復原機制
  - 原始照片不可覆寫原則（`files/original/` 目錄結構）

- **API 架構完善**（`shop/api.py`）：
  - FastAPI + uvicorn，依賴最小化（只有 HTTP 層）
  - 所有 CRUD 端點已實作
  - 照片存取與搜尋端點可用
  - SPA 路由回退掛載支援客戶端 History API

- **AI 整合框架**（`shop/ai_client.py`）：
  - OpenAI 相容 API 介面
  - Vision 模型支援（Google Gemini / OpenRouter / Custom）
  - 建議生成與部分序號正規化邏輯
  - 由 `tools/ai_config.local.json` 配置

- **前端骨架完成**（`web/` 目錄）：
  - 零建置 ESM 模組化架構
  - 輕量路由器、狀態管理、API 封裝
  - 手機底部導覽、桌面頂部搜尋框
  - 繁中與英文雙語支援（352 keys × 2 languages）
  - Capture / Home / Record Detail / Settings 四大頁面

- **測試基線確立**：
  - 共 928 個測試（全 pytest 框架；Phase 1B-A 後）
  - 36 個測試檔案，涵蓋 API、DB、前端、列印、i18n
  - **現況：全部通過** ✓
  - 包含 V3 核心流程驗收測試（test_v3_core_slice.py）

### 已驗證但未 commit 的工作
- **V3 前端核心實作**（`web/` 目錄，untracked）：
  - Capture 全螢幕連拍與托盤流程
  - AI 整理結果展示與主管驗收模式
  - 紀錄列表與詳細檢視
  - 搜尋、i18n、響應式排版

- **V3 核心 API 支援**（`shop/api.py` 已修改）：
  - SPA 靜態掛載與路由回退
  - 照片檔案路徑相容性（`/files/ITM-xxxx/...` 與 `/files/files/...`）
  - 圖片快取控制標頭

- **V3 驗收測試**（`tests/test_v3_core_slice.py`，untracked）：
  - Scenario A：第一次使用，拍照 → AI 整理 → 存下來 → 找得到
  - Scenario B：連續拍攝多件物品，無需重複設定
  - Scenario C：生活隨拍照片，彈性記錄無規格強制

---

## 工程階段規劃

### Phase 0：基線盤點與工程文件建立（COMPLETED）

**目標**：確認專案整體狀態，建立工程控制系統，為正式施工建立清晰基線。

**完成內容**：
- ✓ 全面 audit：Git 狀態、未提交工作、前後端能力、測試基線
- ✓ 建立三份工程文件：ROADMAP / STATUS / DECISIONS
- ✓ 建立 AGENT_GUIDE 與 AGENTS 入口
- ✓ 921 個測試基線確認無失敗
- ✓ 工程決策記錄完整

**下一階段**：Phase 1A（見下節）

---

### Phase 1A：V3 前端正式整合（COMPLETED 2026-10-09，commit `2879904`）

**目標**：將驗證完成的 V3 前端與核心測試納入版本控制，建立可回退的 Git checkpoint。

**工作範圍**：
1. **V3 Web 靜態檔案正式化**
   - 將 `web/` 完整目錄納入版本控制（11 個檔案）
   - SPA 路由、i18n、design tokens、響應式排版完整

2. **V3 驗收測試納入**
   - `tests/test_v3_core_slice.py` 正式化（5 scenarios）
   - Capture → AI → Save → Retrieve 核心流程驗收

3. **API SPA 支援完善**
   - `shop/api.py` 修改：SPA 靜態路由回退 + 照片路徑相容性

**API 狀態**：
- ✓ `PATCH /api/items/{id}` 已實作（欄位編輯）
- ✓ `/api/items?q=...` 已實作（搜尋）
- ✓ 列表預設排序 `created_at DESC`（Phase 1B-A 實作；不需 sort 參數）

**資料庫狀態**：
- ✓ 無需 migration（所有必要欄位已存在）

**驗收標準**：
- [ ] `pytest tests/test_v3_core_slice.py -v` 5/5 通過
- [ ] `pytest -q` 全 921 通過（無回歸）
- [ ] 手機實機：Capture → 拍照 → 預覽 → 存下來 ✓

**時間估計**：1 天（整合 + 驗證）

**Git Checkpoint**：
```
Commit: "feat: phase-1a integrate V3 SPA frontend and core tests"
  - Add web/ (11 files: index.html, app.js, app.css, core/*, views/*, i18n/*)
  - Add tests/test_v3_core_slice.py
  - Update shop/api.py (+50 lines for SPA routing)
```

---

### Phase 1B：首頁流程改進與編輯完善（1B-A 首頁基本流程 COMPLETED 2026-10-09）

**依賴**：Phase 1A

**目標**：實現首頁最新紀錄優先、大卡片展示、保存回首頁、按需編輯的完整首頁體驗。

**工作範圍**：
1. **首頁紀錄流改進**
   - 新紀錄置頂（created_at DESC 排序）
   - 最新紀錄卡片較大展示
   - 保存成功後自動回首頁並高亮

2. **紀錄編輯完善**
   - 按需編輯（不自動觸發 AI 重新分析）
   - 「生活備忘」欄位（購買日期、保固、存放位置）利用現有 `items.attributes`
   - 使用者備註與 AI 建議的來源清晰標示

3. **搜尋優化**
   - 序號旁增設「對照照片」按鈕
   - 搜尋結果精確度（品名、型號、半截序號）

**API 需求**：
- ✓ `PATCH /api/items/{id}` 已實作
- ✓ `items.attributes` 已存在
- ✓ `GET /api/items` 預設 `created_at DESC`（Phase 1B-A；不需 sort 參數）

**驗收標準**：
- 首頁紀錄按倒序排列
- 保存 3 件新物品，最新的置頂
- 點擊編輯，修改生活備忘，無衝突

**時間估計**：2 天

---

### Phase 2：AI Contract 2.0 與視覺紀錄基礎（2A、2B、2C-A、2C-B、2C-C、2C-D COMPLETED）

**依賴**：Phase 1A

**目標**：擴充 AI 整合契約，支援通用視覺紀錄、自然語言描述、模型評測，為後續 AI 功能奠基。

**已完成（Phase 2A，2026-10-09）**：AI 建議生命週期與部分失敗語意 —— 成功的新分析於同一交易內 supersede 舊 pending；失敗分析保留既有 pending；accept 原子化、重試不重複；capture 部分失敗誠實回報並可原地重試。零 schema migration；12 個新測試，全 940 通過。細則見 `STATUS.md`。

**已完成（Phase 2B，2026-10-09）**：證據累積與情境式重新理解 —— 既有紀錄可加入新照片（不建新紀錄）；分析帶入既有詮釋與新證據；`attribute:<key>` 契約（pattern 驗證、單鍵合併、不覆蓋使用者資料）；失敗保留照片與 pending 並可重試；accepted 詞彙保留於搜尋；併發寫入改 `BEGIN IMMEDIATE`。零 schema migration；15 個新測試，全 955 通過。細則見 `STATUS.md`。

**已完成（Phase 2C-A，2026-10-10）**：AI 評測與自主性政策 —— `tools/evaluate_models.py`（離線重播契約守門＋`--live` 受控模式）＋合成 fixture；實際評測 `gemini-3.5-flash-lite`（8 次呼叫、free tier、僅合成圖）：7/7 契約合法、收據情境正確更新、不確定時不發明；發現「矛盾證據被靜默合併」（L4）與「最新-8 丟失最早身分照」（L6a）；建議證據選擇「最早 2＋最新 6」與 T0/T1 自主性政策（不依賴模型信心）。報告：`AI-EVALUATION-REPORT.md`；+7 測試，全 962 通過。

**已完成（Phase 2C-B，2026-10-10）**：可回復的 AI 自動更新與證據感知自主性 —— 證據選擇「最早 2＋最新 6」；`commit_analysis(auto=1)` 依決定性政策自動套用（描述屬性／空身分／auto 來源修訂），使用者編輯、確認、清空、復原過的欄位永不自動覆蓋；購買資訊僅在「同張照片提供身分」時自動、否則升級衝突確認（L4 錄製回放為回歸測試）；`POST /api/suggestions/{id}/undo` 還原前值並鎖定欄位；詳情頁「已自動更新＋復原」banner 與來源照片標示。零 schema migration；+21 測試，全 983 通過；瀏覽器 E2E 驗證。細則見 `STATUS.md`。

**已完成（Phase 2C-C，2026-10-10）**：自主性 Live 驗證 —— 對 `gemini-3.5-flash-lite`（free tier、僅合成 fixture、7 次成功＋1 次 4xx）：自動修訂可行（BOSE→SONY）、使用者修正受保護、衝突規則在三種內容上泛化、9 張選擇在真實管線修復 L6a、失敗/重試乾淨；**抓到「過期 undo 可覆寫後續編輯」缺陷**、`attribute:description` 0/9 出現。報告：`AI-AUTONOMY-VALIDATION.md`（含 2C-D 五條驗收條件：undo 防護、描述 prompt、跨照片身分聲明、修訂前後值可見、全測試＋E2E）。

**已完成（Phase 2C-D，2026-10-10）**：撤銷安全、描述性理解與衝突處理 —— 過期 undo 防護（現值＋中間事件檢查，409 零副作用；批次逐欄位、UI 逐項說明）；banner 顯示修訂前後值；描述與跨照片身分 prompt 上線並以 Live 回評（C1 描述 ✓、C6 雙身分 ✓、P/S/F ✓；**R 型有上下文時模型仍可能擇一 → 限制誠實記錄**）；新增可重複 Live 驗證入口 `tools/validate_autonomy_live.py`。零 schema migration；+11 測試，全 994 通過。細則見 `STATUS.md`／`AI-AUTONOMY-VALIDATION.md`。

**工作範圍**：
1. **AI Contract 升級**
   - 支援通用「視覺紀錄」（非僅限商品規格）
   - 自然語言描述補充（「帶有刮痕」「外觀略舊」等）
   - 置信度分數與來源照片索引
   - 多模型適配（Gemini, OpenRouter, Custom）

2. **AI 資料與人工備註分離**
   - AI 建議進 `suggestions` 表（待確認）
   - 使用者自由編輯的備註進 `items.attributes.notes`
   - 來源清晰標示（✨ AI vs 📝 人工）

3. **基礎模型評測**
   - 建立 evaluation harness（準確度、速度、成本對比）
   - 測試場景：商品規格、序號識別、狀況描述

**資料庫**：
- ✓ `suggestions` 表已存在
- ✓ `items.attributes` 已存在
- 無需 migration

**驗收標準**：
- AI 能生成通用視覺紀錄（非僅商品）
- 人工備註與 AI 建議獨立維護
- 基礎評測框架建立

**時間估計**：3~4 天

---

### Phase 3：垃圾桶與資料生命週期

**依賴**：Phase 1A（核心流程就緒）

**目標**：實現安全的資料刪除流程，支援 30 天軟刪除、還原、永久刪除。

**工作範圍**：
1. **紀錄狀態擴展**
   - 新增 `items.deleted_at` 欄位（軟刪除時間戳）

2. **30 天保留與還原**
   - 刪除 → `deleted_at = NOW()`
   - 首頁隱藏，垃圾桶可見
   - 30 天內一鍵還原

3. **永久刪除驗證**
   - 驗證：資料庫紀錄 + 照片檔案 + 搜尋索引
   - 刪除順序：索引 → 檔案 → DB
   - 交易回滾機制

**資料庫遷移**：
```sql
ALTER TABLE items ADD COLUMN deleted_at DATETIME NULL;
```
向下相容：既有資料 `deleted_at = NULL`

**驗收標準**：
- 刪除紀錄 → 垃圾桶隱藏
- 30 天後永久刪除
- 驗證：檔案與 DB 同步清理

**時間估計**：3~4 天

---

### Phase 4：AI 自動分類與正規化

**依賴**：Phase 2（AI Contract 基礎）

**目標**：建立分類系統，支援 AI 自動建議、使用者維護、分類正規化。

**工作範圍**：
1. **分類體系**
   - 預定義分類清單
   - 支援自訂分類
   - 同義詞與別名對應

2. **AI 自動分類**
   - Vision API 擴充：返回分類推薦
   - 置信度分數

3. **分類正規化**
   - 同義詞轉換（「電腦零件」= 「PC 配件」）
   - 分類索引與計數

**資料庫遷移**：
```sql
CREATE TABLE categories (id TEXT PRIMARY KEY, name TEXT NOT NULL);
ALTER TABLE items ADD COLUMN category_id TEXT REFERENCES categories(id);
```

**驗收標準**：
- AI 分類推薦準確度 > 85%
- 使用者可新增自訂分類
- 分類篩選 < 50ms

**時間估計**：3~5 天

---

### Phase 5：高效能搜尋與繁簡互搜

**依賴**：Phase 1B（首頁搜尋已就位）

**目標**：實現 FTS5 全文索引、部分字串搜尋、繁簡互搜、詞彙別名、索引維護。

**工作範圍**：
1. **FTS5 全文索引**
   - 建立虛擬表 `items_fts5`
   - 索引：品名、品牌、型號、分類、備忘、識別碼

2. **部分字串搜尋**
   - Prefix query（「4070」→「RTX4070」）
   - 序號末碼搜尋

3. **繁簡互搜**
   - 繁簡對照表或開源庫（OpenCC）
   - 搜尋時同時查詢原詞 + 轉換後異體

4. **索引維護**
   - 增量更新（觸發器）
   - 完整重建端點
   - 最佳化與清理

**驗收標準**：
- 搜尋 < 50ms（1000+ 紀錄）
- 部分字串匹配準確度 > 95%
- 繁體「電腦」找到簡體「电脑」

**時間估計**：4~5 天

---

### Phase 6：進階能力與輸出

**依賴**：Phase 1A（基礎完整）

**目標**：實現列印、比對、匯出等進階功能。

**工作範圍**：
1. **標籤列印 QR Code 綁定**（多數已實作）
   - 紀錄頁 `⋯` 選單 → 列印
   - 預覽 + 印表機選擇 + 執行

2. **外觀前後比對器**（已實作基礎）
   - 雙視窗同步縮放平移

3. **紀錄匯出封存包**（已實作基礎）
   - ZIP 打包：item.json + photos + manifest.json

**驗收標準**：
- 實體標籤印出，QR 可掃
- 比對模式操作流暢
- 匯出 ZIP 完整性無誤

**時間估計**：1~2 天（多數已實作）

---

### Phase 7：同一物品匹配與批次整理

**依賴**：Phase 4（分類正規化完成）、Phase 5（搜尋高效）

**目標**：支援相同物品的重複紀錄識別、相機記憶卡批次匯入、智慧分組。

**工作範圍**：
1. **同一物品識別**
   - 序號與照片相似度判斷（embedding 或視覺哈希）
   - 可選：自動合併或提示使用者

2. **批次照片匯入**
   - `/unsorted` 頁面：拖放相機記憶卡照片
   - 按 EXIF 時間智慧分組
   - 確認分組後一鍵建檔

**驗證標準**：
- 同一物品重複率識別準確度 > 90%
- 批次匯入 30 張照片 < 2 分鐘完成

**時間估計**：5~8 天

---

### Phase 8：Windows / Microsoft Store 發行準備

**依賴**：所有核心功能（Phase 1–7）

**目標**：整理應用程式資產，準備 Windows Store 發行。

**工作範圍**：
1. **應用程式中繼資料**
   - 版本號管理
   - CHANGELOG
   - app.ico / app.png

2. **Windows 打包**
   - MSIX / EXE 建置與簽名
   - 使用者資料位置標準化（%APPDATA%）
   - 安裝 / 更新機制

3. **隱私政策與授權**

**時間估計**：3~5 天

---

## 工作依賴關係

```
Phase 0 (Baseline)  ✓ COMPLETED
    ↓
Phase 1A (V3 Frontend Integration) ← 核心基礎
    ├→ Phase 1B (Homepage Flow)
    ├→ Phase 2 (AI Contract 2.0)
    │   └→ Phase 4 (Classification)
    │       └→ Phase 7 (Batch & Dedup)
    ├→ Phase 3 (Trash & Lifecycle)
    ├→ Phase 5 (Search) ← 獨立並行
    ├→ Phase 6 (Advanced Output)
    └→ Phase 8 (Windows Release)
```

**關鍵路徑**：Phase 1A → 1B / 2 → 4 → 7 → 8

**可並行**：Phase 3 / 5 / 6（不阻塞主路徑）

---

## 修改歷史

- **2026-10-09**：初始版本（Phase 0 audit 基礎）
- **2026-10-09（修正）**：重新排序，明確依賴，Phase 0 標記完成

**目標**：將未 commit 的 V3 前端代碼正式集成，實現 「拍照 → AI 理解 → 存下來 → 找得到」 的完整核心流程。

**工作範圍**：
1. **V3 Web 靜態檔案正式化**
   - 將 `web/` untracked 檔案正式納入版本控制
   - 確保 SPA 路由、i18n、CSS design tokens 完整
   - 手機單手快門與桌面全域搜尋可用

2. **首頁改造與新紀錄置頂**
   - 按建立時間倒序排列紀錄（最新優先）
   - 首頁卡片展示最新 N 筆紀錄的大圖
   - 保存成功後自動回首頁並高亮新紀錄
   - 搜尋結果精確度優化（品名、型號、半截序號、分類）

3. **AI 整理結果改進**
   - 序號旁增設「對照照片」放大鏡按鈕（快速驗證標籤特寫）
   - AI 置信度分數顯示與 UI 反饋
   - 整理結果呈現優化：品牌、型號、分類欄位清晰區分

4. **紀錄編輯與使用者備註分離**
   - 紀錄詳細頁支援按需編輯（不自動觸發 AI 重新分析）
   - 「生活備忘」欄位（購買日期、保固、存放位置）與 AI 資料欄位獨立維護
   - 使用者備註與 AI 建議的來源清晰標示

**API 需求**：
- `PATCH /api/items/{id}` —— 欄位局部編輯（已實作 ✓）
- `PATCH /api/items/{id}/attributes` —— 生活備忘單獨編輯（新增）
- ✓ `GET /api/items` 預設 `created_at DESC`，搜尋沿用同一順序（Phase 1B-A 實作）

**資料庫狀態**：
- ✓ `items.attributes` JSON 欄位已存在（schema.sql line 13）
- 既有欄位默認值：`'{}'` 空物件
- 無需 migration，直接利用現有欄位

**驗收標準**：
- 新 untracked 檔案已 commit
- 首頁最新紀錄置頂並高亮
- 搜尋響應時間 < 100ms（百筆紀錄內）
- 紀錄編輯與 AI 資料獨立維護，無衝突
- 全 921 測試仍通過，新增 Phase 1 驗收測試
- 手機實機測試：拍照 → 理解 → 編輯 → 保存 → 搜尋 → 完整閉環

**時間估計**：2~3 天（前端 + API 改進 + 測試）

---

### Phase 2：垃圾桶與永久刪除（Data Lifecycle）

**目標**：實現安全的資料生命週期管理，支援 30 天軟刪除與永久刪除。

**工作範圍**：
1. **紀錄狀態擴展**
   - 新增 `items.deleted_at` 欄位（軟刪除時間戳，NULL 表示未刪除）
   - 已作廢狀態 (`status='void'`) 與軟刪除 (`deleted_at IS NOT NULL`) 區分
   - 軟刪除紀錄隱藏於首頁，但支援「垃圾桶」頁面查看

2. **30 天保留期與還原**
   - 使用者刪除 → `deleted_at = NOW()`
   - 系統定期掃描：刪除 > 30 天的紀錄標記永久刪除候選
   - UI 提供「還原」按鈕（30 天內一鍵恢復）
   - 系統清理 job（每天凌晨）執行永久刪除檢查

3. **永久刪除驗證**
   - 永久刪除前驗證：資料庫紀錄 + 照片檔案 + 搜尋索引
   - 刪除順序：索引 → 照片檔案 → 資料庫紀錄
   - 交易回滾機制：若任意步驟失敗則全部回滾
   - 清理日誌記錄（含 item_id、檔案數、時間戳）

4. **搜尋結果排除已刪除紀錄**
   - 所有搜尋查詢自動過濾 `deleted_at IS NULL`
   - 垃圾桶專屬頁面查詢 `deleted_at IS NOT NULL` 並按刪除時間倒序

**API 新增**：
- `PATCH /api/items/{id}/delete` —— 軟刪除（設定 deleted_at）
- `PATCH /api/items/{id}/restore` —— 還原（清除 deleted_at）
- `DELETE /api/items/{id}/permanently` —— 永久刪除（需二次確認）
- `GET /api/items/trash` —— 垃圾桶列表與統計

**資料庫遷移**：
- 新增 `items.deleted_at` DATETIME NULL 欄位
- 現有資料 `deleted_at = NULL`（無需清理）

**驗收標準**：
- 刪除 → 垃圾桶隱藏 → 30 天內可還原 → 30 天後永久刪除
- 垃圾桶頁面展示待清理紀錄與剩餘日期
- 永久刪除驗證：照片檔案確實被移除，資料庫無紀錄
- 搜尋不包含已刪除紀錄，垃圾桶專頁可查看
- 全測試通過（現有測試不受影響）

**時間估計**：3~4 天（API + UI + cleanup job + 驗證）

---

### Phase 3：AI 自動分類與分類正規化

**目標**：建立分類系統，支援 AI 自動分類與使用者手動維護。

**工作範圍**：
1. **分類體系定義**
   - 預定義分類清單（例：電腦零件、攝影器材、工具、生活用品 等）
   - 支援自訂分類（使用者新增）
   - `items.category` 欄位與分類表關聯

2. **AI 自動分類**
   - 在 Vision API 呼叫時增加分類推薦
   - 前端展示 AI 建議分類（可能性列表與置信度）
   - 使用者確認或修改

3. **分類索引與搜尋**
   - 分類篩選快速（預加載分類清單與計數）
   - 分類 + 全文搜尋組合查詢

**資料庫改動**：
- 新增 `categories` 表（id, name, created_at）
- `items.category_id` 外鍵關聯
- 現有 `items.category` 欄位遷移至新表

**API 新增**：
- `GET /api/categories` —— 分類清單與計數
- `POST /api/categories` —— 新增自訂分類
- `PATCH /api/items/{id}/category` —— 修改分類

**驗收標準**：
- AI 自動分類推薦準確度 > 85%
- 分類篩選響應 < 50ms
- 使用者可新增 / 修改 / 刪除分類
- 全測試通過

**時間估計**：3~5 天

---

### Phase 4：SQLite 全文搜尋與繁簡互搜

**目標**：實現高效、支援中文部分字串搜尋與繁簡體互搜的搜尋能力。

**工作範圍**：
1. **全文搜尋索引建立**
   - 建立 FTS5 虛擬表 `items_fts`（品名、品牌、型號、備註、分類、識別碼）
   - 索引管理：新增 / 編輯 / 刪除紀錄時自動更新

2. **部分字串搜尋**
   - FTS5 prefix query 支援（例：「4070」匹配 「RTX4070」「B650E-F」 等型號）
   - 序號末碼搜尋（例：「1234」匹配 「SN-xxxx-1234」）

3. **繁簡互搜支援**
   - 建立繁簡對照表（或使用開源繁簡轉換庫）
   - 搜尋時同時查詢原詞 + 轉換後的異體
   - 例：搜「電腦」也找到「电脑」之類紀錄

4. **索引增量更新與重建**
   - `POST /api/admin/search-index/rebuild` —— 完整重建（維護用）
   - `POST /api/admin/search-index/optimize` —— 最佳化（定期執行）

**資料庫改動**：
- 建立 FTS5 虛擬表 `items_fts5(品名, 品牌, 型號, ...)`
- 建立觸發器自動維護索引

**API 改進**：
- `GET /api/items?q=...` —— 改用 FTS5 查詢
- 新增搜尋響應欄位：`matched_fields` 標示匹配位置

**驗收標準**：
- 搜尋響應時間 < 50ms（1000+ 紀錄）
- 部分字串搜尋準確度 > 95%
- 繁簡互搜支援可驗證
- 索引完整性驗證無誤

**時間估計**：4~5 天

---

### Phase 5：進階能力與輸出交付

**目標**：實現列印、比對、匯出等進階功能。

**工作範圍**：
1. **標籤列印 QR Code 綁定**（已有基礎，需 UI 整合）
   - 紀錄頁 `⋯` 選單 → 「列印標籤」
   - 預覽 + 印表機選擇 + 執行
   - QR Code 指向 `/i/{item_id}`

2. **外觀比對器（Compare）** —— 雙視窗並排
   - 選擇兩個快照（建檔時 vs 收回時）
   - 同步縮放 + 平移
   - 標註差異點

3. **紀錄匯出封存包**
   - `/api/items/{id}/evidence/export` —— 打包 item.json / photos / manifest.json
   - 選用：生成 report.pdf（人類可讀報告）
   - 下載 ZIP 或單檔存取

**驗收標準**：
- 列印輸出實體貼紙，QR 可掃
- 比對模式操作流暢
- 匯出 ZIP 完整性驗證無誤

**時間估計**：2~3 天（多數已實作）

---

### Phase 6：跨次物品匹配與大量照片整理（Future）

**目標**：支援相同物品的多次紀錄識別、批次匯入與整理。

**工作範圍**：
1. **同一物品識別**（重複紀錄辨識）
   - 序號與照片相似度判斷（使用 embedding 或視覺哈希）
   - 可選：自動合併或提示使用者

2. **批次照片匯入**
   - `/unsorted` 頁面：拖放相機記憶卡照片
   - 按 EXIF 時間智慧分組
   - 確認分組後一鍵建檔

**時間估計**：5~8 天（需 embedding 模型或相似度演算法）

---

### Phase 7：Windows / Microsoft Store 發行準備

**目標**：整理工程資產，為封裝與應用商店發行做準備。

**工作範圍**：
1. **應用程式中繼資料**
   - app.ico / app.png
   - 版本號管理
   - CHANGELOG

2. **Windows 打包**
   - MSIX / EXE 建置與簽名
   - 使用者資料位置標準化
   - 安裝 / 更新機制

3. **隱私政策與授權**

**時間估計**：3~5 天（主要是配置與測試）

---

## 工作依賴關係

```
Phase 0 (Baseline)
    ↓
Phase 1 (V3 Frontend Integration & Homepage)  ← 核心
    ↓
Phase 2 (Trash & Deletion)  ← 資料安全
    ↓
Phase 3 (Auto Classification)
    ↓
Phase 4 (Full-text Search & CJK)  ← 高效查詢
    ├→ Phase 5 (Advanced: Print / Compare / Export)
    └→ Phase 6 (Batch & Deduplication)
        ↓
Phase 7 (Windows Release)
```

---

## 資料庫 Migration 策略

### Phase 1
- 新增 `items.attributes` JSON（相容舊資料，無破壞性）

### Phase 2
- 新增 `items.deleted_at` DATETIME NULL（向下相容）

### Phase 3
- 建立 `categories` 表 + 遷移 `items.category` 到外鍵
- 現有字符欄位值遷移至新表，無資料損失

### Phase 4
- 建立 FTS5 虛擬表（增量更新，無破壞性）

---

## 不在本次實作範圍

- 多人雲端同步 / 帳號系統
- PDF 生成與高級報表設計
- 機器學習模型訓練與微調
- 移動應用（Android / iOS）—— 純 Web 優先
- 自動備份到雲端儲存

---

## 施工原則

1. **最小變更範圍**：每個 Phase 只解決一個主要問題
2. **測試優先**：新功能需補充測試，不刪除既有測試
3. **資料安全**：涉及刪除 / 修改時必須驗證備份與回滾機制
4. **向下相容**：資料庫遷移不破壞舊資料
5. **單個 Commit**：一個 Phase = 一個邏輯完整的 commit
6. **完整回歸**：每個 Phase 完成後運行全測試

---

## 已知問題與開放問題

| 項目 | 狀態 | 備註 |
|---|---|---|
| V3 前端完成度 | 95% | web/ 已實作，待正式 commit |
| 首頁排序邏輯 | Open | 倒序 vs 分類導航優先級 |
| 分類體系設計 | Proposed | 預定義分類清單待確定 |
| 繁簡對照表來源 | Open | 自建 vs 開源庫 |
| Windows Store 要求 | Open | 需確認簽名 / MSIX 配置 |

---

## 修改歷史

- **2026-10-09**：初始版本建立，基於 Phase 0 audit 結果
- **2026-10-09（Phase 1B-A）**：Phase 1A 標記 COMPLETED；列表排序方案確定為預設 `created_at DESC`（不走 sort 參數）；測試基線更新為 928
- **2026-10-09（Phase 2A）**：建議生命週期與部分失敗語意完成（supersede／失敗保留／重試不重複／誠實回報）；零 schema migration；測試基線更新為 940；下一階段 = Phase 2B 提案命名空間（study S1，待決策）
- **2026-10-09（Phase 2B）**：證據累積與情境式重新理解完成（加照片到既有紀錄、上下文分析、`attribute:<key>` 契約、失敗保留＋重試、accepted 詞彙搜尋保留、`BEGIN IMMEDIATE` 併發修正）；零 schema migration；測試基線更新為 955；下一階段 = Phase 2C 模型評測 harness（study S4）
- **2026-10-10（Phase 2C-A）**：評測與政策完成（harness＋合成 fixture、7 情境實測 `gemini-3.5-flash-lite`、證據選擇建議「最早 2＋最新 6」、T0/T1 自主性政策、2C-B 驗收條件）；零產品程式碼變更；測試基線更新為 962；下一階段 = Phase 2C-B 自動套用實作
- **2026-10-10（Phase 2C-B）**：可回復的自動套用完成（選擇策略、決定性政策、使用者保護、衝突升級、undo、banner/來源標示）；零 schema migration；測試基線更新為 983；Phase 2 核心完成；下一階段 = Phase 3 垃圾桶與資料生命週期（收尾選項：description prompt 調校、屬性來源標籤）
- **2026-10-10（Phase 2C-C）**：自主性 Live 驗證完成（7 次成功＋1 次 4xx、僅合成圖）：修訂/保護/衝突/選擇/失敗重試通過；抓到過期 undo 缺陷與 description 缺口；測試基線不變（未改程式碼）；下一階段 = Phase 2C-D 收斂五條驗收，接 Phase 3
- **2026-10-10（Phase 2C-D）**：撤銷安全、描述與衝突處理完成（409 防護、banner 前後值、描述/身分 prompt、Live 回評 C1/C6 通過、R 型限制記錄、可重複 Live 入口）；零 schema migration；測試基線更新為 994；下一階段 = Phase 3 垃圾桶與資料生命週期

