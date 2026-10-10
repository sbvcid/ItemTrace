# ItemTrace Engineering Decisions

重要工程決策與其背景、選項、決定、取捨記錄。

---

## D1. AI Provider 與 ItemTrace AI Contract 的分離

### 背景
ItemTrace 的 AI 能力依賴外部 Vision 模型（Google Gemini / OpenRouter / Custom），但系統不應被特定廠商綁定。需要清晰的介面合約，使 AI 廠商可替換、可離線、可未來升級。

### 選項
1. **直接依賴 OpenAI API** —— 簡單，但被 OpenAI 綁定
2. **建立 ItemTrace AI Contract** —— 抽象層次高，廠商可替換 ✓
3. **自訂模型微調** —— 維護成本高，短期不可行

### 決定
**採用 Option 2：ItemTrace AI Contract**
- `shop/ai_client.py` 定義統一呼叫介面
- 支援 OpenAI / Gemini / OpenRouter / Custom 端點
- Suggestions 結構化標準：`[{"field": "...", "value": "...", "confidence": ..., "source_photo_index": ...}]`
- 配置存在 `tools/ai_config.local.json`（不版本控制，安全隔離密鑰）

### 取捨
- **優勢**：廠商無鎖定，使用者可選擇成本/品質平衡
- **成本**：需維護多個廠商的 API 轉接層
- **風險**：各廠商 API 變更時需更新適配

### 驗證方式
- `tests/test_ai_provider_errors.py` 驗證錯誤處理
- `tests/test_ai_config.py` 驗證配置切換
- 新增廠商時補充適配測試

**狀態**：✓ Accepted（已實作於 shop/ai_client.py）

---

## D2. 新欄位、動態屬性與使用者備註的儲存策略

### 背景
ItemTrace 既要捕捉 AI 自動填入的結構化欄位（品名、型號、序號），也要支援使用者的自由備註（「換了副廠線材」「防潮箱 C-02」）。簡單的單一文本欄位無法支援兩者的獨立維護與搜尋。

### 選項
1. **統一文本欄位** —— 簡單但無法區分 AI vs 人工，搜尋低效
2. **拆成多個固定欄位** —— AI 資料集中，使用者備註分散，難以擴展
3. **JSON 動態屬性 + 固定欄位** —— 結構清晰，易於擴展 ✓

### 決定
**採用 Option 3：JSON 動態屬性 + 固定欄位分離**
- **固定欄位**（AI 與 user 都可寫，但語意明確）：
  - `items.name`、`brand`、`model`、`category`、`condition` —— 由 AI 初始填充，user 可編輯
  - 搜尋索引涵蓋這些欄位
  
