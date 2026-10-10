# ItemTrace Engineering Status

最後更新：2026-10-10 13:10  
當前階段：Phase 2C-C 完成（自主性驗證；本地 commit，未 push）  
遠端狀態：本地領先 origin/main（本階段 commit 後 10 ahead；未 push）  
測試驗證：`pytest -q` 完全通過，全 983 測試無失敗、無跳過（驗證階段未改程式碼與測試）

---

## 當前階段

**Phase 2C-C：驗證自主 AI 行為（Live 模型實測）** ← **COMPLETED**（驗證階段；未改產品程式碼／schema／API／測試）

完成時間：2026-10-10  
Commit：`docs: phase-2c-c validate autonomous ai behavior`（本地，未 push）
報告：`docs/engineering/AI-AUTONOMY-VALIDATION.md`

完成內容：
- ✓ **Live 實測 7 次成功＋1 次 4xx**（`google / gemini-3.5-flash-lite`，free tier，僅合成 fixture）＋新增 2 個錄製情境（C1／C4b）與 4 張合成圖
- ✓ **修訂路徑可行（Live）**：BOSE 標籤自動填入 → 加入 SONY 標籤後 `brand/model` **自動修訂**；`country_of_origin` 自動；BOSE/SONY 兩個序號都輸出 → 同欄位矛盾 → **雙雙升級衝突確認**（政策正確攔截）
- ✓ **使用者保護（Live）**：手打名稱不受收據影響（留待確認）；品牌/型號/購買資訊（同張收據）自動；備註完好
- ✓ **證據選擇（Live）**：9 張紀錄送出 8 張（最早 2＋最新 6），`brand/model/serial` 全部溯源最早標籤；配件收據購買資訊升級衝突（正確不誤掛）
- ✓ **失敗/重試（Live）**：無效模型 → 400、照片保留、零寫入；重試成功、紀錄完整
- ✓ **描述行為（Live）**：可描述物件（馬克杯）→ `name=馬克杯`＋`category=日用品`＋`color=紅色`；**9 情境中 `attribute:description` 出現 0 次**（產品缺口，見報告 §2）
- ✓ **缺陷重現**：過期 undo——使用者改過 brand 後，對較舊自動套用按「復原」→ 使用者值被靜默清空（報告 §4；列入 2C-D 驗收）
- ✓ 決策性產出：2C-D 五條驗收條件（undo 防護、描述 prompt、跨照片身分聲明、修訂前後值可見、全測試＋E2E）
- ✓ 未改產品程式碼、schema、API、既有測試；未 push；未傳任何真實資料

### Phase 2C-C 驗證結論摘要（細節見報告）

| 面向 | 結論 |
|---|---|
| 自動修訂 | ✓ Live 可行（BOSE→SONY）；跨照片身分「沉默擇一」仍需 prompt 導正 |
| 使用者保護 | ✓ Live 可行（名稱/備註不動；編輯後不再自動） |
| 衝突處理 | ✓ 三種內容泛化（L4 回放、C4b、S3 背帶收據）；重複值偵測連模型「兩者都給」也接得住 |
| 證據選擇 | ✓ Live 修復 L6a（最早標籤進得來） |
| 描述契約 | ✗ `attribute:description` 從未被使用（建議最小 prompt 調整，未實作） |
| Undo | ✗ 過期 undo 可覆寫後續編輯（已重現；2C-D 修補） |

### Phase 2C-B 自動套用規則（實作即規格）

| 類別 | 規則 |
|---|---|
| 描述性 `attribute:*`（非購買類） | 空值自動填入；`auto` 來源可自動修訂；使用者動過 → 確認 |
| 購買資訊（vendor/amount/price/purchase_date… ） | 僅「現值為空＋使用者未動＋同一張照片也提供身分資訊」自動；否則衝突確認 |
| `name`／`brand`／`model` | 空值自動填入；`auto` 來源可自動修訂；user（編輯/確認/清空/復原）→ 確認 |
| `identifier:*`、`category`、`condition`、`notes` | 永遠待確認（T0／T2） |
| 矛盾值（同一輪同欄位不同值） | 全部轉衝突確認 |
| 無來源照片 | 不自動（證據支持不足） |
| 與現值相同 | 直接丟棄（不佔建議） |
| 信心值 | 僅記錄，不參與任何決策 |

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
- Phase 2C-A：AI 評測與自主性政策（`dda8b61`）
- Phase 2C-B：可回復的 AI 自動更新與證據感知自主性（`7927faf`）

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 37 | conftest + 36 test_*.py |
| 總測試數 | 983 | 全 pytest 計數（Phase 2C-B +21） |
| 通過 | 983 ✓ | 100% pass rate |
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
- **V3 核心驗收**：test_v3_core_slice.py (14) —— 原始 5 情境 + Phase 1B-A 5 項 + Phase 2A 1 項 + Phase 2B 2 項 + Phase 2C-B 1 項
- **評測 harness**：test_evaluate_models.py (7) —— 離線重播、契約回歸守門、live 需 --allow-live（不碰網路）

