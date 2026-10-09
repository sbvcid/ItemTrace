# ItemTrace Engineering Status

最後更新：2026-10-09 18:55  
當前階段：Phase 2B 已完成（本地 commit，未 push）  
遠端狀態：本地領先 origin/main（本階段 commit 後 7 ahead；未 push）  
測試驗證：`pytest -q` 完全通過，全 955 測試無失敗、無跳過

---

## 當前階段

**Phase 2B：證據累積與情境式重新理解** ← **COMPLETED**

完成時間：2026-10-09  
Commit：`feat: phase-2b evidence accumulation and contextual reinterpretation`（本地，未 push）

完成內容：
- ✓ 詳情頁可「加入照片」到既有紀錄（新 observation → 上傳 → 自動重新分析），不建立新紀錄；stable id、created_at、原照片全保留
- ✓ 分析把「既有詮釋（欄位＋attributes＋使用者備註）」與全部（或最新 8 張）證據一起送給 AI；prompt 明確以照片為準
- ✓ 契約最小擴充：`attribute:<key>` 提案（key pattern 由軟體強制、值非空、單輪上限 24 筆）；`description` 為慣例 key
- ✓ accept 屬性為「單鍵合併」，不覆蓋使用者自己填的 attributes；使用者備註不被分析覆蓋
- ✓ 嚴格驗證整批失敗（非法 key／超量）；新的 UI：待確認清單（套用／拒絕／全部套用）＋屬性顯示區塊
- ✓ 失敗語意：照片先落地；分析失敗顯示「照片已保存，但 AI 整理未完成」＋重試；失敗保留既有 pending
- ✓ 搜尋保留：`q` 額外命中曾被接受（accepted）的舊建議值；pending/superseded/rejected 猜測不入搜尋
- ✓ 修正併發缺陷（瀏覽器測試抓到）：per-request 連線並行 accept → `database is locked`；`db.transaction` 改 `BEGIN IMMEDIATE` ＋ 回歸測試
- ✓ 新增 15 測試（AI 7 ＋ repo 3 ＋ search 2 ＋ V3 情境/靜態 2 ＋ 交易併發 1）；全 955 通過
- ✓ 瀏覽器端到端（臨時資料根目錄、假 provider）：加入收據 → 自動分析 → 待確認清單 → 全部套用 → 名稱/屬性更新、備註保留 → 搜尋命中；另驗失敗橫幅＋重試

### Phase 2B 契約規則（實作即規格）

| 規則 | 內容 |
|---|---|
| 提案欄位 | 固定欄位 ∪ `identifier:<kind>` ∪ `attribute:<key>`（`^[a-z][a-z0-9_]{0,39}$`） |
| 屬性接受 | 單鍵合併進 `items.attributes`；其他鍵（含使用者填的）一律保留；事件記 attributes 前後快照 |
| 分析不覆蓋 | 分析只產生 pending；主表（含 notes）在任何人接受前不變 |
| 失敗邊界 | 照片保存與分析是兩件事：分析失敗照片仍在；失敗不動既有 pending |
| 搜尋保留 | `q` 命中 accepted 建議值；未經確認的猜測永不進搜尋 |
| 併發寫入 | 交易一律 `BEGIN IMMEDIATE` ＋ `busy_timeout=5000`：先到先做，不噴 locked |

### AI 建議生命週期規則（Phase 2A，實作即規格）

| 情境 | 規則 |
|---|---|
| 新分析成功（含空結果） | 該商品所有 `pending` → `superseded`（同交易），新建議寫入為 `pending` |
| 新分析失敗（provider 故障／格式錯誤／未設定） | 不寫任何資料；既有 `pending` 原封不動 |
| `accepted` / `rejected` | 永遠是歷史：不受後續分析影響、不可再變更、不會回到 pending |
| `superseded` | 終態：不可 accept / reject / update；保留事件與決策時間 |
| Accept 失敗 | 整筆回滾（含事件）；建議留在 `pending` 可重試；不會先標 accepted |
| 重複 accept | 400；不重複套用變更（交易 + pending 檢查為第二道保險） |

