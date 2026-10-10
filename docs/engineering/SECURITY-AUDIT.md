# Security Audit 1 — Desktop Application

- 狀態：**唯讀稽核（未改任何程式碼／設定／依賴／schema／測試）**
- 日期：2026-10-10
- 基線：`main @ 79eaecc`（11 ahead，未 push）；`pytest -q` 994 passed / 0 failed / 0 skipped（**功能測試全綠≠安全，本報告不以其為證據**）
- 範圍：本機執行的 ItemTrace 桌面應用（FastAPI 服務 + 零建置 SPA + CLI）。未來獨立手機 App 不在範圍。
- 方法：完整程式碼審查（所列檔案見附錄）＋**隔離實測**（暫存資料根、合成資料、僅 127.0.0.1；滲透驗證不含真實資料、不外連、不破壞）。

**嚴重性定義**：Critical＝未授權即可遠端執行或無條件洩漏長期機密；High＝在現實前置條件下可竊取機密或全面接管；Medium＝需使用者互動或造成 DoS／內容完整性風險；Low＝縱深防禦與資訊衛生；Info＝現況說明。

---

## SR-1 修復狀態（2026-10-10；對應 commit 見 `STATUS.md`）

> 本節由 SR-1 施工階段追加；上方 §1–§5 保留**稽核當時**的原始發現（唯讀快照）。

| 發現 | 狀態 | 修復與驗證（隔離實例、合成資料） |
|---|---|---|
| **F1** DNS rebinding／Host | ✅ **已修** | 新增 `shop/security.py`：Host 白名單（loopback 全形式＋`server_host`＋config `allowed_hosts`）＋Origin 驗證（host∈白名單、埠需一致、`null` 拒絕），在路由前 403。實測：`Host: evil.example` → **403**；`127.0.0.1:8899` → 200；測試 `tests/test_security.py` |
| **F2** key 轉送 | ✅ **已修** | `/api/settings/ai/test` 僅在端點屬**已知 preset** 時沿用已存 key；自訂 URL 必須帶臨時 key（否則 400）。實測：canary＋本地接收器——拒絕對照組零外送；帶臨時 key 時接收器只看到臨時 key |
| **F3** CSRF | ✅ **已修** | 變更類（POST/PATCH/PUT/DELETE）一律要求 `X-Requested-With: ItemTrace`；Origin 驗證同上。實測：無標頭 POST→**403**、`Origin: evil` → 403、同源→201；`web/core/api.js`、`tools/analyze_item.py`、驗證工具同步帶標頭 |
| **F5** 綁定 | ✅ **已修** | 程式預設 loopback；非 loopback 需 config `"allow_lan": true`。實測：現值 `0.0.0.0` 下 `python serve.py` **拒絕啟動（exit 2）** 並印出明確指示；隔離實例實際監聽 **127.0.0.1**；LAN 模式有警語＋README 信任模型說明 |
| **F6** 儲存型 XSS／媒體 | ✅ **已修** | 前端 `escapeHtml` 套用於紀錄／建議／錯誤訊息（home／capture／detail／router）；移除所有 inline `onerror`/`onclick`（CSP 相容）；回應加 `nosniff`／`Referrer-Policy`／HTML CSP（`script-src 'self'`、`frame-ancestors 'none'`）；`/files` 非圖片 → `application/octet-stream`＋`attachment`＋`default-src 'none'; sandbox`。實測：payload 名稱／備註／屬性（含惡意鍵）全部純文字、`window.__xss` 未定義、evil.html 下載化；瀏覽器 0 console errors；`tests/test_security.py`＋兩條靜態守門 |
| **F4** 資源上限 | ⏳ **未修**（SR-1 範圍外） | 依 SR-1 任務切分保留：body／單檔／檔數上限、PIL 像素上限、analyze 節流——建議列下一階段 |
| **F7** 資訊衛生／**F8** 列印 | ⏳ **未修**（低） | `/docs` 開關、錯誤訊息簡化、模板 script 過濾——候選後續 |

