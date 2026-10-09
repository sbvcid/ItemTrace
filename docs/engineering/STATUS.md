# ItemTrace Engineering Status

最後更新：2026-10-09 13:50  
當前 HEAD：`3be4ac5` ("docs: add ItemTrace V3 product proposal")  
遠端狀態：本地與 origin/main 完全同步（0 ahead, 0 behind）  
測試驗證：`pytest -q` 完全通過，全 921 測試無失敗

---

## 當前階段

**Phase 0：基線盤點與 V3 前端整合評估** ← **CURRENT**

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 36 | conftest + 35 test_*.py |
| 總測試數 | 921 | 全 pytest 計數 |
| 通過 | 921 ✓ | 100% pass rate |
| 失敗 | 0 | 零失敗 |
| 跳過 | 0 | 無跳過 |
| 覆蓋率 | 未測 | 建議後續補充 |

**測試框架**：pytest（可選 pytest-cov 補充覆蓋率）

**主要測試分類**：
- API 端點：test_api.py (82), test_phase8a_api.py (35), test_settings_api.py (43) 等
- 資料庫 & Repo：test_repo_*.py (13-21 each), test_db_transactions.py (7)
- AI & 分析：test_ai_*.py (15-78), test_analyze_item.py (78)
- 前端與 UI：test_capture_ui.py (6), test_inbox_ui.py (35)
- 列印：test_print.py (31), test_print_settings_api.py (20)
- i18n：tests/test_i18n.py（數量未計）
- **V3 核心驗收**：test_v3_core_slice.py (5) —— Capture → AI → Save → Retrieve

**最近運行**：2026-10-09，全通過

---

## 已完成功能

## 已完成功能狀態分類

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 921 個 pytest 全通過，V3 core slice test 驗收 |
| **Committed** | 變更已進入版本控制 | main branch 上的所有程式碼 |
| **Pushed** | 變更已推送到遠端 | origin/main 的最新狀態 |

### 核心產品體驗
- ✓ 手機隨手拍照 (Capture) — **Implemented, Tested, Committed, Pushed**
- ✓ AI 自動整理與建議 — **Implemented, Tested, Committed, Pushed**
- ✓ 超低摩擦確認（一鍵存起來） — **Implemented, Tested, Committed, Pushed**
- ✓ 紀錄詳細檢視與大圖展示 — **Implemented, Tested, Committed, Pushed**
- ✓ 即時文字 & 序號搜尋 — **Implemented, Tested, Committed, Pushed**
- ✓ 隨手追加照片與筆記 — **Implemented, Tested, Committed, Pushed**
- ⚙ V3 前端（Capture/Home/Detail/Settings 完整實作） — **Implemented, Tested, Not Committed**

### 後端基礎
- ✓ SQLite + WAL + STRICT 約束 — **Implemented, Tested, Committed, Pushed**
- ✓ Items/Photos/Observations/Suggestions/Identifiers/Events 六表 — **Implemented, Tested, Committed, Pushed**
- ✓ 推論與事實分離（Suggestions 隔離） — **Implemented, Tested, Committed, Pushed**
- ✓ Event sourcing 與單欄位復原 — **Implemented, Tested, Committed, Pushed**
- ✓ FastAPI HTTP API 與文件 — **Implemented, Tested, Committed, Pushed**
- ✓ 照片原始檔案保存（files/original/） — **Implemented, Tested, Committed, Pushed**
- ✓ 搜尋與全文過濾 — **Implemented, Tested, Committed, Pushed**
- ✓ items.attributes JSON 欄位 — **Implemented, Not Tested, Committed, Pushed** (schema exists, API usage untested)

### 前端基礎
- ✓ 零建置 ESM 架構 — **Implemented, Tested, Not Committed** (web/ 已實作但未 commit)
- ✓ 輕量路由 + 狀態管理 — **Implemented, Tested, Not Committed**
- ✓ 繁中 + 英文 i18n（352 keys × 2） — **Implemented, Tested, Not Committed**
- ✓ 手機 + 桌面響應式排版 — **Implemented, Tested, Not Committed**
- ✓ 照片展示與 lazy loading — **Implemented, Tested, Not Committed**

