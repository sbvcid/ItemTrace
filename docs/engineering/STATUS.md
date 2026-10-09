# ItemTrace Engineering Status

最後更新：2026-10-09 15:45  
當前階段：Phase 1B-A 已完成（本地 commit，未 push）  
遠端狀態：本地領先 origin/main 4 commits（`2879904` 1A、`4318ae0` 產品規格、`6bfdeda` 工程文件、本階段）  
測試驗證：`pytest -q` 完全通過，全 928 測試無失敗、無跳過

---

## 當前階段

**Phase 1B-A：首頁基本流程（最新置頂、保存後回首頁）** ← **COMPLETED**

完成時間：2026-10-09  
Commit：`feat: phase-1b-a home flow - newest-first list, save-to-home, latest card`（本地，未 push）

完成內容：
- ✓ `GET /api/items` 預設依 `created_at DESC, id DESC` 排序（修改舊紀錄不會跳到最前面；搜尋沿用同一順序）
- ✓ Capture 保存成功後回首頁（`/?fresh=<item_id>`），不再直達詳細頁
- ✓ 首頁最新紀錄放大卡片：品名、品牌／型號／分類、狀況、照片數、建立日期
- ✓ 剛存入紀錄短暫高亮 +「✨ 剛剛存入」文字標籤（不以顏色為唯一線索）
- ✓ 舊紀錄維持緊湊卡片，點擊仍進入既有 Detail 頁
- ✓ 新增 7 測試、更新 2 個既有排序斷言（未刪除、未弱化）
- ✓ 瀏覽器煙霧測試（臨時資料根目錄、AI 停用）：保存 → 回首頁 → 第一筆 → Detail → 搜尋

前序已完成：
- Phase 0：基線盤點與工程控制文件（`6bfdeda`）
- Phase 1A：V3 SPA 前端整合與核心驗收（`2879904`）

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 36 | conftest + 35 test_*.py |
| 總測試數 | 928 | 全 pytest 計數（Phase 1B-A +7） |
| 通過 | 928 ✓ | 100% pass rate |
| 失敗 | 0 | 零失敗 |
| 跳過 | 0 | 無跳過 |
| 覆蓋率 | 未測 | 建議後續補充 |

**測試框架**：pytest（可選 pytest-cov 補充覆蓋率）

**主要測試分類**：
- API 端點：test_api.py (82), test_phase8a_api.py (35), test_settings_api.py (43) 等
- 資料庫 & Repo：test_repo_*.py (13-23 each), test_db_transactions.py (7)
- AI & 分析：test_ai_*.py (15-78), test_analyze_item.py (78)
- 前端與 UI：test_capture_ui.py (6), test_inbox_ui.py (35)
- 列印：test_print.py (31), test_print_settings_api.py (20)
- **V3 核心驗收**：test_v3_core_slice.py (10) —— 原始 5 情境 + Phase 1B-A 5 項

**最近運行**：2026-10-09，`pytest -q --junitxml` → tests=928, failures=0, errors=0, skipped=0

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 928 個 pytest 全通過，V3 core slice test 驗收 |
| **Committed** | 變更已進入版本控制 | main branch 上的所有程式碼 |
| **Pushed** | 變更已推送到遠端 | origin/main 的最新狀態（目前落後 4 commits） |

### 核心產品體驗
- ✓ 手機隨手拍照 (Capture) — **Implemented, Tested, Committed, Pushed**
- ✓ AI 自動整理與建議 — **Implemented, Tested, Committed, Pushed**
- ✓ 超低摩擦確認（一鍵存起來） — **Implemented, Tested, Committed, Pushed**
- ✓ 紀錄詳細檢視與大圖展示 — **Implemented, Tested, Committed, Pushed**
- ✓ 即時文字 & 序號搜尋 — **Implemented, Tested, Committed, Pushed**
- ✓ 隨手追加照片與筆記 — **Implemented, Tested, Committed, Pushed**
- ✓ V3 前端（Capture/Home/Detail/Settings 完整實作） — **Implemented, Tested, Committed（2879904）, Not Pushed**
- ✓ 首頁最新紀錄置頂與保存後回首頁（Phase 1B-A） — **Implemented, Tested, Committed（本階段）, Not Pushed**

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
- ✓ 零建置 ESM 架構 — **Implemented, Tested, Committed（2879904）**
- ✓ 輕量路由 + 狀態管理 — **Implemented, Tested, Committed（2879904）**
- ✓ 繁中 + 英文 i18n — **Implemented, Tested, Committed**（Phase 1B-A 新增 2 keys × 2）
- ✓ 手機 + 桌面響應式排版 — **Implemented, Tested, Committed**
- ✓ 照片展示與 lazy loading — **Implemented, Tested, Committed**

