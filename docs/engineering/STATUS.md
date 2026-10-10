# ItemTrace Engineering Status

最後更新：2026-10-11 00:00  
**當前狀態：手機優先 MVP 完成就緒**  
遠端狀態：本地 at `547a522`（SR-2 已 push），待提交：README 更新  
測試驗證：`pytest -q` 完全通過，全 **1049 測試**無失敗、無跳過

## 📱 MVP 交付檢查清單

**功能完整性** ✓：
- ✓ 拍照 → AI 分析 → 一鍵存檔 完整流程
- ✓ 已保存紀錄編輯、追加照片、AI 重新理解
- ✓ 搜尋名稱、品牌、型號、序號，即時找回
- ✓ 手機優先 UI，同時支援電腦操作
- ✓ AI 失敗優雅降級（存照片、無建議仍可用）

**測試涵蓋** ✓：
- ✓ 1049 個自動化測試全數通過
- ✓ 手機視口測試：尺寸 375×812，流程完整
- ✓ 搜尋功能驗證：模糊匹配正常
- ✓ 錯誤處理：上傳失敗、重試、部分失敗場景

**安全防護** ✓：
- ✓ SR-1：Host 白名單、Origin 驗證、CSRF 防禦、媒體安全、AI key 保護
- ✓ SR-2：資源上限、資訊衛生、列印管線硬化、mXSS 修復

**文件準備** ✓：
- ✓ 使用者 README 完全重寫（產品定位、快速開始、流程說明、常見問題）
- ✓ 工程 STATUS/ROADMAP/DECISIONS 與代碼一致

---

---

## 當前階段

**SR-2：資源上限、資訊衛生與列印安全（本機應用）** ← **COMPLETED**

完成時間：2026-10-10  
Commit：`feat: sr-2 resource limits, caching hygiene, and print pipeline hardening`（本地，未 push）
報告：`docs/engineering/SECURITY-AUDIT.md`（新增「SR-2 修復狀態」節）

完成內容：
- ✓ **F4 資源上限**：`shop/limits.py` 單一事實來源＋config 可覆寫（body 32 MiB、單檔 24 MiB、每請求 20 檔、圖片 50 MP、列印光柵 60 MP、AI 10 次/分、Template 1 MB）；`BodySizeLimitMiddleware`（純 ASGI；Content-Length 直拒＋chunked 逐塊累計）413 於路由前；上傳邊讀邊檢查、先前成功檔案保留；JPEG/PNG 零解碼像素判讀；analyze＋settings 測試共用滑動視窗（429＋Retry-After）；列印尺寸在啟動瀏覽器前先擋
- ✓ **F7 資訊衛生**：`/docs`、`/openapi.json`、`/redoc` 預設 404（`enable_docs` 明示開啟）；API `Cache-Control: no-store`、照片 `private, max-age`、靜態資產維持快取；`ConfigError` 對外通用化（完整原因只進伺服器 console）；404 不回 DATA_ROOT 路徑
- ✓ **F8 列印管線**：重驗發現**兩個實測 mXSS**（`<!-->` 立即結束註解、實體編碼標記解碼後原樣輸出）——renderer 改「重新序列化」：註解丟棄、文字 escape（`<style>` raw text 除外）、屬性 allowlist（`on*` 不輸出）、渲染前重新驗證；validator 加嚴（註解含 `<`/`>` 拒絕）；列印照片 inline 只收 raster MIME；**sandbox 預設保留**（實測新版 headless 不需 `--no-sandbox`；受限環境 `ITEMTRACE_PRINT_NO_SANDBOX=1` 明示退回）；未採用會壞 `--print-to-pdf` 的 `--blink-settings=scriptEnabled=false`（實測證據在稽核報告）
- ✓ 驗證：`tests/test_security_sr2.py` 30 測試（含**真實 Chromium canary PDF**：`MARKER-OK` 留存、`SCRIPT-RAN` 不存在）；SR-1 保護全數重驗通過（17 安全測試＋完整套件）
- ✓ 測試：+36（SR-2 30＋config 文件參數化 6）；全 1049 通過；未刪除／跳過／弱化既有測試（3 個既有契約測試依 SR-2 政策更新並強化）
- ✓ 零 schema migration、無登入系統、未動 Phase 3 功能；殘餘限制（單行程節流、列印瀏覽器 JS 引擎仍啟用）已誠實文件化