### 進階能力（部分）
- ✓ 標籤列印 + QR Code（Chromium + GDI） — **Implemented, Tested, Committed, Pushed**
- ✓ 證據包匯出（manifest.json + photos） — **Implemented, Tested, Committed, Pushed**
- ✓ 列印設定管理 — **Implemented, Tested, Committed, Pushed**
- ✓ 本機備份 & 完整性驗證 — **Implemented, Tested, Committed, Pushed**

---

## 未完成工作

### 立即待做（Phase 1）
1. **V3 前端正式整合**
   - `web/` untracked 檔案正式 commit
   - 確保 SPA routing、design tokens、i18n 完整

2. **首頁改造**
   - 新紀錄置頂（created_at DESC）
   - 保存後自動回首頁 + 高亮
   - 最新紀錄大卡片展示

3. **紀錄編輯完善**
   - 按需編輯（不自動觸發 AI 重新分析）
   - 生活備忘欄位（購買日期、保固、位置）
   - AI 資料與使用者備註分離

### 短期（Phase 2–3）
- 垃圾桶 & 30 天保留 + 永久刪除
- AI 自動分類與分類體系
- 搜尋性能優化

### 中期（Phase 4–6）
- SQLite FTS5 全文搜尋
- 繁簡互搜支援
- 外觀比對器（Compare）
- 相機批次匯入 & 重複識別

### 長期（Phase 7）
- Windows / Microsoft Store 發行準備

---

## 已知問題

| 問題 | 嚴重性 | 狀態 | 備註 |
|---|---|---|---|
| Web 目錄尚未 commit | 中 | 待處理 | Phase 1 的第一項工作 |
| 首頁排序邏輯待決定 | 中 | 開放問題 | 倒序 vs 分類導航優先級 |
| 照片路徑相容性驗證 | 低 | 已實作，待測 | `/files/ITM-xxxx/` vs `/files/files/` 相容 |
| i18n 覆蓋率 | 低 | 完整 | 前端全文字已翻譯 |

---

## 未提交修改詳細分類

### 產品規格文件修改（15 files，tracked）
路徑：`docs/product-v3/`  
檔案：AI-EXPERIENCE.md, BACKEND-IMPACT.md, DESIGN-SYSTEM.md, FEATURE-PLAN.md, FRONTEND-ARCHITECTURE.md, IMPLEMENTATION-PLAN.md, INFORMATION-ARCHITECTURE.md, JOB-TO-BE-DONE.md, PRODUCT-ARCHITECTURE.md, PRODUCT-VISION.md, README.md, TARGET-USERS.md, USER-JOURNEYS.md, UX-DESIGN.md, VISUAL-DIRECTION.md

**目的**：UI 改進、功能微調、決策記錄  
**狀態**：應保留，作為產品方向參考  
**建議**：不納入 Phase 1 commit，分開提交或待後續決策

### API 層修改（1 file，tracked）
路徑：`shop/api.py`  
修改：SPA 靜態路由掛載 + 照片路徑相容性  
行數變更：+50 lines  

**目的**：支援 V3 前端 SPA 路由回退，相容多種照片 URL 格式  
**狀態**：已實作，待驗證  
**測試**：test_v3_core_slice.py 中的 `test_web_spa_serving_and_routing` 驗證  
**建議**：與 web/ 同時 commit（Phase 1A）

### V3 前端實作（web/ 目錄，untracked）
路徑：`web/`  
檔案：index.html, app.js, app.css + core/{api.js, router.js, store.js} + views/{capture.js, home.js, record-detail.js, settings.js} + i18n/{index.js, zh-TW.js, en.js}