修復後重演的原始攻擊（隔離實例）：H1 evil Host 200→**403**；C1 CSRF void 200→**403**；K1 canary 外送→**400＋零外送**；evil.html `text/html`→**attachment/octet-stream**；有效綁定 0.0.0.0→**127.0.0.1**（且 0.0.0.0 未 opt-in 直接拒啟）。

**殘餘（已知且刻意保留）**：無登入系統的「信任區網」模型不變——LAN 上的直接用戶端（已 opt-in）仍可完整讀寫；非瀏覽器腳本只要帶標頭即可操作（設計如此）。F4/F7/F8 未動。

---

## 0. 現況基線（實測）

- 服務綁定：`serve.py` 讀 `config.json` 的 `server_host`；**程式碼預設 `127.0.0.1`**（`shop/config.py:20`），但**本 checkout 的 `config.json` 現值為 `0.0.0.0:8731`**（唯一遠處的實際配置）。
- 實測（暫存實例）：`Get-NetTCPConnection -LocalPort 8897 -State Listen` → **`0.0.0.0:8897 Listen`**；`127.0.0.1` 可達 200。→ 以現值啟動時，**同一網段所有裝置皆可完整使用 API**。
- 認證／授權：**全應用沒有任何登入、token、session、權限層**。唯一與來源有關的邏輯是 `settings.is_loopback()`，但只用來在 `GET /api/settings/ai` 回報 `is_loopback` 旗標；**所有寫入端點（含 AI key 寫入）在設計上接受任何可達來源**（`shop/settings.py:1-25` docstring 明說「區網裝置也能操作 AI 設定」；`tests/test_settings_api.py:375-395` 以測試釘住「LAN 可改 key／清除 key／跑測試」）。
- CSRF/CORS：未安裝 CORS middleware（實測回應無 `Access-Control-Allow-Origin`）；亦無任何 Origin/Host 驗證。

---

## 1. 確認的發現（Confirmed）