### SR-1 安全修復（前序；已完成）

完成時間：2026-10-10  
Commit：`feat: sr-1 host/origin guard, key forwarding fix, lan opt-in, media hardening`（本地，未 push）
報告：`docs/engineering/SECURITY-AUDIT.md`（新增「SR-1 修復狀態」節）

完成內容：
- ✓ **F1／F3**：`shop/security.py` Host 白名單（loopback 全形式＋`server_host`＋config `allowed_hosts`）＋Origin 驗證（host／埠一致、`null` 拒絕）＋變更類一律要求 `X-Requested-With: ItemTrace`；`web/core/api.js`、adapter、驗證工具同步；未通過在路由前 403
- ✓ **F2**：`/api/settings/ai/test` 已存 key 只送往**已知 preset**；自訂 URL 必須帶臨時 key（否則 400）——canary 實測：拒絕對照組零外送、臨時 key 流程只送臨時 key
- ✓ **F5**：預設 loopback（實測監聽 127.0.0.1）；非 loopback 需 `"allow_lan": true` —— 現值 0.0.0.0 下 `python serve.py` **拒絕啟動 exit 2**＋明確指示；LAN 模式有警語＋README 信任模型
- ✓ **F6**：`escapeHtml` 全面套用（home／capture／detail／router）；移除 inline `onerror`/`onclick`（CSP 相容＋失敗縮圖改事件監聽）；回應加 nosniff／Referrer-Policy／HTML CSP／frame 保護；`/files` 非圖片→octet-stream＋attachment＋`default-src 'none'; sandbox`
- ✓ 驗證：**修復後重演原攻擊**（socket 級隔離實例）：evil Host 200→403；無標頭 POST→403；evil Origin→403；canary 外送→400＋零外送；evil.html text/html→attachment；有效綁定→127.0.0.1；瀏覽器 E2E：payload 全數純文字、`window.__xss` 未定義、0 console errors、保存流程（含新標頭）完整可用
- ✓ 測試：+19（`tests/test_security.py` 17＋config 文件參數化 2）；全 1013 通過；未刪除／跳過／弱化既有測試（1 個既有 settings 測試依新規則更新）
- ✓ 零 schema migration、無登入系統、未動 F4／F7／F8（依 SR-1 範圍）

### Phase 2C-D 撤銷語義（實作即規格）

| 情境 | 結果 |
|---|---|
| 自動套用後無任何變更 | 復原 200：還原前值、建議 rejected、寫回 actor=user（該欄位之後不再自動） |
| 使用者改過同欄位（含改掉又改回） | **409**：值/建議狀態/事件全部不動；UI 逐項列「未復原」欄位 |
| 被較新的自動套用取代 | 舊的 409；最新那筆（未被動過）仍可復原 |
| attributes 其他鍵被編輯 | 不影響（僅同鍵變更才擋） |
| 批次 undo | 每欄位獨立；成功者還原、過期者維持現值 |

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
- Phase 2C-C：自主性 Live 驗證（`5a4c792`；報告 AI-AUTONOMY-VALIDATION.md）
- Phase 2C-D：撤銷安全、描述與衝突處理（`79eaecc`）
- Security Audit 1：桌面應用唯讀安全稽核（`3e002d2`；F1–F8 報告）
- SR-1：安全修復 F1/F2/F3/F5/F6（`24d1909`；Host／Origin／標頭、key 不轉送、LAN opt-in、媒體硬化）

---

## 測試基線

| 項目 | 數值 | 備註 |
|---|---|---|
| 測試檔案數 | 40 | conftest + 39 test_*.py（SR-2 新增 test_security_sr2.py） |
| 總測試數 | 1049 | 全 pytest 計數（SR-2 +36：安全 30＋config 文件參數化 6） |
| 通過 | 1049 ✓ | 100% pass rate |
| 失敗 | 0 | 零失敗 |
| 跳過 | 0 | 無跳過（本機有 Chromium／PyMuPDF，列印與 canary 測試皆實跑） |
| 覆蓋率 | 未測 | 建議後續補充 |

**測試框架**：pytest（可選 pytest-cov 補充覆蓋率）