**最近運行**：2026-10-10，`pytest -q --junitxml` → tests=983, failures=0, errors=0, skipped=0

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 983 個 pytest 全通過，V3 core slice test 驗收 |
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
- ✓ AI 評測 harness 與自主性政策（Phase 2C-A；工具＋文件，未改產品行為） — **Implemented, Tested, Committed（dda8b61）, Not Pushed**
- ✓ 可回復的 AI 自動更新（Phase 2C-B：選擇策略、自動套用、undo、衝突升級） — **Implemented, Tested, Committed（7927faf）, Not Pushed**
- ✓ 自主性驗證與殘餘缺口（Phase 2C-C：Live 實測、報告、fixture／錄製） — **Evaluated, Committed（本階段）, Not Pushed**

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

### 立即待做（Phase 2C-D：驗證結論收斂，建議；依 AI-AUTONOMY-VALIDATION.md §7）
1. **undo 過期防護**：目前值 ≠ 該次自動套用值時回 409（不再靜默覆寫後續編輯）
2. **描述 prompt 調整**（最小）：看得見但認不出 → 以描述性 `name`＋`attribute:description`（看見 vs 推測）；C1 期望加入「必須有描述且不得編造品牌/型號」
3. **跨照片身分聲明 prompt**：不同照片支持不同身分時分別輸出（讓既有重複值偵測升級衝突）；新增 harness 情境 C6
4. 修訂 banner 顯示前後值（BOSE → SONY）＋確認清單保留「先前判讀（已被取代）」
5. 全測試通過＋一次瀏覽器 E2E；零 schema migration

### 接著（Phase 3：垃圾桶與資料生命週期）
- 依 `ROADMAP.md` Phase 3：垃圾桶 UI／30 天保留／永久刪除（明確使用者意圖、可稽核）

### 短期（Phase 2–3）
- Phase 2：AI Contract 2.0 —— **完成（2A 生命週期、2B 證據累積、2C-A 評測、2C-B 可回復自動套用、2C-C Live 驗證；2C-D 收斂待做）**
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
| 矛盾證據被靜默合併 | 中 | 已解決 | Phase 2C-B：L4 錄製輸出回放 → 購買資訊轉 `external_conflict` 確認，絕不自動併入 |
| 最新-8 選擇會丟最早的身分照 | 中 | 已解決 | Phase 2C-B：「最早 2＋最新 6」；邊界與兩端整合測試 |
| 模型自報信心無鑑別力 | 低 | 已驗證（全場 0.9~1.0） | 政策不得依賴信心；信心僅記錄 |
| `attribute:description` 未被模型自發產生 | 中 | 已驗證（2C-C Live：9 情境 0 次） | 2C-D：最小 prompt 調整＋C1 驗收（見 AI-AUTONOMY-VALIDATION §2） |
| 過期 undo 可覆寫後續編輯 | 中 | 已重現（2C-C） | 使用者改過值後按較舊的復原 → 靜默清空；2C-D：值不符回 409 |
| 跨照片身分「沉默擇一」 | 中 | 已驗證（2C-C S1b） | 模型直接以新標籤修訂舊身分（非錯誤但無示警）；2C-D：prompt 身分聲明＋C6 |
| 屬性逐鍵來源標籤（✨AI／✍手動） | 低 | 開放 | 目前以 banner＋事件/建議可追溯；逐鍵 UI 標籤後續 |
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

## Phase 2C-A 變更清單（commit `dda8b61`，前次）

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

## Phase 2C-B 變更清單（commit `7927faf`，前次）

| 檔案 | 變更 |
|---|---|
| `shop/repo.py` | 政策常數（識別欄位／確認欄位／購買鍵／來源標記）；`commit_analysis()`（2A 生命週期＋auto 決策＋自動套用，同交易）；`_field_provenance()`（事件推導 none/auto/user）；`_apply_auto()`；`undo_auto_suggestion()`；純函式 `_auto_decision`／`_conflicting_fields`／`_drop_unchanged_entries`／`_current_value`；`replace_pending_suggestions` 改委派 |
| `shop/api.py` | analyze 新增 `?auto=1`；`_select_photos_for_analysis`（最早 2＋最新 6）；`POST /api/suggestions/{id}/undo` |
| `web/views/record-detail.js` | 詳情頁 auto=1；「✨ 已自動更新＋復原」banner；待確認列加來源照片 `📷 #n` 與衝突 ⚠️ 說明；修掉型號整列重複 |
| `web/core/api.js` | `analyzeItem(id,{auto})`、`undoSuggestion` |
| `web/i18n/zh-TW.js`, `web/i18n/en.js` | +5 keys × 2（analysisApplied／undo／undoDone／undoFailed／conflictNote） |
| `web/app.css` | `is-applied`、`suggestion-photo`、`is-conflict`、conflict note 樣式 |
| `tests/test_ai_analyze.py` | +17（選擇邊界、自動填入/修訂、使用者保護、L3/L4 錄製回放、矛盾、跳過同值、undo×3、失敗、信心無關） |
| `tests/test_repo_suggestions.py` | +3（矛盾欄位、丟棄同值、auto 整批回滾） |
| `tests/test_v3_core_slice.py` | +1（2C-B 前端接線靜態檢查） |
| `docs/engineering/STATUS.md`, `ROADMAP.md` | 狀態校準 |

