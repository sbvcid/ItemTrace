# ItemTrace Engineering Status

最後更新：2026-10-10 03:40  
當前階段：Phase 2C-A 完成（評測與政策；本地 commit，未 push）  
遠端狀態：本地領先 origin/main（本階段 commit 後 8 ahead；未 push）  
測試驗證：`pytest -q` 完全通過，全 962 測試無失敗、無跳過

---

## 當前階段

**Phase 2C-A：AI 評測與自主性政策** ← **COMPLETED**（評測／政策階段；未改產品程式碼）

完成時間：2026-10-10（資料收集 03:24）  
Commit：`feat: phase-2c-a ai evaluation harness and autonomy policy`（本地，未 push）

完成內容：
- ✓ Harness：`tools/evaluate_models.py`（離線重播＝契約回歸守門；`--live --allow-live` 受控即時模式、呼叫上限）＋`tools/make_eval_images.py`（合成 fixture，無個資）
- ✓ 情境集 7 個：清楚標籤／陌生物件／收據改變詮釋／矛盾證據／證據不足／九張照片之兩種選擇變體
- ✓ 真實模型評測（`google / gemini-3.5-flash-lite`，free tier，**8 次呼叫**、僅合成圖）：7/7 輸出合法；收據情境正確更新品名＋vendor/amount/date；不確定時空陣列；使用者資料未動
- ✓ 發現：模型自報信心無鑑別力（全場 0.90~1.00）；模型自發使用 `attribute:<key>` 且本輪詞彙一致（origin／vendor／amount／purchase_date）
- ✓ 發現（需政策）：矛盾證據被靜默合併（L4）；最新-8 會丟最早的身分標籤導致誤標（L6a：name→相機背帶；L6b 含標籤則型號/序號全對）
- ✓ 建議：證據選擇「最早 2＋最新 6」；自主性分層（T0 身分/識別碼永不自動；T1 描述性屬性自動、僅空值、可復原、不依賴信心）；2C-B 驗收條件 8 條
- ✓ 報告：`docs/engineering/AI-EVALUATION-REPORT.md`；+7 harness 測試；全 962 通過
- ✓ 未改產品程式碼、schema、API；未 push；未傳送任何真實資料

### Phase 2C-A 評測結論摘要（細節見報告）

| 面向 | 結論 |
|---|---|
| 契約承載力 | 7/7 合法；`attribute:<key>` 被自發且一致地使用 |
| 情境式更新 | 收據正確改變詮釋（L3 ✓）；矛盾證據無示警（L4 ✗ —— 政策必須覆蓋） |
| 不確定處理 | 無字／全黑 → 空陣列，不發明（L2／L5 ✓） |
| 證據選擇 | 最新-8 會丟最早身分照（L6a ✗）；最早 2＋最新 6 可修（L6b ✓） |
| 信心值 | 無鑑別力，不可作政策依據 |
| 可檢索性 | 正確欄位可搜；L6a 型誤標會破壞檢索 |

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
- Phase 2B：證據累積與情境式重新理解（`22b0c22`）

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 37 | conftest + 36 test_*.py（Phase 2C-A 新增 test_evaluate_models.py） |
| 總測試數 | 962 | 全 pytest 計數（Phase 2C-A +7） |
| 通過 | 962 ✓ | 100% pass rate |
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
- **評測 harness**：test_evaluate_models.py (7) —— 離線重播、契約回歸守門、live 需 --allow-live（不碰網路）

**最近運行**：2026-10-10，`pytest -q --junitxml` → tests=962, failures=0, errors=0, skipped=0

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 962 個 pytest 全通過，V3 core slice test 驗收 |
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
- ✓ 證據累積與情境式重新理解（Phase 2B） — **Implemented, Tested, Committed（22b0c22）, Not Pushed**
- ✓ AI 評測 harness 與自主性政策（Phase 2C-A；工具＋文件，未改產品行為） — **Implemented, Tested, Committed（本階段）, Not Pushed**

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
- ✓ 繁中 + 英文 i18n — **Implemented, Tested, Committed**（1B-A +2、2A +1、2B +19 keys × 2）
- ✓ 手機 + 桌面響應式排版 — **Implemented, Tested, Committed**
- ✓ 照片展示與 lazy loading — **Implemented, Tested, Committed**

### 進階能力（部分）
- ✓ 標籤列印 + QR Code（Chromium + GDI） — **Implemented, Tested, Committed, Pushed**
- ✓ 證據包匯出（manifest.json + photos） — **Implemented, Tested, Committed, Pushed**
- ✓ 列印設定管理 — **Implemented, Tested, Committed, Pushed**
- ✓ 本機備份 & 完整性驗證 — **Implemented, Tested, Committed, Pushed**

---

## 未完成工作