**主要測試分類**：
- API 端點：test_api.py (82), test_phase8a_api.py (35), test_settings_api.py (43) 等
- 資料庫 & Repo：test_repo_*.py (13-23 each), test_db_transactions.py (8)
- AI & 分析：test_ai_*.py (15-78), test_analyze_item.py (78)
- 前端與 UI：test_capture_ui.py (6), test_inbox_ui.py (35)
- 列印：test_print.py (31), test_print_settings_api.py (20)
- **V3 核心驗收**：test_v3_core_slice.py (15) —— 原始 5 情境 + Phase 1B-A 5 項 + Phase 2A 1 項 + Phase 2B 2 項 + Phase 2C-B 1 項 + Phase 2C-D 1 項
- **評測 harness**：test_evaluate_models.py (7)、test_validate_autonomy_live.py (2) —— 離線守門（不碰網路）
- **安全（SR-1）**：test_security.py (17) —— Host／Origin／自訂標頭、key 不轉送（canary＋接收器）、綁定 opt-in、媒體標頭、CSP/escaping 靜態守門
- **安全（SR-2）**：test_security_sr2.py (30) —— body／單檔／檔數／像素／列印尺寸上限、AI 節流、docs 開關、快取政策、錯誤訊息去路徑化、註解／實體 mXSS、render-time 驗證、sandbox 命令、raster MIME、真實 Chromium canary PDF

**最近運行**：2026-10-10，`pytest -q` → collected=1049（逐檔加總），failures=0，exit=0

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 994 個 pytest 全通過，V3 core slice test 驗收 |
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
- ✓ 自主性驗證與殘餘缺口（Phase 2C-C：Live 實測、報告、fixture／錄製） — **Evaluated, Committed（5a4c792）, Not Pushed**
- ✓ 撤銷安全、描述性理解與衝突處理（Phase 2C-D） — **Implemented, Tested, Committed（79eaecc）, Not Pushed**
- ✓ 桌面應用安全稽核（Security Audit 1；唯讀） — **Audited, Committed（3e002d2）, Not Pushed**（F1–F8 見 SECURITY-AUDIT.md）
- ✓ SR-1 安全修復（Host/Origin＋標頭、key 不轉送、LAN opt-in、媒體硬化、前端 escaping） — **Implemented, Tested, Committed（本階段）, Not Pushed**

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

### 立即待做（Phase 3：垃圾桶與資料生命週期）
- 依 `ROADMAP.md` Phase 3：垃圾桶 UI／30 天保留／永久刪除（明確使用者意圖、可稽核）
- 收尾選項（可穿插）：R 型跨照片身分的下一輪評測；屬性逐鍵來源標籤；Phase 1B-B

### 安全後續（F4／F7／F8）— SR-2 已完成
- F4：body／單檔／檔數／像素／列印尺寸上限、analyze 節流（單行程；多 worker 限制已文件化）
- F7：`/docs` 預設關閉（`enable_docs`）、錯誤訊息去路徑化、`Cache-Control: private`／`no-store`
- F8：列印輸出重新序列化（註解丟棄＋文字 escape＋屬性白名單＋render 前重驗）；sandbox 預設保留
- 殘餘（已知）：列印瀏覽器 JS 引擎仍啟用（防線在「輸出不含可執行內容」）；單行程節流重啟歸零；未對 HTML 解析器差異做 fuzzing