### 進階能力（部分）
- ✓ 標籤列印 + QR Code（Chromium + GDI） — **Implemented, Tested, Committed, Pushed**
- ✓ 證據包匯出（manifest.json + photos） — **Implemented, Tested, Committed, Pushed**
- ✓ 列印設定管理 — **Implemented, Tested, Committed, Pushed**
- ✓ 本機備份 & 完整性驗證 — **Implemented, Tested, Committed, Pushed**

---

## 未完成工作

### 立即待做（Phase 1B-B）
1. **紀錄編輯完善**
   - 按需編輯（不自動觸發 AI 重新分析）
   - 生活備忘欄位（購買日期、保固、存放位置）利用現有 `items.attributes`
   - AI 建議與使用者備註來源清晰標示

### 短期（Phase 2–3）
- Phase 2：AI Contract 2.0（通用視覺紀錄、自然語言描述、模型評測）
- Phase 3：垃圾桶 & 30 天保留 + 永久刪除

### 中期（Phase 4–6）
- 分類系統與 AI 自動分類（Phase 4）
- SQLite FTS5 全文搜尋、繁簡互搜（Phase 5）
- 外觀比對器（Compare）、批次匯入 & 重複識別（Phase 6）

### 長期（Phase 7）
- Windows / Microsoft Store 發行準備

---

## 已知問題

| 問題 | 嚴重性 | 狀態 | 備註 |
|---|---|---|---|
| 首頁排序邏輯 | — | 已解決 | Phase 1B-A：預設 `created_at DESC`；分類導航延後（ROADMAP Phase 4/5） |
| 照片路徑相容性 | 低 | 已實作，已測 | `/files/ITM-xxxx/` 與 `/files/files/` 相容（test_v3_core_slice） |
| i18n 覆蓋率 | 低 | 完整 | 前端全文字已翻譯（Phase 1B-A +2 keys × 2） |
| `matched_identifier` 不在列表 API | 低 | 已知 | 前端序號欄位目前退回顯示 model；需要的話後續階段補 |
| 生活備忘欄位設計 | 中 | 開放 | Phase 1B-B；參考 FEATURE-PLAN.md, JOB-TO-BE-DONE.md |
| 搜尋效能基線 | 低 | 未測 | Phase 5 時詳細評估 |

---

## Phase 1B-A 變更清單（本階段 commit）

| 檔案 | 變更 |
|---|---|
| `shop/repo.py` | `list_items` 預設排序改為 `created_at DESC, id DESC`（搜尋路徑同） |
| `web/views/capture.js` | 保存成功後 `router.navigate('/?fresh=<id>')`（不再直達 `/i/<id>`） |
| `web/views/home.js` | 最新紀錄 featured 卡片；讀取 `fresh` 參照並高亮；搜尋維持緊湊排列 |
| `web/app.css` | `.record-card-featured`、`.record-card-fresh`、徽章與短暫光圈動畫 |
| `web/i18n/zh-TW.js`, `web/i18n/en.js` | 新增 `latestBadge`、`freshBadge` |
| `tests/test_v3_core_slice.py` | +5 Phase 1B-A 驗收測試（含靜態前端接線檢查） |
| `tests/test_repo_items.py` | +2 排序測試；更新分頁排序斷言 |
| `tests/test_api.py` | 更新分頁排序斷言 |
| `docs/engineering/STATUS.md`, `ROADMAP.md` | 狀態校準與排序方案修正 |

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| Ahead/Behind | 4 ahead, 0 behind（未 push） |
| Uncommitted Changes | 0（本階段變更全數進入獨立 commit） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 1B-B：紀錄編輯完善（建議）
檢查清單：
- [ ] 紀錄詳細頁按需編輯（不自動觸發 AI 重新分析）
- [ ] 生活備忘欄位（購買日期／保固／位置）使用現有 `items.attributes`
- [ ] AI 建議與使用者備註來源標示
- [ ] 補充測試、全測試通過

（備註：Phase 2「AI Contract 2.0」依 ROADMAP 只依賴 Phase 1A，可視產品優先級調整順序。）

---

## 阻塞項與風險

| 項 | 優先級 | 狀態 | 緩解 |
|---|---|---|---|
| 前端正式化 | — | 已解決 | Phase 1A commit `2879904` |
| 生活備忘欄位設計 | 中 | 開放 | Phase 1B-B；參考 FEATURE-PLAN.md |
| 搜尋效能基線 | 低 | 未測 | Phase 5 時詳細評估 |

---

## 修改歷史

- **2026-10-09**：初始版本建立（Phase 0 audit 基線）
- **2026-10-09**：Phase 1B-A 完成——首頁最新置頂（`created_at DESC`）、保存後回首頁＋短暫高亮、最新放大卡片；測試基線 921 → 928；狀態校準