前序已完成：
- Phase 0：基線盤點與工程控制文件（`6bfdeda`）
- Phase 1A：V3 SPA 前端整合與核心驗收（`2879904`）
- Phase 1B-A：首頁基本流程（`98edc0c`）
- Phase 2A：AI 建議生命週期與部分失敗語意（`15f2e9b`）

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 36 | conftest + 35 test_*.py |
| 總測試數 | 955 | 全 pytest 計數（Phase 2B +15） |
| 通過 | 955 ✓ | 100% pass rate |
| 失敗 | 0 | 零失敗 |
| 跳過 | 0 | 無跳過 |
| 覆蓋率 | 未測 | 建議後續補充 |

**測試框架**：pytest（可選 pytest-cov 補充覆蓋率）

**主要測試分類**：
- API 端點：test_api.py (82), test_phase8a_api.py (35), test_settings_api.py (43) 等
- 資料庫 & Repo：test_repo_*.py (13-23 each), test_db_transactions.py (8)
- AI & 分析：test_ai_*.py (15-78), test_analyze_item.py (78)
- 前端與 UI：test_capture_ui.py (6), test_inbox_ui.py (35)
- 列印：test_print.py (31), test_print_settings_api.py (20)
- **V3 核心驗收**：test_v3_core_slice.py (13) —— 原始 5 情境 + Phase 1B-A 5 項 + Phase 2A 1 項 + Phase 2B 2 項

**最近運行**：2026-10-09，`pytest -q --junitxml` → tests=955, failures=0, errors=0, skipped=0

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 955 個 pytest 全通過，V3 core slice test 驗收 |
| **Committed** | 變更已進入版本控制 | main branch 上的所有程式碼 |
| **Pushed** | 變更已推送到遠端 | origin/main 的最新狀態（多個本地 commit 未 push；見下方同步狀態） |

### 核心產品體驗
- ✓ 手機隨手拍照 (Capture) — **Implemented, Tested, Committed, Pushed**
- ✓ AI 自動整理與建議 — **Implemented, Tested, Committed, Pushed**
- ✓ 超低摩擦確認（一鍵存起來） — **Implemented, Tested, Committed, Pushed**
- ✓ 紀錄詳細檢視與大圖展示 — **Implemented, Tested, Committed, Pushed**
- ✓ 即時文字 & 序號搜尋 — **Implemented, Tested, Committed, Pushed**
- ✓ 隨手追加照片與筆記 — **Implemented, Tested, Committed, Pushed**
- ✓ V3 前端（Capture/Home/Detail/Settings 完整實作） — **Implemented, Tested, Committed（2879904）, Not Pushed**
- ✓ 首頁最新紀錄置頂與保存後回首頁（Phase 1B-A） — **Implemented, Tested, Committed（98edc0c）, Not Pushed**
- ✓ AI 建議生命週期與部分失敗語意（Phase 2A） — **Implemented, Tested, Committed（15f2e9b）, Not Pushed**
- ✓ 證據累積與情境式重新理解（Phase 2B） — **Implemented, Tested, Committed（本階段）, Not Pushed**

### 後端基礎
- ✓ SQLite + WAL + STRICT 約束 — **Implemented, Tested, Committed, Pushed**
- ✓ Items/Photos/Observations/Suggestions/Identifiers/Events 六表 — **Implemented, Tested, Committed, Pushed**
- ✓ 推論與事實分離（Suggestions 隔離） — **Implemented, Tested, Committed, Pushed**
- ✓ Event sourcing 與單欄位復原 — **Implemented, Tested, Committed, Pushed**
- ✓ FastAPI HTTP API 與文件 — **Implemented, Tested, Committed, Pushed**
- ✓ 照片原始檔案保存（files/original/） — **Implemented, Tested, Committed, Pushed**
- ✓ 搜尋與全文過濾 — **Implemented, Tested, Committed, Pushed**
- ✓ items.attributes JSON 動態屬性（含 AI `attribute:<key>` 提案與單鍵合併） — **Implemented, Tested, Committed**（Phase 2B）

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