### 短期（Phase 2–3）
- Phase 2：AI Contract 2.0 —— **完成（2A/2B/2C-A/2C-B/2C-C/2C-D）**
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
| `attribute:description` 未被模型自發產生 | — | 已解決 | Phase 2C-D：prompt 上線；C1 Live 回評已產生真描述（無品牌幻覺） |
| 過期 undo 可覆寫後續編輯 | — | 已解決 | Phase 2C-D：值不符或有中間變更 → 409 零副作用；批次逐欄位＋UI 逐項說明 |
| 跨照片身分「沉默擇一」 | 中 | 部分解決（2C-D） | C6（無上下文）：兩身分都輸出→衝突 ✓；R 型（有上下文）模型仍可能擇一 → 限制已記錄（AI-AUTONOMY-VALIDATION §2C-D） |
| 【安全】F1 DNS rebinding／Host 未驗證 | High | **已解決（SR-1）** | `shop/security.py` Host 白名單＋Origin 驗證；實測 evil Host→403 |
| 【安全】F2 API key 可被轉送攻擊者 URL | High | **已解決（SR-1）** | 已存 key 只送往 preset；自訂 URL 需臨時 key（canary 實測零外送） |
| 【安全】F5 現值綁 0.0.0.0 | High（as-configured） | **已解決（SR-1）** | 非 loopback 需 `allow_lan: true`；實測 0.0.0.0 未 opt-in → serve.py 拒啟 exit 2 |
| 【安全】F3 CSRF | Medium | **已解決（SR-1）** | 變更類一律要求 `X-Requested-With: ItemTrace`＋Origin 驗證；實測無標頭→403 |
| 【安全】F6 前端 XSS／媒體 | Medium | **已解決（SR-1）** | escapeHtml 全面＋CSP/nosniff＋非圖片附件化；瀏覽器 E2E 驗證 |
| 【安全】F4 資源上限 | Medium | **已解決（SR-2）** | body/單檔/檔數/像素/列印尺寸上限＋AI 節流；413/400/429；殘餘：單行程計數器（已文件化） |
| 【安全】F7 資訊衛生 | Low | **已解決（SR-2）** | `/docs` 預設 404（`enable_docs` 開啟）；API `no-store`／照片 `private`；ConfigError 去路徑化 |
| 【安全】F8 列印管線 | Low（重驗後為可執行 mXSS，Medium） | **已緩解（SR-2）** | 實測兩個 mXSS 已修（renderer 重新序列化＋render 前重驗）；sandbox 預設保留；殘餘：瀏覽器 JS 引擎仍啟用（未 fuzz 全解析器差異） |
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

## Phase 2C-C 變更清單（commit `5a4c792`，前次）

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

## Phase 2C-D 變更清單（commit `79eaecc`，前次）

| 檔案 | 變更 |
|---|---|
| `shop/repo.py` | `undo_auto_suggestion` 過期防護（現值比對＋`_has_intervening_change` 逐鍵事件檢查；不符 ConflictError→409、零副作用） |
| `shop/ai_client.py` | PROMPT：描述規則（看得見→描述性 name＋attribute:description；看見 vs「看起來像」）＋跨照片身分聲明（不同值分別輸出，不默默擇一） |
| `web/views/record-detail.js` | `buildRevisionDetails`（banner 顯示前→後／新增）；`undoSuggestions` 逐欄位結果（409→未復原欄位清單） |
| `web/core/api.js` | `listEvents` |
| `web/i18n/zh-TW.js`, `web/i18n/en.js` | +3 keys × 2（revisionChanged／revisionFilled／undoStale）；undoFailed 改為逐欄位文案 |
| `tools/validate_autonomy_live.py` | 新增：可重複的 Live 管線驗證入口（--allow-live 守門、合成圖限定、呼叫上限、資料目錄防誤刪） |
| `tools/evaluate_models.py` | 新增期望 kind：`has_field`、`field_has_multiple_values` |
| `tools/eval_fixtures/scenarios.json` | C1 加入 description 期望；新增 C6（兩張身分標籤） |
| `tools/eval_fixtures/recorded/` | C1 錄製更新（新 prompt）、新增 C6 錄製；summary 記錄第三次 run |
| `tests/test_ai_analyze.py` | +8（過期 undo×6、跨照片衝突×2） |
| `tests/test_v3_core_slice.py` | +1（2C-D 前端接線靜態檢查） |
| `tests/test_validate_autonomy_live.py` | 新增：驅動安全守門×2（不碰網路） |
| `docs/engineering/` | STATUS／ROADMAP／DECISIONS（D8）／AI-AUTONOMY-VALIDATION（2C-D 補充） |

**未變更**：schema（零 migration）、API 契約形狀、media 結構、capture/home/settings view；未引入欄位鎖定子系統。

---

## Security Audit 1 變更清單（commit `3e002d2`，前次；唯讀稽核）

| 檔案 | 變更 |
|---|---|
| `docs/engineering/SECURITY-AUDIT.md` | 新增：稽核報告（F1–F8、正面清單、情境判定、SR-1 建議、限制、附錄） |
| `docs/engineering/STATUS.md`, `AGENTS.md` | 稽核結果與修復優先級校準 |

**未變更**：產品程式碼（shop/、web/、tools/）、`config.json`、依賴、schema、測試——**全部零修改**；稽核僅使用暫存資料根（已刪除）。

---

## SR-1 變更清單（前次 commit `24d1909`）