**未變更**：schema（零 migration）、API 契約形狀（analyze 回應增列 auto 項目、排序 applied→pending）、media 結構、capture/settings view。

---

## Phase 2C-C 變更清單（本階段 commit）

| 檔案 | 變更 |
|---|---|
| `docs/engineering/AI-AUTONOMY-VALIDATION.md` | 新增：Live 驗證報告（結果、描述契約、選擇策略、undo/provenance 建議、殘餘失敗模式、2C-D 驗收條件） |
| `tools/make_eval_images.py` | 新增 fixture：馬克杯物件圖、BOSE/Canon 標籤、HP 墨水匣收據 |
| `tools/eval_fixtures/images/`（+4 張） | `object_mug.jpg`、`label_bose.jpg`、`label_canon.jpg`、`receipt_hp_ink.jpg` |
| `tools/eval_fixtures/scenarios.json` | +2 情境（`C1_unknown_mug`、`C4b_conflict_printers`） |
| `tools/eval_fixtures/recorded/` | +2 錄製（C1／C4b 真實模型輸出）＋`summary.json` 記錄兩次 run |
| `docs/engineering/STATUS.md`, `ROADMAP.md`, `AGENTS.md` | 狀態校準 |

**未變更**：產品程式碼（shop/、web/）、schema、API、既有測試（983 全保留）；實際 live 呼叫 7 次成功＋1 次 4xx（僅合成 fixture）。

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| Ahead/Behind | 10 ahead, 0 behind（未 push；本階段 commit 後） |
| Uncommitted Changes | 0（本階段變更全數進入獨立 commit） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda`、`98edc0c`、`ef85450`、`15f2e9b`、`22b0c22`、`dda8b61`、`7927faf` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 2C-D：驗證結論收斂（依 AI-AUTONOMY-VALIDATION.md §7）
檢查清單：
- [ ] undo 過期防護（值不符 → 409；測試＋瀏覽器路徑）
- [ ] 描述 prompt 規則＋`C1` 期望升級（必須有描述、不得編造品牌/型號）＋離線重播全綠
- [ ] 跨照片身分聲明 prompt＋新 harness 情境 `C6_two_identity_labels`
- [ ] 修訂 banner 顯示前後值＋確認清單保留「先前判讀（已被取代）」
- [ ] 全測試通過＋一次瀏覽器 E2E；零 schema migration

### 接著（Phase 3：垃圾桶與資料生命週期）
- 垃圾桶頁面（void 紀錄）＋還原；30 天保留與永久刪除（明確使用者意圖、可稽核）

### AI-Native 架構研究對照（`docs/engineering/AI-NATIVE-ARCHITECTURE.md`）
- ✓ S1（提案命名空間）→ Phase 2B：`attribute:<key>` 受驗證契約
- ✓ S2（修訂語意＋可靠性修正）→ Phase 2A
- ◐ S3（前端呈現/可溯性）→ 審閱＋屬性顯示＋失敗重試＋自動更新 banner/undo 完成；逐鍵來源標籤後續
- ✓ S4（模型評測 harness）→ Phase 2C-A（評測＋政策；含真實模型證據）＋2C-C（Live 驗證）
- ✓ S5（受控自動套用）→ Phase 2C-B：決定性政策、可回復、衝突升級；2C-C 驗證修訂可行、抓到 undo 過期缺陷
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
- **2026-10-10**：Phase 2C-B 完成——證據選擇「最早 2＋最新 6」；可回復的自動套用（描述屬性／空身分／auto 修訂；決定性、不看信心）；使用者保護（編輯/確認/清空/復原皆鎖定）；衝突升級（L4 錄製回放）；`POST /suggestions/{id}/undo`；詳情頁 banner＋復原；瀏覽器 E2E（自動更新→復原→套用→搜尋）；測試基線 962 → 983
- **2026-10-10**：Phase 2C-C 完成——Live 驗證（7 次成功＋1 次 4xx、僅合成圖）：自動修訂可行（BOSE→SONY）、使用者保護、衝突泛化、9 張選擇修復、失敗/重試；抓到「過期 undo 可覆寫後續編輯」缺陷；`attribute:description` 0/9 出現；產出 2C-D 五條驗收條件；測試基線不變 983（未改程式碼/測試）