### 立即待做（Phase 2C-B：實作評測結論 —— 選擇策略＋T1 自動套用，建議）
1. **證據選擇**：>8 張時「最早 2＋最新 6」（≤8 全送不變）；單元測試覆蓋邊界
2. **自動套用政策 T1**：描述性 `attribute:*` 自動更新（僅空值或用戶未動過的鍵），身分/識別碼永不自動；不依賴模型信心
3. **可回復＋可見**：每次自動變更的事件/復原＋「AI 已自動更新」通知；衝突（新身分 ≠ 既有）升級回確認清單
4. **驗收**：`AI-EVALUATION-REPORT.md` §6 的 8 條全部滿足；含 fake-provider 回歸＋一次瀏覽器 E2E

### 替代順序
- Phase 1B-B 紀錄編輯完善（ROADMAP Phase 1B 剩餘項）

### 短期（Phase 2–3）
- Phase 2（2A、2B、2C-A 完成）：AI Contract 2.0 —— 提案命名空間 ✓、證據累積 ✓、評測 harness ✓、**自動套用政策實作（2C-B）待做**
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
| 矛盾證據被靜默合併 | 中 | 已驗證（評測 L4） | 2C-B：身分衝突升級確認；購買屬性僅空值自動；詳見 AI-EVALUATION-REPORT §5 |
| 最新-8 選擇會丟最早的身分照 | 中 | 已驗證（評測 L6a） | 2C-B：改「最早 2＋最新 6」（L6b 證明可行） |
| 模型自報信心無鑑別力 | 低 | 已驗證（全場 0.9~1.0） | 政策不得依賴信心；信心僅記錄 |
| `attribute:description` 未被模型自發產生 | 低 | 開放 | 生活描述 prompt 調校＋再評測（2C-B/後續） |
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

## Phase 2B 變更清單（commit `22b0c22`，前次）

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

## Phase 2C-A 變更清單（本階段 commit）

| 檔案 | 變更 |
|---|---|
| `tools/evaluate_models.py` | 新增評測 harness：離線重播（契約回歸守門、CI 可跑）＋`--live --allow-live` 受控即時模式（呼叫上限、逐情境錄製） |
| `tools/make_eval_images.py` | 合成 fixture 產生器（PIL；無個資） |
| `tools/eval_fixtures/scenarios.json` | 7 個評測情境＋結構化期望 |
| `tools/eval_fixtures/images/`（15 張） | 合成文字圖／雜訊圖（標籤、收據、不明物件、全黑、雜訊） |
| `tools/eval_fixtures/recorded/`（8 檔） | 真實模型輸出的錄製（`gemini-3.5-flash-lite`，free tier，僅合成圖）＋summary |
| `tests/test_evaluate_models.py` | +7（錄製存在、契約回歸守門、離線 CLI、live 需二次確認、期望語義） |
| `docs/engineering/AI-EVALUATION-REPORT.md` | 評測報告＋證據選擇建議＋自主性政策＋2C-B 驗收條件 |
| `docs/engineering/STATUS.md`, `ROADMAP.md`, `AGENTS.md` | 狀態校準 |

**未變更**：產品程式碼（shop/、web/）、schema、API、測試未刪修（既有 955 全保留）。

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| Ahead/Behind | 8 ahead, 0 behind（未 push；本階段 commit 後） |
| Uncommitted Changes | 0（本階段變更全數進入獨立 commit） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda`、`98edc0c`、`ef85450`、`15f2e9b`、`22b0c22` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 2C-B：實作評測結論（證據選擇＋T1 自動套用；依 AI-EVALUATION-REPORT §6）
檢查清單：
- [ ] 證據選擇「最早 2＋最新 6」（>8 張）；邊界單元測試（8/9/12 張）
- [ ] T1 自動套用：描述性 `attribute:*`（僅空值或 AI 上次套用的鍵；身分/識別碼永不自動；不依賴信心）
- [ ] 通知與復原：「✨ AI 已自動更新」＋一鍵復原（事件 prev/next）；衝突升級回確認清單
- [ ] 驗收 8 條全滿足（fake-provider 回歸＋一次瀏覽器 E2E）；全測試通過

（替代順序：Phase 1B-B 紀錄編輯完善 —— 見 ROADMAP Phase 1B 剩餘項。）

### AI-Native 架構研究對照（`docs/engineering/AI-NATIVE-ARCHITECTURE.md`）
- ✓ S1（提案命名空間）→ Phase 2B：`attribute:<key>` 受驗證契約
- ✓ S2（修訂語意＋可靠性修正）→ Phase 2A
- ◐ S3（前端呈現/可溯性）→ 審閱＋屬性顯示＋失敗重試完成；來源標籤（✨AI/✍手動）＝ 2C-B 隨自動套用一起補
- ✓ S4（模型評測 harness）→ Phase 2C-A（評測＋政策；含真實模型證據）
- 下一步 S5：受控自動套用（可回復；見 AI-EVALUATION-REPORT §5/§6）
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
- **2026-10-10**：Phase 2C-A 完成——評測 harness＋合成 fixture；實際評測 `gemini-3.5-flash-lite`（8 次呼叫、free tier、僅合成圖）：契約 7/7 合法、`attribute:<key>` 被自發使用、信心無鑑別力、L4 矛盾證據合併、L6a 選擇策略丟失身分；產出證據選擇建議與 T0/T1 自主性政策＋2C-B 驗收條件；測試基線 955 → 962