| 檔案 | 變更 |
|---|---|
| `shop/security.py` | 新增：Host 白名單（loopback 全形式＋`server_host`＋`allowed_hosts`）、Origin 驗證、`X-Requested-With` 變更端點要求、`require_lan_opt_in`、APP_CSP |
| `shop/api.py` | create_app 安裝安全 middleware（Host/Origin/標頭＋回應 nosniff／Referrer-Policy／HTML CSP／frame 保護）；`_serve_file`→`_file_response`（非圖片 attachment/octet-stream＋嚴格 CSP） |
| `shop/config.py` | `allow_lan`（預設 false）＋`allowed_hosts` 欄位與讀取 |
| `serve.py` | LAN opt-in 守門（未設定拒啟 exit 2＋指示）＋區網模式警語 |
| `shop/settings.py` | F2：已存 key 只送往 preset；自訂 URL 需臨時 key |
| `web/core/dom.js` | 新增 `escapeHtml` |
| `web/core/api.js` | 所有請求帶 `X-Requested-With` |
| `web/views/{home,capture,record-detail}.js`、`web/core/router.js` | escaping 全面套用；inline `onerror`/`onclick` 移除（事件監聽；失敗縮圖 fallback） |
| `tools/analyze_item.py`、`tools/validate_autonomy_live.py` | 客戶端同步帶標頭 |
| `config.example.json`、`README.md` | 新設定欄位文件＋SR-1 安全說明 |
| `tests/test_security.py` | 新增 17 測試；`tests/conftest.py` 兩個 TestClient 建設加 base_url/標頭 |
| `tests/test_settings_api.py` | 1 個既有測試依新規則更新（自訂 URL 帶臨時 key） |
| `docs/engineering/SECURITY-AUDIT.md`、`STATUS.md`、`ROADMAP.md`、`DECISIONS.md`(D9)、`AGENTS.md` | 修復狀態與政策 |

**未變更**：schema（零 migration）、`config.json`（**使用者現值 0.0.0.0 未動**——serve.py 會先拒啟並要求明示 opt-in）、無登入系統、F4／F7／F8 未動。

---

## SR-2 變更清單（本階段 commit）

| 檔案 | 變更 |
|---|---|
| `shop/limits.py` | 新增：上限常數（body／單檔／檔數／像素／列印光柵／AI 節流）、`image_dimensions`（JPEG/PNG 零解碼）、`check_image_pixels`／`check_print_pixels`、`SlidingWindowLimiter`、`read_upload_limited` |
| `shop/errors.py` | `PayloadTooLargeError`（→413） |
| `shop/config.py` | 新欄位：`enable_docs`、`max_request_bytes`、`max_upload_bytes`、`max_upload_files`、`max_image_pixels`、`analyze_per_minute`（含 DEFAULTS／load()） |
| `shop/api.py` | `BodySizeLimitMiddleware`（純 ASGI；CL＋chunked）；docs 網址依 `enable_docs`（關閉時文件路徑 404 不回退 SPA）；API `no-store`；上傳端點檔數／單檔／像素檢查；analyze 過節流；`_file_response` 改 `private`；`ConfigError` 對外通用化（完整內容進 stderr） |
| `shop/security.py` | `enforce_ai_quota`（analyze 與 settings 測試共用；429＋Retry-After） |
| `shop/settings.py` | `/api/settings/ai/test` 過節流 |
| `shop/template_renderer.py` | 渲染前 `validate_template`；註解丟棄；文字資料重新 HTML escape（`<style>` raw text 例外）；屬性 allowlist（`on*` 不再輸出） |
| `shop/template_validator.py` | 註解含 `<`／`>` 拒絕；Template 1 MB 上限 |
| `shop/print_backend.py` | `build_browser_command`（預設無 `--no-sandbox`；`ITEMTRACE_PRINT_NO_SANDBOX=1` 才加）；列印光柵上限（啟動瀏覽器前＋量測後）；`inline_photos` 只接受 raster MIME |
| `serve.py` | 啟動訊息依 `enable_docs` 顯示（預設不指向 `/docs`） |
| `config.example.json` | 新欄位樣板（6 個） |
| `README.md` | 設定表新增欄位＋「資源上限與輸出衛生（SR-2）」節 |
| `tests/test_security_sr2.py` | 新增 30 測試（F4／F7／F8；含真實 Chromium canary PDF） |
| `tests/test_api.py`、`tests/test_settings_api.py` | `/docs`／`/openapi.json` 契約測試改「預設關閉、`enable_docs` 開啟」（覆蓋不減） |
| `tests/test_v3_core_slice.py` | 照片 `Cache-Control` 斷言 public → private（同一斷言強度） |
| `tests/test_phase10_docs.py` | stdlib allowlist 加 `sys`（api.py 需要；第三方偵測不變） |
| `docs/engineering/SECURITY-AUDIT.md`、`STATUS.md`、`ROADMAP.md`、`DECISIONS.md`(D10)、`AGENTS.md` | SR-2 狀態與決策 |