### F1 — 無 Host/Origin 驗證：DNS rebinding 可讓**任何網站**完整操作本機應用（High；Confirmed）
- **證據**：`GET /api/items` 帶 `Host: evil.example` → **200**（實測）；程式碼全庫無 Host/Origin 檢查；無 CORS 亦無自訂標頭要求 → 跨站「simple request」可直接改狀態（見 F3）。
- **攻擊路徑**：使用者瀏覽惡意網站 → DNS rebinding（首次解析到攻擊者、rebind 到 `127.0.0.1`）→ 瀏覽器對 `http://evil.example:8731` 的 fetch 實際打到本機服務；伺服器看到 socket 對端是 **loopback**、Host 是 `evil.example` 但不驗證 → 頁面（同源）可**讀取所有紀錄／照片／事件、修改、void、匯出 evidence**，並串接 F2 竊取 AI key。**即使 `server_host=127.0.0.1` 也成立**。
- **前置條件**：使用者於服務執行期間造訪攻擊者網頁；攻擊者需可控 DNS rebinding（成熟手法）。瀏覽器 PNA（Private Network Access）在部分新版 Chromium 對 public→local 會擋（未逐一瀏覽器實測，列未驗證變因）。
- **影響**：等同把無認證的完整控制權交給任意網頁；本機單人使用情境（場景 1）即受影響。
- **修復**：① Host 白名單（`localhost`、`127.0.0.1`、`[::1]`、設定的區網 IP）；不符 → 403。② 狀態變更端點要求自訂標頭（如 `X-Requested-With: ItemTrace`）或 CSRF token —— 迫使瀏覽器先送 preflight，簡單跨站請求即失效。③ 保留 loopback 預設綁定。
- **回歸測試**：`Host: evil.example` → 403；無自訂標頭且 `Origin` 外站 → 403；正式 UI 流程不受影響；同標頭邏輯覆蓋 /api/*（`/docs` 可另議）。

### F2 — `/api/settings/ai/test` 會把**已儲存的 API key** 送往呼叫者指定的 `base_url`（High；Confirmed）
- **證據（實測）**：本機放置假 key（canary，`sk-or-v1-…`）＋假 provider 設定，對 8898 埠本地監聽器呼叫 `POST /api/settings/ai/test`（`{"provider":"custom","base_url":"http://127.0.0.1:8898"}`）→ 監聽器收到 `POST /chat/completions` 且 `Authorization: Bearer sk-or-v1-…`（canary 比對 **true**）。程式碼：`shop/settings.py:194-249`（`incoming or stored.api_key`＋`chat_endpoint(provider, base_url)`＝任意 base_url + `/chat/completions`）。
- **前置條件**：任何可達來源（LAN，或 F1 的 rebinding 頁面／本機其他程序）。無需知道 key 內容。
- **影響**：**長期機密外洩**（provider key 可被拿去別處使用、產生費用），且與「LAN 只能替換 key」的既有信任聲明不同——此處是**竊取現有 key**。
- **修復（最小）**：測試端點只在 `base_url` 屬於**已知 preset** 時可沿用已存 key；自訂 base_url 時**必須同時帶入新的 key**（不允許 `incoming=""`+`stored`）；或將自訂 base_url 限 loopback 並加顯式確認參數。
- **回歸測試**：`base_url` 非 preset 且未帶 key → 400 且監聽器未收到任何請求；preset＋已存 key → 照常。

### F3 — 無 body 的狀態變更端點可被跨站 CSRF（Medium；Confirmed）
- **證據（實測）**：`POST /api/items/{id}/void` 帶 `Origin: http://evil.example`、`Content-Type: text/plain` → **200，item.status=void**（伺服器不看 Origin；此類請求不需 preflight）。
- **受影響（無 body、無自訂標頭要求）**：`/api/items/{id}/void`、`accept`/`reject`/`undo`、`/api/items/{id}/ai/analyze`（**觸發付費 AI 呼叫**）、`clear-key`、`/api/events/{id}/revert`、（PATCH 型端點因需 JSON 會觸發 preflight，較安全）。
- **前置條件**：F1 同源條件或「瀏覽器允許 public→local 簡單請求」（PNA 部署程度不一，未驗證）。
- **修復**：同 F1②（自訂標頭／token）；analyze 另加節流。
- **回歸測試**：無自訂標頭的外站 `Origin` → 403；正常 UI（帶自訂標頭）→ 200。

### F4 — 上傳與圖片處理缺資源上限（Medium；Confirmed/部分推論）
- **證據（實測）**：單檔 **20 MB** 上傳 → **201 接受**（無任何大小上限）；程式碼：`shop/api.py:767-776` 逐檔 `await upload.read()` 全量進記憶體、無檔數上限、無 body 大小中介層（FastAPI/uvicorn 預設不限）；`shop/inbox.py:310-318` 任意位元組落盤。圖片解碼：`shop/ai_client.py:199-215` 以 PIL 解碼縮圖，**未設 `Image.MAX_IMAGE_PIXELS`**（PIL 僅在超大時警告；≈89MP 以上僅 warning、~178MP 才 raise）→ 「小檔大像素」PNG 可在 analyze 時造成高記憶體峰值；analyze 每次 1 次 provider 呼叫，可被無限次觸發（成本 DoS）。
- **前置條件**：可達來源。後果為 DoS／磁碟填充／費用，非機密外洩。
- **修復**：請求 body 上限（如 50 MB）＋每檔 25 MB＋每請求 20 檔；`Image.MAX_IMAGE_PIXELS` 明確設定並回 400；analyze 端點節流（如每分鐘 N 次）。
- **回歸測試**：超限上傳 → 413/400；超像素 fixture → 400；連續 analyze → 429。

### F5 — 現行部署綁 `0.0.0.0`：不受信任網路上即全面暴露（High（as-configured）；Confirmed，且部分為刻意設計）
- **證據**：`config.json`（本機、gitignored）`server_host: 0.0.0.0`；實測綁定 `0.0.0.0 Listen`；零認證（§0）。
- **判定**：專案文件把「信任區網」當前提（`shop/settings.py` §2、測試明文）——**在家用受信任 LAN 屬可接受設計**；但 0.0.0.0 同時涵蓋咖啡店／旅館／公司／來賓 Wi-Fi，且沒有啟動警告或可視提示；只要一次誤連不受信任網路，紀錄、照片、AI key 全部可被讀寫。
- **修復**：預設回到 `127.0.0.1`；「開放區網」改為顯式選項（`--lan` 或設定值＋啟動訊息＋README 安全段）；或保留 0.0.0.0 但強制啟用 F1 的 Host 白名單＋自訂標頭。
- **回歸測試**：預設設定檔啟動 → 僅 loopback 可達（連線自非 loopback 位址失敗／403）。

### F6 — 前端全面 innerHTML 注入：紀錄／建議值可存成 XSS；上傳 HTML 原樣寄宿（Medium；Confirmed（程式碼＋實測））
- **證據**：`web/` 內 **28 處 `innerHTML`**、**0 處 HTML escaping**（grep `escapeHtml|sanitize` 無效命中）；例：`home.js:187`、`record-detail.js:165,458` 直接插值 `item.name/notes/attributes`、`suggestion.value`（含 AI 產出）。實測：上傳 `evil.html` → 儲存為 `inbox/evil.html`，`GET /files/inbox/evil.html` → **200 `Content-Type: text/html`，無 `X-Content-Type-Options`**（可被導向成為同源 XSS）。
- **前置條件**：能寫入資料者（現行 LAN／F1 後的頁面；或「自訂 base_url 的 provider 在建議值中夾帶 HTML」經分析→渲染）。
- **影響**：腳本在使用者瀏覽器以應用同源執行 → 即使在 loopback-only 設定下也可完整操作本機 API、偽造 UI；屬存儲型 XSS 類。
- **修復**：所有插值改 `textContent`／屬性轉義（或最小 escape util）；下載／寄宿面加 `X-Content-Type-Options: nosniff`、上傳僅接受圖片型別（magic bytes）並以 `Content-Disposition: attachment` 或統一 `image/*` 提供；加 CSP（`default-src 'self'; script-src 'self'`；V3 零 inline script 可行）。
- **回歸測試**：以 `<img onerror>` 為 name 建立紀錄 → 首頁/詳情 DOM 為純文字、無腳本執行（可用 Playwright 斷言 window 旗標未設）；`/files/**/*.html` → 非 text/html 或帶著 nosniff。

### F7 — 資訊衛生與縱深缺口（Low；Confirmed）
- `/docs`、`/openapi.json` 對任何可達來源開放（實測 200）——等同介面地圖。
- 錯誤訊息含檔案系統路徑與 provider 原文（key 已 redact ✓）：如 404 `找不到檔案：…`、ConfigError 全路徑。
- `/files/*` 回應 `Cache-Control: public, max-age=86400`——本機單使用者影響低，但語義上應為 `private`。
- 無任何安全標頭（`X-Content-Type-Options`、CSP、`Referrer-Policy`…）。
- **修復**：`--docs` 開關或 loopback 限 docs；錯誤訊息對外簡化（細節僅伺服器 console）；`private, max-age`；加基本安全標頭。

### F8 — 列印管線以 `--no-sandbox` 在 headless Chromium 執行使用者可控 HTML（Low；Plausible，未完整驗證）
- **證據**：`shop/print_backend.py:344-360`（chromium 參數含 `--no-sandbox`，`shell=False`、無指令注入；browser 路徑來自固定候選＋`ITEMTRACE_BROWSER` 環境變數，**不可由 API 指定** ✓）；Template 內容可由 API 任意建立（`POST/PUT /api/templates`），列印時整份 HTML 進瀏覽器；item 值插入 template 的轉義策略未逐一驗證。
- **影響**：列印時腳本在無沙箱 headless 瀏覽器內執行（本機、`file://` 情境）；目前無直接機密通道，屬縱深風險與穩定性風險（可造成列印失敗）。
- **修復**：模板渲染時限制/去除 `<script>` 與事件屬性；列印 HTML 以 `file://` 專用目錄＋僅 data-URI 資源（已是）；評估移除 `--no-sandbox`（Windows 下 Edge/Chrome headless 常可免）。
- **回歸測試**：含 `<script>` 的模板 → 列印輸出不含腳本（或 400）；正常模板不受影響。

---

## 2. 已驗證安全（正面清單，供回歸保護）

| 項目 | 證據 |
|---|---|
| `/files` 路徑穿越防護 | **Raw-socket 實測**（繞過客戶端正規化）：`../`、`..%2F`、`%2e%2e%2f`、多層 `..` 全部 **404**；`_serve_file` resolve＋`is_relative_to(files/inbox)`（`api.py:1096-1119`）；SPA fallback 同規則（`:150-158`） |
| 上傳檔名／intake 路徑 | `sanitize_name` 過濾 `/ \\` 等（`inbox.py:36,382-391`）；`resolve_inbox_paths` 限 `inbox/` 子樹（`:109-129`）；不覆寫（`unique_target`） |
| 秘密不進前端／GET | `GET /api/settings/ai` 回應無 key、無 api_key 欄位（**實測 canary 不在回應**）；web/ 無 key 字樣 |
| 秘密不進 Git | `config.json`、`tools/*.local.json` 皆 gitignore ✓；**git log 無該二檔歷史**；tracked tree 僅測試假 key（`sk-or-v1-TEST-…`） |
| 秘密檔權限 | 寫入走 atomic replace ＋ `chmod 0600`（`ai_config.py:361-369`）；redact 涵蓋 `sk-`/`AIza`（`:376-388`），錯誤路徑均經 redact |
| 來源判定不被標頭欺騙 | `is_loopback` 只讀 socket peer（`settings.py:54-67`）；測試釘住 XFF/Host 偽造無效（`test_settings_api.py:397-421`） |
| SQL 注入 | 全庫查詢以參數綁定；動態片段只來自程式常數欄名（`repo.py` `_where` 模式）；無字串拼接值 |
| 指令注入／反序列化 | 僅 `print_backend.py` 用 `subprocess`：參數陣列、`shell=False`、60s timeout；無 `eval/exec/pickle/yaml.load`（grep） |
| 破壞性操作 | 無永久刪除 API；void 為軟刪除且資料／檔案保留；original 照片不可被刪（需先改成 derived）；備份／驗證只在 CLI |
| 資源界限（部分） | items `limit ≤500`、events `limit ≤2000`、inbox group gap `≤1440`、`MAX_PHOTOS=8`、`MAX_SIDE=1024` 縮圖、AI 單輪 `MAX_SUGGESTIONS=24` |
| 依賴已知 CVE | 安裝：fastapi 0.142.2 / starlette **1.7.0** / uvicorn 0.54.0 / python-multipart **0.0.32** / pymupdf 1.28.2 / pywin32 312。查核：python-multipart <0.0.27（CVE-2026-42561）與 <0.0.26（CVE-2026-40347）**已高於修正版**；starlette CVE-2026-54283（<1.3.1）**不受影響**。未跑自動化掃描（pip-audit）＝未驗證面 |

---

## 3. 情境評估（必答）

| 情境 | 判定 | 說明 |
|---|---|---|
| **1. 單機單人使用** | **基本可接受，但非免疫** | 無認證在此情境合理；然而 F1（rebinding：任意網頁可全控）、F2（本機程序／頁面可竊 key）、F6（XSS 在本機瀏覽器執行）、F4（本機 DoS）都不需要 LAN 就能觸發。**F1＋F2 建議視為本情境必修**。 |
| **2. 私有區網（手機／其他裝置）** | **有條件可接受** | 專案採「信任區網」模型且測試釘住（LAN 可全讀寫＋改 key）。前提是**真的只有受信任裝置**；現值 0.0.0.0 讓任何同網段裝置（含訪客）取得同等權限，且 F2 可把 key 帶走。可接受於自宅受控網路；**不建議**在共用／不可信網路使用。 |
| **3. 公開網際網路** | **明確不可接受** | 零認證＋完整讀寫＋key 竊取＋DoS；即使加 Host 驗證也不足以公開。若未來要公開，需完整認證/授權層（本階段不做）。 |

---

## 4. 最小修復階段建議（SR-1，供下一階段採用）

**目標：讓「本機單人」與「受信任區網」兩個已聲明的使用情境真正站得住，且不引入登入系統。**

1. F1/F3：Host 白名單 + 變更端點自訂標頭（一次 middleware 可解；~60 行＋測試）。
2. F2：test 端點禁止「已存 key＋自訂 base_url」組合（~15 行＋測試）。
3. F4：body/單檔/檔數上限＋`MAX_IMAGE_PIXELS`＋analyze 節流（~40 行＋測試）。
4. F6：前端 escape util 全站套用＋`nosniff`／上傳型別檢查（~80 行＋Playwright 斷言）。
5. F5：預設綁回 127.0.0.1；「開放區網」顯式選項＋啟動警告（文件與 config 政策）。
6. F7/F8：安全標頭、docs 開關、模板 script 過濾（可拆下一階段）。

驗收（SR-1）：新增安全回歸測試全綠＋既有 994 測試不弱化；以本報告的實測腳本（Host/Origin、key-forwarding canary、超限上傳、XSS fixture）作為驗收重演。

---

## 5. 未驗證與限制（誠實聲明）

- 未跑自動化依賴掃描（pip-audit/Dependabot）；CVE 比對僅針對所列三件。
- 瀏覽器 PNA／DNS rebinding 的實效依 Chrome/Edge/Firefox 版本而異，未逐瀏覽器實測（F1/F3 的「瀏覽器端緩解」屬變因）。
- 未做競態／TOCTOU、無 fuzzing、未審計 PyMuPDF/GDI 列印之原生層、未審計 Windows 防火牆與實際外網可達性（僅證明 0.0.0.0 綁定）。
- 未模擬第二台實體裝置（僅以 socket/標頭層等價手法）；LAN 實機測試列為 SR-1 驗收時的補充。
- 稽核限本 checkout（`79eaecc`）；任何後續 commit 需以同方法重驗 F1-F4 修復。

## 附錄 A：實測證據摘要（全部隔離、暫存資料）

- `GET /api/items`＋`Host: evil.example` → 200；`POST …/void`＋`Origin: evil.example`＋text/plain → 200（status=void）。
- canary key 經 `/api/settings/ai/test`（custom base_url）→ 本地監聽器收到 `Bearer sk-or-v1-…`（比對 true）；`GET /api/settings/ai` 回應不含 canary。
- raw-socket 穿越 5 變體 → 全 404；`/docs` → 200；API 回應無 CORS 標頭；上傳 20MB → 201；`evil.html` 上傳後以 `text/html` 供檔（無 nosniff）。
- 綁定實測：temp 實例 `0.0.0.0:8897 Listen`。

## 附錄 B：主要審閱檔案

`serve.py`、`shop/config.py`、`shop/api.py`（全部路由/中介/檔案服務）、`shop/settings.py`、`shop/ai_config.py`、`shop/inbox.py`、`shop/photos.py`、`shop/repo.py`（查詢模式）、`shop/print_backend.py`、`shop/evidence.py`（既有相位已審）、`web/core/*.js`、`web/views/*.js`（innerHTML  sink 盤點）、`config.json`、`.gitignore`、`requirements.txt`、`tests/test_settings_api.py`（信任模型斷言）、git 歷史（秘密掃描）。