- **JSON 屬性** (`items.attributes` JSON 物件）：
  - `purchase_date`、`warranty_until`、`location`、`notes`
  - 動態擴展空間，使用者自由維護
  - 搜尋時可選索引

- **區分來源**：
  - Suggestions 表記錄 AI 提案源頭
  - Events 表記錄人工修改
  - UI 清楚標示「✨ AI 建議」vs「📝 你的備忘」

### 取捨
- **優勢**：結構 + 自由度平衡，易於搜尋與擴展
- **成本**：需設計清晰的欄位歸類與 UI 標示
- **風險**：重複邏輯（某欄位同時出現在 fixed + attributes）需嚴格約束

### 遷移策略
- Phase 1：新增 `items.attributes` JSON 欄位（向下相容）
- 既有資料無 attributes 時視作 `{}`
- 不強制遷移已有數據

### 驗證方式
- Phase 1 測試：編輯固定欄位 vs attributes，各自獨立
- 搜尋測試：attributes 內容可被檢索

**狀態**：✓ Accepted for Phase 1（設計確定，實作待進行）

---

## D3. SQLite 全文索引與中文搜尋策略

### 背景
ItemTrace 需要支援毫秒級搜尋（< 50ms for 1000+ 紀錄），部分字串匹配（型號「4070」→「RTX4070」），以及繁簡體互搜。SQLite FTS5 是輕量方案，但中文分詞與繁簡需特殊處理。

### 選項
1. **無全文索引，逐行 LIKE 查詢** —— 簡單但 O(n) 低效，超過 100 紀錄即無法接受
2. **SQLite FTS5 + 簡單中文分詞** —— 輕量，需手動處理繁簡 ✓
3. **遷移至 Elasticsearch / Meilisearch** —— 功能完善，但引入外部依賴，違反 local-first 原則
4. **自訂 Porter Stemmer for Chinese** —— 維護成本高

### 決定
**採用 Option 2：SQLite FTS5 + 手動繁簡對照表**
- Phase 4 建立 FTS5 虛擬表 `items_fts5`（品名、品牌、型號、分類、備忘、識別碼）
- Prefix query 支援部分字串（e.g., `4070*`）
- 繁簡互搜：
  - 建立簡單繁簡映射表或使用開源庫（如 OpenCC）
  - 搜尋時同時查詢原詞 + 轉換後異體
  - 結果合併去重

### 取捨
- **優勢**：零外部依賴，符合 local-first，效能足夠 1000+ 紀錄
- **成本**：需處理中文分詞與繁簡轉換
- **風險**：繁簡對照可能有邊界情況遺漏

### 索引維護
- **增量更新**：觸發器自動維護 FTS5 索引
- **完整重建**：`POST /api/admin/search-index/rebuild` 維護用端點
- **最佳化**：`POST /api/admin/search-index/optimize` 定期執行

### 驗證方式
- Phase 4 測試：搜尋性能 < 50ms（1000 紀錄）
- 部分字串匹配準確度 > 95%
- 繁簡互搜：繁体「電腦」找到簡体「电脑」紀錄

**狀態**：Proposed（設計待確定，部分字數與繁簡對照方案開放）

---

## D4. 繁簡轉換與原始資料不改寫原則

### 背景
支援繁簡互搜時，需要決定：搜尋時即時轉換 vs 預先轉換存儲？後者違反「原始資料神聖」原則，前者的效能取決於轉換演算法。

### 選項
1. **存儲時轉換備份** —— 違反原始資料原則，資料表膨脹
2. **搜尋時轉換** —— 保持原始資料完整，效能依轉換庫 ✓
3. **建立轉換索引表** —— 折衷方案，需維護同步

### 決定
**採用 Option 2：搜尋時動態轉換**
- 所有用戶輸入資料（品名、備忘等）**原樣保存**，不轉換
- 搜尋時：用戶輸入 → 繁簡轉換 → 查詢 FTS5 （同時查詢原詞）
- 轉換庫選擇：OpenCC（C++) 或 python-opencc（有 Python 綁定）

### 取捨
- **優勢**：原始資料完整，日後支援其他轉換（簡 → 繁 → 粵語 等）無需重構資料
- **成本**：每次搜尋需轉換，增加 CPU 負擔（但通常 < 1ms）
- **風險**：轉換庫失效 / 更新時搜尋結果可能變化

### 驗證方式
- 搜尋轉換性能測試：單次轉換耗時 < 1ms
- 資料驗證：隨機抽查 100 筆紀錄，確認原始資料未被修改

**狀態**：Proposed（Phase 4 實作時最終確定）

---

## D5. 垃圾桶與永久刪除的資料生命週期

### 背景
刪除紀錄涉及資料安全與使用者體驗。需要平衡：使用者意外刪除的後悔機制 vs 確保資料最終清理。

### 選項
1. **立即永久刪除** —— 簡單但無法恢復，風險高
2. **軟刪除 (deleted_at 標記) + 30 天保留** —— 標準做法，給使用者反悔空間 ✓
3. **無限期保留** —— 安全但垃圾堆積
4. **加密而非刪除** —— 複雜，維護成本高

### 決定
**採用 Option 2：軟刪除 + 30 天保留 + 永久刪除**
- **T+0**：用戶點「刪除」→ `items.deleted_at = NOW()`，首頁隱藏但垃圾桶可見
- **T+1 到 T+29**：垃圾桶顯示「剩餘 N 天」，一鍵恢復 (`deleted_at = NULL`)
- **T+30**：系統背景 job 標記為「永久刪除候選」
- **永久刪除驗證**：刪除前確認照片檔案 + 資料庫紀錄 + 搜尋索引均可完全移除

### 資料安全驗證清單
1. 資料庫紀錄刪除 （transaction 保護）
2. 照片檔案移除 （files/{item_id}/ 整棵樹）
3. 搜尋索引清理 （FTS5 虛擬表）
4. 刪除日誌記錄 （含 item_id、file count、timestamp）
5. 失敗時回滾 （所有或無，不可部分刪除）

### 取捨
- **優勢**：使用者有反悔空間，同時最終清理資料
- **成本**：需實作後台 cleanup job + 驗證機制
- **風險**：cleanup job 失敗導致垃圾堆積；誤刪長期無法恢復（30 天後）