### 立即待做（Phase 2C：模型評測 harness —— study S4，建議）
1. **模型評測與回歸**
   - 固定評測案例集（商品標籤／序號混淆／收據／寵物／不明零件／多照片）
   - `tools/evaluate_models.py`：離線 fixture 重播 ＋ 可選真實 provider；輸出 JSON 報告
   - 契約（prompt/schema）變更時偵測回歸；換模型只改 `ai_config.local.json`

### 替代順序
- Phase 1B-B 紀錄編輯完善（ROADMAP Phase 1B 剩餘項）

### 短期（Phase 2–3）
- Phase 2（2A、2B 完成）：AI Contract 2.0 —— 提案命名空間 ✓、證據累積與情境式理解 ✓、模型評測（S4）待做
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
| Capture 部分失敗被靜默吞掉 | — | 已解決 | Phase 2A：failures 追蹤 + `savePartial` 訊息 + 原地重試；重試不重複 |
| 併發寫入噴 database is locked | — | 已解決 | Phase 2B（瀏覽器測試抓到）：`BEGIN IMMEDIATE` ＋ `busy_timeout`；回歸測試 test_db_transactions |
| 照片路徑相容性 | 低 | 已實作，已測 | `/files/ITM-xxxx/` 與 `/files/files/` 相容（test_v3_core_slice） |
| i18n 覆蓋率 | 低 | 完整 | 前端全文字已翻譯（1B-A +2、2A +1、2B +19 keys × 2） |
| `matched_identifier` 不在列表 API | 低 | 已知 | 前端序號欄位目前退回顯示 model；需要的話後續階段補 |
| 外部 adapter 重新分析不觸發 supersede | 低 | 已知 | tools/analyze_item.py 走通用 `POST /suggestions` 逐筆建立；只有伺服器端 analyze 具「最新詮釋」語意 |
| 生活備忘欄位設計 | 中 | 開放 | Phase 1B-B；參考 FEATURE-PLAN.md, JOB-TO-BE-DONE.md |
| 搜尋效能基線 | 低 | 未測 | Phase 5 時詳細評估 |

---

## Phase 1B-A 變更清單（commit `98edc0c`，前次）

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

## Phase 2A 變更清單（commit `15f2e9b`，前次）

| 檔案 | 變更 |
|---|---|
| `shop/repo.py` | 新增 `replace_pending_suggestions()` + `_supersede_pending()`（同交易 supersede + 寫入；`suggestion.superseded` 事件；主表不動） |
| `shop/api.py` | `POST /api/items/{id}/ai/analyze` 改用原子替換；失敗路徑仍不落地 |
| `web/views/capture.js` | 部分失敗追蹤（`appliedSuggestionIds` / `appliedSerialValue`）、`savePartial` 訊息、重試不重複、序號不重複建立 |
| `web/i18n/zh-TW.js`, `web/i18n/en.js` | 新增 `savePartial` |
| `tests/test_repo_suggestions.py` | +3（supersede 範圍／原子性／終態） |
| `tests/test_ai_analyze.py` | +8（re-analysis supersede／失敗保留／空結果規則／accept 失敗／重試不重複） |
| `tests/test_v3_core_slice.py` | +1（capture 部分失敗靜態接線檢查） |
| `docs/engineering/STATUS.md`, `ROADMAP.md` | Phase 2A 完成與下一階段 |

**未變更**：schema（零 migration）、`items` 主表欄位、API 契約（回應形狀不變）、其他 view。

---

## Phase 2B 變更清單（本階段 commit）