**未變更**：schema（零 migration）、`config.json`（使用者現值未動）、無登入系統、Phase 3 功能未動、`shop/repo.py` 與 DB 層未動。

---

## 本地與遠端同步狀態

| 項 | 狀態 |
|---|---|
| Branch | main |
| Ahead/Behind | 14 ahead, 0 behind（未 push；本階段 commit 後） |
| Uncommitted Changes | 0（本階段變更全數進入獨立 commit） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda`、`98edc0c`、`ef85450`、`15f2e9b`、`22b0c22`、`dda8b61`、`7927faf`、`5a4c792`、`79eaecc`、`3e002d2`、`24d1909` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 3：垃圾桶與資料生命週期（依 ROADMAP）
檢查清單：
- [ ] 垃圾桶頁面（void 紀錄）＋還原
- [ ] 30 天保留與永久刪除（明確使用者意圖、可稽核；原照片保護規則先定案）
- [ ] 補充測試、全測試通過

（收尾選項可穿插：R 型跨照片身分的下一輪 prompt 評測；屬性逐鍵來源標籤；Phase 1B-B。）

### AI-Native 架構研究對照（`docs/engineering/AI-NATIVE-ARCHITECTURE.md`）
- ✓ S1（提案命名空間）→ Phase 2B：`attribute:<key>` 受驗證契約
- ✓ S2（修訂語意＋可靠性修正）→ Phase 2A
- ◐ S3（前端呈現/可溯性）→ 審閱＋屬性顯示＋失敗重試＋自動更新 banner（含前後值/撤銷逐項說明）完成；逐鍵來源標籤後續
- ✓ S4（模型評測 harness）→ Phase 2C-A（評測＋政策）＋2C-C（Live 驗證）＋2C-D（回評；描述與 C6 通過，R 型限制記錄）
- ✓ S5（受控自動套用）→ Phase 2C-B：決定性政策、可回復、衝突升級；2C-C 抓到 undo 過期缺陷；2C-D 修補（409 防護）
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
- **2026-10-10**：Phase 2C-D 完成——過期 undo 防護（409 零副作用＋逐欄位批次＋UI 逐項說明）；描述與跨照片身分 prompt 上線；banner 修訂前後值；可重複 Live 驗證入口；Live 回評：C1 描述 ✓、C6 雙身分 ✓、P/S/F ✓、R 型仍可能擇一（限制記錄）；測試基線 983 → 994
- **2026-10-10**：Security Audit 1 完成（唯讀）——F1 DNS rebinding／Host 未驗證、F2 API key 轉送、F3 CSRF、F4 資源上限、F5 0.0.0.0 綁定、F6 前端 XSS、F7/F8 縱深；正面清單（穿越防護、秘密衛生、參數化 SQL 等）；情境判定與 SR-1 修復建議；測試基線不變 994（未改任何程式碼／設定／測試）
- **2026-10-10**：SR-1 完成——Host／Origin／`X-Requested-With` 守門（F1/F3）、已存 key 只送 preset＋自訂 URL 需臨時 key（F2）、LAN opt-in＋綁定實測 loopback（F5）、escaping＋CSP／nosniff＋媒體附件化＋移除 inline 處理器（F6）；修復後重演原攻擊全數攔下；測試基線 994 → 1013
- **2026-10-10**：SR-2 完成——資源上限（body／單檔／檔數／像素／列印光柵；413/400；先前成功檔案保留）＋AI 節流（429＋Retry-After）；`/docs` 預設關閉、API `no-store`／照片 `private`、錯誤訊息去路徑化；列印管線重新序列化並實測修復兩個 mXSS（`<!-->` 註解、實體編碼標記）＋sandbox 預設保留；測試基線 1013 → 1049（+36）