**目的**：零建置 SPA 前端實作，支援 Capture → AI → Save → Retrieve 完整流程  
**狀態**：已實作，已測試  
**測試**：
  - test_v3_core_slice.py (5 scenarios) ✓ 全通過
  - test_capture_ui.py, test_inbox_ui.py 也驗證前端邏輯
**建議**：Phase 1A 正式 commit

### V3 驗收測試（1 file，untracked）
路徑：`tests/test_v3_core_slice.py`  
測試數：5 scenarios（Scenario A–C + photo serving + SPA routing）  

**目的**：驗收 V3 核心流程  
**狀態**：已實作，已通過  
**驗收標準**：
  - Capture → AI 整理 → 存下來 → 找得到 ✓
  - 連續多件拍攝無需重複設定 ✓
  - 生活隨拍無規格強制 ✓
  - 照片 byte-for-byte 保存 ✓
  - SPA 路由回退正常 ✓
**建議**：與 web/ 同時 commit（Phase 1A）

### 工程文件（docs/engineering/，untracked）
新增檔案：
  - ROADMAP.md（405 lines） —— 施工藍圖
  - STATUS.md（此檔） —— 當前進度
  - DECISIONS.md（280+ lines） —— 技術決策
  - AGENT_GUIDE.md（250+ lines） —— 施工規則

**目的**：建立工程控制系統，供 Agent 與人工審查使用  
**狀態**：Phase 0 成果  
**建議**：作為 Phase 0 baseline 提交（獨立 commit），或合併入 Phase 1B（工程文件 commit）

### 根目錄 AGENTS.md（untracked）
新增檔案：`AGENTS.md`

**目的**：Agent 工作流入口，簡短指引  
**狀態**：Phase 0 成果  
**建議**：與工程文件同時提交

### 無需處理
- IDE 配置、快取、lock 檔案（已在 .gitignore）

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| HEAD | 與 origin/main 同步 |
| Ahead/Behind | 0 ahead, 0 behind（完全同步） |
| Uncommitted Changes | 18 files（15 product-v3 modified + 1 shop/api.py modified + 2 untracked: web/, test_v3_core_slice.py） |
| 衝突 | 無 |
| 新增工程文件 | docs/engineering/{ROADMAP.md, STATUS.md, DECISIONS.md, AGENT_GUIDE.md}（均 untracked） |
| 根目錄 AGENTS.md | 新增（untracked） |

**建議**：Phase 1 開始後，將相關工作按邏輯分組為獨立 commit（見下節）

---

## 下一個明確任務

### 優先順序 1（Phase 1 工作 A）
**將 V3 前端與驗收測試正式整合**

檢查清單：
- [ ] `web/` 所有檔案確認完整
- [ ] `tests/test_v3_core_slice.py` 符合驗收標準
- [ ] `shop/api.py` 修改符合 SPA 掛載需求
- [ ] 運行 `pytest tests/test_v3_core_slice.py -v` 全部通過
- [ ] 運行完整 `pytest -q` 全通過
- [ ] 建立 commit

### 優先順序 2（Phase 1 工作 B）
**首頁新紀錄置頂與保存後回首頁**

依賴：完成優先順序 1

檢查清單：
- [ ] 修改 `GET /api/items` 支援排序參數（`sort=created_desc`）
- [ ] 前端保存成功後導航至首頁
- [ ] 新紀錄高亮顯示
- [ ] 搜尋順序也遵循置頂邏輯
- [ ] 補充相應測試
- [ ] 全測試通過

---

## 阻塞項與風險

| 項 | 優先級 | 狀態 | 緩解 |
|---|---|---|---|
| 前端正式化 | 高 | 待處理 | Phase 1 第一階段 |
| 生活備忘欄位設計 | 中 | 開放 | 參考 FEATURE-PLAN.md, JOB-TO-BE-DONE.md |
| 搜尋效能基線 | 低 | 未測 | Phase 4 時詳細評估 |

---

## 修改歷史

- **2026-10-09**：初始版本建立（Phase 0 audit 基線）