| 檔案 | 變更 |
|---|---|
| `shop/models.py` | `ATTRIBUTE_FIELD_PREFIX`／`ATTRIBUTE_KEY_PATTERN`／`attribute_key()`；`Suggestion.attribute_key` |
| `shop/ai_client.py` | PROMPT 改為整理助手＋上下文規則＋`attribute:<key>` 指引；`RESPONSE_SCHEMA` 改 pattern；`MAX_SUGGESTIONS=24`；`build_request_body`／`call_ai_provider` 新增 keyword-only `context`（向後相容） |
| `shop/api.py` | analyze：附上 `_analysis_context(item)`（既有詮釋）＋超過上限時保留最新 8 張 |
| `shop/repo.py` | `_validate_suggestion` 接受 `attribute:<key>`；accept 屬性「單鍵合併」；`list_items` 搜尋額外命中 accepted 建議值 |
| `shop/db.py` | `transaction` 改 `BEGIN IMMEDIATE`（修併發 `database is locked`） |
| `web/views/record-detail.js` | 加入照片（observation→upload→自動重新分析）、待確認清單（套用／拒絕／全部套用）、補充資訊區、失敗橫幅＋重試 |
| `web/core/api.js` | `createObservation`／`uploadObservationPhotos`／`rejectSuggestion` |
| `web/app.css` | toolbar／analysis-status／suggestion-review／attribute 樣式 |
| `web/i18n/zh-TW.js`, `web/i18n/en.js` | 新增 19 keys × 2 |
| `tests/`（8 檔） | +15 測試；更新 3 個契約釘樁（schema pattern／簽章＋context／stdlib 清單） |
| `docs/engineering/STATUS.md`, `ROADMAP.md` | Phase 2B 完成與下一階段 |

**未變更**：schema（零 migration）、API 契約形狀、media 儲存結構、capture/home/settings view。

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| Ahead/Behind | 7 ahead, 0 behind（未 push；本階段 commit 後） |
| Uncommitted Changes | 0（本階段變更全數進入獨立 commit） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda`、`98edc0c`、`ef85450`、`15f2e9b` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 2C：模型評測 harness（study S4；建議）
檢查清單：
- [ ] 評測案例集（商品／序號混淆／收據／寵物／不明零件／多照片）＋離線 fixture 重播
- [ ] `tools/evaluate_models.py` 產出 JSON 報告（準確率／失敗模式／延遲）
- [ ] 契約（prompt/schema）變更時的回歸偵測；換模型只改設定檔
- [ ] 全測試通過

（替代順序：Phase 1B-B 紀錄編輯完善 —— 見 ROADMAP Phase 1B 剩餘項。）

### AI-Native 架構研究對照（`docs/engineering/AI-NATIVE-ARCHITECTURE.md`）
- ✓ S1（提案命名空間）→ Phase 2B：`attribute:<key>` 受驗證契約
- ✓ S2（修訂語意＋可靠性修正）→ Phase 2A
- ◐ S3（前端呈現/可溯性）→ Phase 2B 完成審閱＋屬性顯示＋失敗重試；來源標籤（✨AI/✍手動）尚待
- 待做：S4（模型評測 harness）＝ Phase 2C
- 研究結論：不換資料模型；全部 additive、無 schema migration

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
- **2026-10-09**：新增 AI-Native 架構研究（`docs/engineering/AI-NATIVE-ARCHITECTURE.md`）；本次未變更程式碼、schema、資料、前端或測試
- **2026-10-09**：Phase 2A 完成——AI 建議生命週期（成功分析 supersede 舊 pending／失敗保留／superseded 終態）與 capture 部分失敗語意（誠實回報＋原地重試不重複）；測試基線 928 → 940
- **2026-10-09**：Phase 2B 完成——證據累積（詳情頁加入照片、不建新紀錄）、情境式重新理解（既有詮釋＋新證據）、`attribute:<key>` 契約、失敗保留與重試、accepted 詞彙搜尋保留、`BEGIN IMMEDIATE` 併發修正；測試基線 940 → 955