### 驗證方式
- Phase 2 測試：刪除 → 垃圾桶可見 → 還原 → 首頁可見
- 模擬 30 天流逝，cleanup job 執行
- 驗證永久刪除：查詢資料庫、檔案系統、索引，確認完全無跡

**狀態**：✓ Accepted for Phase 2（設計確定，實作待進行）

---

## D6. 原始照片、衍生預覽、備份的邊界

### 背景
ItemTrace 強調原始紀錄不可破壞，但同時需要快速預覽與備份。需要定義哪些檔案必保留、哪些可重生。

### 檔案分類
1. **原始照片** (`files/{item_id}/original/`) —— 神聖，永不覆寫、永不壓縮
2. **衍生預覽** (`files/{item_id}/derived/`) —— 可重生，用於 UI 快速顯示
3. **備份** (`backups/shop-{timestamp}/`) —— 完整快照，用於災難恢復

### 決定
- **原始照片**：byte-for-byte 保存上傳檔案，不修改、不轉檔、不重新壓縮
  - 即使是 HEIC / WebP 等「非標準」格式，也原樣保留
  - 用戶下載時提供原檔

- **衍生預覽**：
  - 縮圖 1024×768 JPEG 用於首頁卡片
  - 大圖 2048×1536 JPEG 用於詳細頁
  - 可刪除重生，不影響原始資料
  
- **備份**：
  - `python shopctl.py backup` 使用 SQLite `Connection.backup()` + `shutil.copytree`
  - 保留最近 30 份快照（滾動保留）
  - 備份內容完全自足，整個資料夾複製回去即還原

### 取捨
- **優勢**：原始資料與使用者體驗完全解耦
- **成本**：磁碟空間（衍生預覽 + 多份備份）
- **風險**：衍生預覽與原始不同步時使用者看不到新照片

### 驗證方式
- Phase 1+ 測試：上傳各種格式相片，下載後驗證 byte-for-byte 相同
- 備份還原測試：備份 → 刪除 → 還原 → 驗證資料完整

**狀態**：✓ Accepted（已實作原始照片保護）

---

## D7. 未來 Windows 封裝和使用者資料位置

### 背景
ItemTrace 當前是命令行啟動的純 Web 應用。未來封裝為 Windows Store 應用或 EXE 時，需要決定：資料存放位置、安裝路徑、更新機制。

### 選項
1. **固定位置** （例 `C:\ItemTrace`）—— 簡單但不尊重使用者偏好
2. **%APPDATA% 位置** —— 標準 Windows 做法 ✓
3. **使用者自選位置** —— 尊重使用者但複雜度高

### 決定
**採用 Option 2：%APPDATA% 位置（Phase 7 決定最終細節）**
- 資料默認位置：`%APPDATA%\ItemTrace\` （例 `C:\Users\username\AppData\Roaming\ItemTrace\`）
- 可選：提供「選擇位置」嚮導，讓使用者指定 USB 隨身碟或網路驅動器
- 當前本地開發：仍使用 `config.json` 指定 `data_root`

### 取捨
- **優勢**：符合 Windows 使用者期望，支援多使用者
- **成本**：需調整 path 解析邏輯，測試多個路徑場景
- **風險**：某些網路驅動器可能不支援 WAL 模式

### 驗證方式
- Phase 7 測試：在 %APPDATA% 位置啟動、建檔、搜尋，驗證功能完整

**狀態**：Proposed（Phase 7 實作時最終確定）

---

## D8. AI 自動更新的邊界與復原安全（Phase 2C-B/C/D）

### 背景
AI 會隨新證據自動更新判讀（描述、屬性、身分修訂）。若處理不當，自動更新可能覆蓋使用者意圖、隱藏矛盾證據，或讓「復原」反過來破壞後續編輯。2C-C 的 Live 實測即抓到「過期 undo 覆寫後續編輯」缺陷。

### 決定
1. **自動套用分層**（2C-B）：描述性 `attribute:*` 自動、空身分自動、先前由系統自動填入的身分可自動修訂；`identifier:*`／category／condition／notes 永遠人工確認；購買資訊僅在「同一張照片同時提供身分資訊」時自動，否則升級衝突。
2. **撤銷安全**（2C-D）：undo 只在「現值＝該次自動套用的值」且「套用後沒有任何改到同一欄位的事件（值改掉又改回亦算）」時執行；不符回 409、**零副作用**。批次逐欄位獨立，UI 逐項列出「未復原」欄位。
3. **判讀提示**（2C-D）：看得見但認不出身分時，用描述性 `name`＋`attribute:description`（先寫看見的，推測用「看起來像」）；不同照片支持不同身分時分別輸出（多值），由系統的重複值偵測升級衝突，不默默擇一。
4. 以上全部**不依賴模型自報信心**（2C-A 實測：0.90~1.00 無鑑別力）。

### 取捨
- 優勢：可回復、可稽核、保護使用者意圖；契約與政策皆可離線回歸（recorded replay）。
- 成本：模型在「有上下文＋兩張身分標籤」時仍可能擇一（R 型）；目前由 auto 修訂 banner＋可復原承擔風險。
- 風險：prompt 無法保證模型遵守分列規則 → 以評測（C6）與政策側重複值偵測兜底；不採品牌特例規則。

### 驗證方式
- `tests/test_ai_analyze.py`（過期 undo×6、跨照片衝突×2）、`tests/test_v3_core_slice.py`（靜態接線）。
- `tools/evaluate_models.py --offline`（10 情境契約回歸）；`tools/validate_autonomy_live.py`（Live 行程，僅合成圖）。

**狀態**：✓ Accepted（2C-B/C/D 實作與驗證；R 型限制記錄於 AI-AUTONOMY-VALIDATION.md）

---

## D9. SR-1 安全基線（Host／Origin／標頭、key 外送、綁定、媒體輸出）（2026-10-10）

### 背景
Security Audit 1 確認（隔離實測）：F1 DNS rebinding（無 Host/Origin 驗證，loopback 綁定亦可被任意網頁全控）、F2 已存 API key 可被轉送到呼叫者指定的 base_url、F3 無 body 端點可 CSRF、F5 實值綁 0.0.0.0、F6 儲存型 XSS 與媒體主動內容原樣供檔。

### 決定
1. **路由前守門**：Host ∈ 白名單（loopback 全形式＋`server_host`＋config `allowed_hosts`）；有 Origin 時必須同源（host∈白名單、埠一致、`null` 拒絕）。
2. **變更類自訂標頭**：POST／PATCH／PUT／DELETE 一律要求 `X-Requested-With: ItemTrace`（瀏覽器跨站帶不了自訂標頭；前端與工具統一附加）。缺少 Origin **不**單獨構成信任。
3. **key 外送邊界**：`/api/settings/ai/test` 的已存 key 只送往已知 provider preset；自訂 base URL 必須由該次請求帶臨時 key。
4. **綁定 opt-in**：預設 loopback；非 loopback 需 config `"allow_lan": true`（未設定拒啟）。信任區網模型文件化，且明示**不能取代認證**。
5. **輸出安全**：前端 `escapeHtml` 全面套用；回應 `nosniff`／`Referrer-Policy`／HTML CSP（`script-src 'self'`、`frame-ancestors 'none'`）；`/files` 非圖片 → `attachment`/`octet-stream`＋`default-src 'none'; sandbox`；禁 inline 事件處理器。

### 取捨
- 手動 curl／腳本需多帶一個標頭；自訂 provider 測試需當次貼臨時 key——換得「瀏覽器不可被跨站利用」與「長期 key 不外流」。
- 不引入登入系統（維持 local-first 單人）；F4（資源上限）、F7/F8（縱深）保留後續。

### 驗證
- `tests/test_security.py`（17＋靜態守門）與 `test_settings_api.py` 更新；修復後以 socket 級隔離實例重演原攻擊全數攔下（canary 零外送、evil Host/Origin→403、非圖片附件化、綁定 loopback）；瀏覽器 E2E：payload 純文字、0 console errors、保存流程正常。

**狀態**：✓ Accepted（SR-1）

---

## D10. SR-2 資源上限、輸出衛生與列印管線硬化（2026-10-10）

### 背景
Security Audit 1 的 F4（資源上限）、F7（資訊衛生）、F8（列印管線）在 SR-2
逐一重驗後實作。F8 重驗時發現兩個**可實際執行 JS** 的 mXSS（見
SECURITY-AUDIT.md「SR-2」節）：立即結束註解（`<!-->`）與實體編碼標記
（`&lt;img …&gt;`）都能穿過存檔驗證、由 renderer 原樣重送進列印瀏覽器。

### 決定
1. **資源上限是明示的 config 欄位**（`shop/limits.py` 為單一事實來源）：
   body 32 MiB、單檔 24 MiB、每請求 20 檔、圖片 50 MP、列印光柵 60 MP、
   AI 每分鐘 10 次、Template 1 MB。超限回 413／400／429；**先前已成功
   的檔案保留**，不因後段失敗回滾。上傳端**不設型別白名單**（D6：證據
   原檔不可被拒收），安全處理放在輸出端（SR-1 附件化／CSP、SR-2
   inline MIME 白名單、像素上限）。
2. **body 上限用純 ASGI middleware**：有 Content-Length 直接拒；chunked
   逐塊累計，超限由 middleware 自己送 413（FastAPI 會把 body 讀取例外
   吞成 400，所以不能只丟例外）。
3. **像素防護零解碼優先**：JPEG（SOF）／PNG（IHDR）在上傳時讀檔頭判寬高；
   Pillow 只在 analyze 縮圖時作為其他格式的兜底。
4. **AI 節流是單行程滑動視窗**（不引入 Redis 等外部服務）；限制誠實
   文件化：多 worker 時為 N 倍、重啟歸零。
5. **列印輸出採「重新序列化」策略**：renderer 不再原樣轉貼模板——
   註解丟棄、文字 escape（`<style>` raw text 除外）、屬性 allowlist、
   render 前再驗一次。validator 同步加嚴（註解含 `<`／`>` 拒絕）。
6. **列印瀏覽器預設保留 sandbox**：實測本機新版 headless 不需
   `--no-sandbox`；受限環境用 `ITEMTRACE_PRINT_NO_SANDBOX=1` 明示退回。
   實測 `--blink-settings=scriptEnabled=false` 會讓 `--print-to-pdf` 失效，
   不採用；JS 的防線在 renderer 端（輸出不可能含可執行內容）。
7. **API 文件預設關閉**（`enable_docs` 開發選項）；API `no-store`、
   照片 `private`、靜態資產維持可快取；`ConfigError` 對外通用化、細節
   只進伺服器 console。

### 取捨
- 手動 curl／自訂工具在多檔上傳時會拿到 413／400 而非默默接受；換得
  「小檔大像素」與巨量 body 不會打爆記憶體。
- 模板作者若在註解裡用 `<`／`>`（例如 `<!-- a > b -->`）存檔會被拒——
  訊息明確，且此類註解在列印情境沒有功能價值。
- 節流不是分散式；以本專案「local-first、單一桌面實例」的定位，這是
  刻意取捨（文件已載明多 worker 的語義）。
- 列印 JS 引擎仍開著；我們選擇「不讓可執行內容抵達瀏覽器」而不是
  「關 JS」（後者在目前 Chromium 沒有可靠的 CLI 開關，實測會壞）。

### 驗證
- `tests/test_security_sr2.py`（30 測試）：body（CL＋chunked）、單檔／檔數／
  像素、列印尺寸上限、節流與視窗行為、docs 開關、快取政策、錯誤訊息
  去路徑化、註解／實體 mXSS、render-time 驗證、sandbox 命令契約、
  raster MIME 白名單、**真實 Chromium canary PDF**（無 `SCRIPT-RAN`）。
- 完整回歸見 `STATUS.md`；SR-1 測試全數保留。

**狀態**：✓ Accepted（SR-2）

---

## 開放問題

| 編號 | 問題 | 優先級 | 決策期限 |
|---|---|---|---|
| O1 | 首頁分類導航 vs 新紀錄置頂的優先級 | 中 | Phase 1 |
| O2 | 預定義分類清單（電腦零件、工具 等）| 中 | Phase 3 |
| O3 | 繁簡對照表來源（自建 vs OpenCC）| 低 | Phase 4 |
| O4 | 外觀比對模式的差異標註方式 | 低 | Phase 5 |
| O5 | AI evaluation harness 的標準與流程 | 低 | Phase 6 |

---

## 決策修改歷史

- **2026-10-09**：初始版本建立，記錄 Phase 0–Phase 7 的關鍵決策
- **2026-10-10**：新增 D8（AI 自動更新邊界與復原安全，Phase 2C-B/C/D 實作與驗證）
- **2026-10-10**：新增 D9（SR-1 安全基線：Host／Origin／標頭、key 外送、綁定、媒體輸出）
- **2026-10-10**：新增 D10（SR-2：資源上限、輸出衛生、列印管線硬化）

