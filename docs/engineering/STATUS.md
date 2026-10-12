# ItemTrace Engineering Status

最後更新：2026-10-12

**當前狀態：拍照／匯入雙入口 UX 完成，裝置文案掛載修正完成（零 schema／API 變更），1199 測試無失敗**

遠端狀態：`main` 與 `origin/main` 同步（含本階段 commit）

測試驗證：`pytest` 完全通過，全 **1199 測試**無失敗、無跳過（1196 基線 +3）

## 📱 MVP 交付檢查清單

**功能完整性** ✓：
- ✓ 拍照 → AI 分析 → 一鍵存檔 完整流程
- ✓ 已保存紀錄編輯、追加照片、AI 重新理解（含完整修改歷史、識別碼溯源與新證據自動套用）
- ✓ 搜尋名稱、品牌、型號、序號，即時找回
- ✓ 手機優先 UI，同時支援電腦操作
- ✓ AI 失敗優雅降級（存照片、無建議仍可用）

**測試涵蓋** ✓：
- ✓ 1179 個自動化測試全數通過
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

### 匯入按鈕裝置文案切換修正（capture）← **COMPLETED**

完成時間：2026-10-12（有限範圍修正；僅前端挂載邏輯與測試）

- ✓ **問題**：`renderEntryLabels()` 的掛載監視器觀察 `document.body`
  且只有 `childList`；router 實際把 view 掛進 `#app`（`#app` 本來就是
  body 的子節點），監視器永遠等不到插入 —— 觸控裝置的「從相簿匯入」
  不會生效，按鈕維持模板預設「選擇照片」
- ✓ **修正**（`web/views/capture.js` 單一區塊）：改為觀察實際掛載容器
  `#app`（`getElementById('app') || document.body` 後備）並加
  `subtree: true` 涵蓋任何層級插入；確認掛載後立即 `disconnect()`
  （不做長期 DOM 監視）；其他 insertion（如 toast）先到時不誤判掛載、
  繼續等待。未動按鈕行為、流程、API、schema
- ✓ **測試 +3**（`tests/test_capture_inputs.py`）：以 Node 執行真實
  `createCaptureView`＋最小 DOM shim 模擬 router 掛載，驗證掛載後
  文案 —— coarse→「從相簿匯入」、fine→「選擇照片」、無 `#app` 後備
  仍正確；並驗證掛載前預設文案不變、不相關插入不提早停止監視、掛載
  後監視器歸零、四個入口（含托盤追加）仍觸發正確 input。反轉驗證：
  換回舊版監視器時 3 項掛載測試全數失敗（確認能攔住迴歸）
- ✓ **瀏覽器實測**（隔離暫存資料、`127.0.0.1:8732`、桌面 Chromium、
  `matchMedia` stub 非真機）：`?stub_coarse` →「從相簿匯入」、
  `?stub_fine` →「選擇照片」；匯入入口開檔選擇器、選 1 張入托盤、
  input 重設；0 console error。真機（iOS／Android）未驗證
- ✓ 全 1199 pytest 通過、`node --check` 全 web JS 通過、`git diff --check`
  乾淨；正式開發資料庫與手機配對零接觸

### 拍照與相簿／檔案匯入雙入口（capture UX）← **COMPLETED**

完成時間：2026-10-12（有限範圍 UX；零 schema、零後端 API 變更）

- ✓ **兩種明確入口**（`/capture` 初始畫面與托盤中都有）：拍照用
  `capture="environment"` 的圖片輸入框（行動瀏覽器提示後置相機；不保證
  所有裝置）；匯入用 `type=file`、`accept="image/*"`、`multiple`、
  不帶 capture（手機／電腦走系統照片／檔案選擇器）。兩者視覺層級相近
- ✓ **文案依情境**：觸控裝置（`pointer: coarse`）顯示「從相簿匯入」、
  桌面上顯示「選擇照片」；不宣稱能存取整個相簿，只處理使用者明確選取
  交付的照片；文案全部走 i18n（雙語 7 keys，無硬寫字串）
- ✓ **共用既有流程**：兩個入口與拖放都進同一個 `appendFiles()` 待整理
  流程（多張、預覽縮圖、移除、分批追加、確認後才 AI 分析、存起來才
  建檔）；追加不清空、不重複；每個 file input 讀取後重設（同一張照片
  可再次選取）；取消選取不顯示錯誤、不清既有照片
- ✓ **格式誠實處理**：新增 `web/core/photoFiles.js` 分流 —— HEIC／HEIF
  （瀏覽器多半無法預覽、後端也不保證解碼）在選取當下明確提示、不假裝
  匯入成功；瀏覽器無法解碼的其他圖以縮圖 onerror 兜底移除並告知；
  未引入影像函式庫或轉檔系統
- ✓ **測試 +6**（`tests/test_capture_inputs.py`）：兩個獨立入口靜態接線
  （capture／multiple／reset）、雙語 key、Node 執行實際 ESM 模組驗證
  格式分流與兩批追加保留／取消不清空／同名不誤刪／HEIC 提示；全 1196
  pytest 通過、`node --check` 全 web JS 通過
- ✓ **隔離瀏覽器實測**（暫存資料目錄、`127.0.0.1:8732`、正式資料零接觸）：
  拍照與匯入按鈕開啟對應輸入框（file chooser 實測）；匯入 2 張→托盤
  2 張；追加 1 張→3 張且三張縮圖可解碼；HEIC 被拒＋雙語提示、托盤不變；
  壞檔預覽兜底移除；「AI 開始整理」→3 張進 inbox、0 筆正式紀錄（確認
  儲存才建檔的生命週期不變）；取消→inbox 清空、0 筆紀錄；375px 窄螢幕
  兩顆按鈕全寬 47~51px 高、畫面完整；英文語系文案正確、0 console error

### Phase 4：資料夾管理 UI 與路由整合 ← **COMPLETED**

完成時間：2026-10-12  
Commit：`a658c68` Phase 4: Add folder management UI and routes（已推送）  
基準：`1c1100d`（Phase 4 API & Repository 完成後）

完成內容：
- ✓ **前端視圖實作**：
  - `web/views/folders.js`：資料夾列表頁面，含建立、編輯、刪除modal；虛擬「未分類」資料夾顯示未分類紀錄數
  - `web/views/folder-detail.js`：資料夾詳情頁面，列出該資料夾內的紀錄，支援搜尋過濾
- ✓ **路由與 API 集成**：
  - `web/app.js`：新增 `/folders` 與 `/folders/:id` 路由
  - `web/core/api.js`：6 個新方法（`listFolders`, `createFolder`, `updateFolder`, `deleteFolder`, `getFolderItems`, `moveItemToFolder`）
- ✓ **紀錄移動操作**：
  - `web/views/record-detail.js`：詳情頁新增「移至資料夾」按鈕，點擊展開資料夾選擇器
  - 支援移至資料夾或回到「未分類」
- ✓ **首頁導航集成**：
  - `web/views/home.js`：在紀錄計數旁新增「📁 資料夾」與「🗑 垃圾桶」導航連結（低視覺權重）
- ✓ **i18n 完整性**：
  - 新增 `folders` 命名空間：建立、編輯、刪除、移動操作相關 key × 2（繁中＋英文）
  - 新增 `app.create` key（繁中＋英文）
  - 新增 `detail.moveToFolder`, `detail.selectFolder`, `detail.moveToFolderDone`, `detail.moveToFolderError` × 2
- ✓ **UI 樣式**：
  - `.folder-card`：資料夾卡片（包含名稱、描述、紀錄數、操作按鈕）
  - `.folder-list`：卡片列表
  - `.modal` 與 `.modal-content`：建立／編輯資料夾 modal
  - `.folder-option-btn`：移動操作時的資料夾選擇按鈕
  - `.records-nav-links`：首頁導航連結樣式
  - 手機響應式調整（375px 以下）
- ✓ **測試驗證**：全 1190 pytest 測試通過（無新增測試，基於 API/schema 已驗正）；前端靜態檢查通過（無 js 語法錯誤）
- ✓ **無迴歸**：既有 1180 測試全數保留，無刪修；手機與桌面界面均可用

### 重複描述候選（多筆 attribute:description）修正 ← **COMPLETED**

完成時間：2026-10-12｜基準：`3c25653`

- ✓ **問題**：AI prompt 允許同一欄位在不同照片提出多筆建議；capture.js
  只把第一筆 description 讀進單一輸入框、其餘描述列被排除在編輯 UI
  之外，但存檔驗證又檢查重複 attribute key —— 多筆 description 建議
  造成保存被阻止，使用者卻無法在介面上找到並移除多餘的列（死結）
- ✓ **修正（僅前端；零 schema、零 API 變更）**：描述候選有專屬編輯區塊，
  每一筆都看得見、可修改（textarea）、可移除（✕）、可查閱來源照片；
  多筆候選時以 radio 明確選擇要保存的一筆（不沉默擇一、不丟棄證據）
- ✓ **保存語意**：只有選取的一筆會寫入 `attributes.description`（詳情頁
  主要描述語意不變）；選取且未改 → accept；已修改 → reject＋PATCH（不
  冒充 AI 判讀）；未選取／移除以至清空的候選 → reject，AI 原值、model、
  信心、來源照片完整保留在建議歷史；閱讀模式列出全部候選（標示主要／
  未採用／候選）並提示需先選擇
- ✓ **明確選擇要求**：尚未選擇就存檔 → 本地驗證阻止（在 intake 之前），
  顯示雙語訊息、直接進入編輯模式並帶到候選列
- ✓ **重試安全**：部分保存後改選／清空／移除描述 → value-aware 清除舊值
  （只刪確實是我們寫入的值，不誤刪剛選取的新值）；曾因修改被拒絕、重試
  前又改回原值的描述也能經 PATCH 落地（accept 已不可能）
- ✓ **測試**：`test_generic_records.py` +6（兩筆候選移除＋修改、保留原值
  accept、全部移除、單筆、改回原值、部分保存後改選）、`test_web_views.py`
  +1（前端接線、每列可操作、雙語鍵）＋既有靜態檢查更新（總數 1179）
- ✓ 全 1179 pytest 通過；`node --check` 全 web JS 通過；Playwright 對獨立
  暫存資料庫實測（真實 capture.js，AI 草稿以 route 攔截模擬）：40 項檢查
  全數通過（含部分失敗後改選重試、console 除刻意中止外零錯誤）；預設開發
  資料庫與真實手機配對零接觸
- ⚠️ 已知限制：建議狀態是終態 —— 部分失敗前已 accept／reject 的候選在
  重試時無法改回另一狀態（後端沒有反接受／反拒絕 API）；改選以 accept
  覆蓋值或 PATCH 落實最終值，歷史事件完整保留（與前一階段限制一致）

### 通用紀錄保存一致性修正 ← **COMPLETED**

完成時間：2026-10-11｜基準：`49488ee`

- ✓ 保存以使用者最後確認的內容為準：與最終輸入等值的建議才 accept；
  被清空／修改／移除的一律 reject（建議保留 AI 原值／model／信心／
  來源照片；使用者修改走 PATCH，不冒充 AI 判讀）
- ✓ 固定欄位清空會真的清掉（含部分失敗後的殘留）；識別碼（serial／
  imei／barcode）可在審閱時修改／移除，已套用後被改掉／移除的值會
  真的從紀錄刪除（DELETE identifier）
- ✓ 動態屬性以「GET 現值加減差異」寫回：移除是真的刪除、不動看不見的鍵
- ✓ 存檔前本地驗證（在第一次 intake 之前）：標題必填；新增屬性 key 需
  符合 `^[a-z][a-z0-9_]{0,39}$`、不得重複（含 description 與 AI 既有
  列）；失敗顯示本地化訊息並阻止建檔，不留半套正式紀錄
- ✓ 部分保存後重試：不重複建檔、已套用的不重跑、重試前的修改與移除都會
  落實（瀏覽器 E2E 驗證識別碼與 attributes 於重試後真刪除）
- ✓ 測試：`test_generic_records.py` +8、`test_web_views.py` +1、既有靜態
  測試更新（總數 1172）
- ⚠️ 已知限制：部分失敗前已被 accept 的建議無法改回 rejected（後端沒有
  「反接受」API）；重試後的修改以 PATCH 落實，歷史保留「accepted → 使用
  者修改」事件序列，正式紀錄不殘留舊值

### 通用照片紀錄第一版（非商品照片）← **COMPLETED**

完成時間：2026-10-11｜基準：`0f8d0e3`

- ✓ 資料契約沿用既有模型：`name`＝通用標題、`attribute:description`＝描述、
  `attribute:<key>`＝動態屬性（AI key 驗證規則不變）；未動 schema
- ✓ AI prompt 通用化：商品／文件／風景／街景／人物活動皆可；明令非商品
  照片不得硬套品牌、型號、品況、識別碼，且不得憑空補入地點、人物身分、
  時間；拒絕／撤回保護條款原樣保留
- ✓ 草稿審閱（capture.js）：描述與所有 attribute:<key>、imei／barcode
  全部先呈現再保存（舊版會被靜默套用）；編輯模式可修改／新增／移除動態
  屬性；操作區在內容下方（存起來／修改／取消）；改過的值標「自訂」
- ✓ 保存：AI 草稿維持 create→accept（model／信心／來源照片追溯）；使用者
  新增屬性以 PATCH attributes 合併；移除／清空的屬性不會被套用；重試、
  部分失敗、取消與暫存照片生命週期不變
- ✓ 詳情頁：標題＋描述為閱讀主入口，描述不再重複列在補充資訊
- ✓ 搜尋：既有 LIKE 已涵蓋 name／brand／model／category／notes／
  attributes（含描述）／識別碼／已接受建議值；首頁提示改為「搜尋任何你
  記得的紀錄資訊……」（pending／rejected 建議仍不進搜尋）
- ✓ 測試：`tests/test_generic_records.py` 7 項＋`test_web_views.py` +2；
  全套 1163 通過；Playwright 對獨立暫存 DB 實測（正式資料零接觸）

### 物品詳情頁「找不到此紀錄」修復（P0）← **COMPLETED**

完成時間：2026-10-11｜基準：`ded1f11`

- ✓ 根因（瀏覽器實測）：`renderDetail` 查詢 UI 精簡時（`e86f6ee`）已移除的
  `#status-badge` → `null.textContent` 拋 TypeError 中斷整個 render；
  `loadDetail` 的 catch 又把所有錯誤一律標成「找不到此紀錄」——API 實際
  一直回 200（`GET /api/items/ITM-0010`）
- ✓ 修復：移除失效的 statusBadge 參照；錯誤分類以 404 為界 ——
  401／403 →「沒有存取權限」、5xx →「伺服器發生錯誤」、網路中斷 →
  「無法連線」，皆提供「重試」與返回首頁
- ✓ 測試：`tests/test_web_views.py`（查詢的 element id 必須存在於同檔、
  錯誤分類、雙語 key）＋ `test_api.py` 列表→詳情契約（+4；總數 1154）
- ✓ 瀏覽器驗收：首頁點卡片→詳情完整顯示（標題／照片／規格，0 console
  error）；404／500／網路中止／401 四種錯誤各自顯示正確訊息與重試

### 手機免設定檔配對與連線安全邊界 ← **COMPLETED**

完成時間：2026-10-11｜基準：`3791eaf`（前一版配對骨架；原 Ed25519/Web Crypto 設計在區網 HTTP 不可行）

- ✓ 端到端配對：電腦「設定 → 手機配對」產生 QR Code（`segno` 本機產生，
  不經任何外部服務），手機掃描開啟 `/pair` 頁自動完成 claim，取得裝置權杖
  （伺服器只存 SHA-256 雜湊；原文只在 claim 回應出現一次）
- ✓ 三層授權（`shop/security.py`）：admin（loopback）／device（Bearer 或
  HttpOnly cookie）／unpaired（僅配對頁、靜態與 claim／session／health）；
  未配對裝置的 GET 資料與照片一律 403，CSRF 標頭不構成存取權
- ✓ 配對管理（start／工作階段狀態／QR／裝置清單／撤銷）僅限電腦本機
- ✓ 媒體 `<img src="/files/…">` 以 cookie 通過認證；撤銷後權杖與 cookie 立即失效
- ✓ 預設 `server_host: 0.0.0.0`、移除 `allow_lan` opt-in（安全改由配對授權承擔），
  啟動不需手動修改 `config.json`
- ✓ 一次性配對碼：5 分鐘過期、錯誤嘗試 5 次上限（計數持久化）、成功後不可重用
- ✓ 前端自動附加 `Authorization: Bearer`（`web/core/api.js`）；未配對裝置顯示
  配對引導頁；撤銷／失效（401）自動清除本機權杖
- ✓ 配對碼不進 HTTP 存取日誌：QR 網址改用 fragment（`/pair#id=…&code=…`），
  瀏覽器不會把 fragment 送進請求行（`438272a` 後續修正）
- ✓ 舊版設定的相容：`config.json` 留著舊預設值 `server_host: "127.0.0.1"`
  （且未含 `local_only` 鍵）時自動升級為區網綁定，升級後不需手改設定即可
  配對；明示的純本機模式改用 `local_only: true`（綁 loopback，配對端點
  給出可操作的解除說明）（`438272a` 後續修正）
- ✓ QR 顯示修復（`38cc562` 後續修正）：原本用 segno `svg_inline()`
  （無 `xmlns`／`viewBox` 的 HTML 內嵌片段），`<img src>` 拿到 HTTP 200
  但瀏覽器無法解碼（實測 naturalWidth = 0、QR 空白）；改用獨立 SVG 文件
  （`save(svgns=True, xmldecl=True, unit="px")`），迴歸測試釘住 namespace
- ✓ 配對頁失敗處理（`38cc562` 後續修正）：建立工作階段失敗在頁面上保留
  可讀的伺服器訊息；QR 載入失敗顯示具體原因與「重試顯示 QR Code」，
  不再只有空白或破圖；文案統一為「開始配對」（不再出現「連結手機」）
- ✓ 新增 `tests/test_pairing.py` 38 項與 `tests/test_config.py` 15 項回歸：
  生命週期、暴力限制、撤銷、管理端點邊界、QR 本機性與可解碼文件、
  fragment 不外洩、舊版設定檔相容、純本機模式、預設啟動、舊 schema 遷移
- ⚠️ 限制：真機瀏覽器（iOS/Android）未在自動化環境驗證；後端契約與
  授權邊界已由測試釘住，真機流程需人工驗收

### 既有紀錄 AI 重新分析流程改善：完整上下文、證據時間軸與合理更新政策 ← **COMPLETED**

完成時間：2026-10-11  
基準：`68b1399`（capture 建檔流程修正後）

改善內容：
- ✓ **完整單筆紀錄分析上下文（`build_analysis_context`）**：
  - 核心 API 與外部 adapter（`tools/analyze_item.py`）共用同一套上下文組裝函式
  - 整合目前紀錄狀態（名稱、品牌、型號、分類、狀況、全部屬性與備註）
  - 整合已登記識別碼清單（類型、值、來源照片 ID）
  - 整合本次選取之照片與拍攝觀測時間軸，並打上標籤（`[初始建檔照片]`、`[後續追加照片]`、`[含識別碼證據]`）
  - 整合重要歷史修改（從 events 提取使用者人工修改欄位與時間、系統自動套用與撤銷 Undo 紀錄）
  - **精確區分歷史建議語意**：
    - `status=accepted, source=auto` 標示為「⚙️ 系統先前自動套用」（不混充為使用者採納）
    - 使用者手動接受標示為「✓ 使用者已採納」
    - 系統自動套用後被撤回（Undo）標示為「↩️ 使用者先前撤回（Undo）」
    - 使用者明確拒絕標示為「⚠️ 使用者明確拒絕」
    - 提示詞指引：曾遭撤回或拒絕的值在無新證據時不重複提議、永不自動套用；有新證據可再次提出，但僅為待確認建議
  - **明確規範外部工具邊界**：
    - `tools/analyze_item.py` 外部 adapter 受限於最小權限設計，不讀取內部 events
    - 上下文明確標記限制「- （無手動修改記錄或未取得歷史）」，不宣稱完全同步
- ✓ **關鍵照片保留與精準來源映射（`select_photos_for_analysis`）**：
  - 回傳張數保證不超過 `max_photos`（含 2／3 等小預算；曾因預算未隨請求縮放而超出上限）
  - 超過 8 張照片時，依明確配額取捨：
    - 必須保留：Photo 0（初始建檔基線）與最新追加照片（預算允許時最新 2 張）
    - 優先保留：包含已登記識別碼的照片（$\le 5$ 張全數保留；$> 5$ 張保留最新 5 張；名額不足時 Photo 1 讓出給識別碼）
    - 餘額由最新照片往前依序補齊；無識別碼時維持預設之「最早 2 張＋最新 6 張」
  - 保持嚴格時間遞增順序，確保模型的 `source_photo_index` 精準映射回真實的 `source_photo_id`
- ✓ **細緻化欄位溯源與證據自動套用（`_auto_decision` / `_field_provenance_details`）**：
  - 新增 `FieldProvenance` 資料結構，記錄最後人工修改時間、事件序號與歷史拒絕/復原值清單
  - 辨別真正的新證據：比對照片拍攝時間與 ULID 事件先後順序；只有在使用者修改**之後**新增的照片才視為新證據
  - **輔助信心門檻（`confidence >= 0.90`）**：新照片不得僅因「照片較新」就盲目覆寫使用者人工修正；使用者編輯過的 brand / model / attributes 需「新證據＋模型自報信心 >= 0.90」才允許自動套用，否則留待人工確認（`pending`）。此門檻僅是輔助條件，**不證明**照片證據充分（程式無法獨立驗證視覺內容；自報信心過往實測無鑑別力）
  - **先前自動套用可修訂**：先前由系統自動套用（`state == "auto"`）的欄位，重新分析時允許自動更新為新詮釋（可復原）
  - 尊重使用者品名自訂（S2 命名偏好）：若使用者已手動填寫名稱，新提案不強制覆蓋，保留為 `pending` 供人工確認
  - 歷史拒絕防護：曾被使用者手動拒絕或撤回的值，嚴禁再次**自動**套用（新照片存在或信心再高亦然）；有新證據支持時允許再次提出，但僅進入待確認清單
  - 歷史取用順序與上限：`build_analysis_context` 取最近各類配額（拒絕 8／已採納 8／已取代 4）；`_field_provenance_details`／分析上下文改以最新紀錄優先讀取（`newest_first`），建議總數超過上限時不漏掉新的拒絕／撤回
- ✓ **測試覆蓋 +24（`tests/test_ai_analyze.py` 20＋`tests/test_analyze_item.py` 2＋`tests/test_repo_suggestions.py` 2）**：
  - 重新分析上下文包含完整歷史、識別碼與歷次建議
  - 上下文精確區分自動套用、使用者採納、Undo 撤回與明確拒絕
  - 初次辨識錯誤後使用者修正，追加新照片後 AI 善用修正歷史
  - 新照片證據達輔助門檻（confidence >= 0.90）支持更新舊判讀並可復原
  - 新照片證據不足（confidence < 0.90）時保留使用者修正，維持 pending
  - 舊照片重新分析時，先前 AI 自動套用之身分允許自動修訂並可復原
  - 歷史衝突與曾被拒絕值之安全防護
  - 大量照片（>8 張）下多個識別碼分散在不同照片均能保留，且來源照片索引映射精準
  - 識別碼照片超出 5 張配額時之確定性取捨
  - 外部工具 adapter 之上下文注入與邊界限制驗證
  - 歷史取用順序與上限：超過配額與 500 筆窗口時，最近的拒絕／採納／取代／撤回仍被選入且防護生效
  - 拒絕語意：舊證據不盲目重複、新證據可再次提出（僅待確認）、拒絕值永不自動覆寫主表
  - 照片上限：所有 `max_photos` 下回傳張數不超過上限（含 2／3 邊界），預設 8 張識別碼保留與索引映射不變
- ✓ 全 1107 pytest 測試完全通過，無迴歸

### capture 建檔流程修正：確認儲存才建立正式紀錄 ← **COMPLETED**

完成時間：2026-10-11  
基準：`36684a8`（工程文件清理後）

修正內容：
- ✓ **問題**：capture 在 AI 分析前就呼叫 `api.intake()`（`/api/inbox/intake` 會建立正式紀錄並歸檔照片），取消操作只清前端圖片網址——使用者未確認儲存就留下正式紀錄
- ✓ **草稿分析**：新增 `POST /api/inbox/analyze`——對 inbox 暫存照片跑同一條 AI 管線（節流、設定、>8 張取「最早 2＋最新 6」），**不建立任何紀錄**；`source_photo_index` 對應請求順序
- ✓ **存起來才建檔**：第一次按「✓ 存起來」才呼叫 intake 建立正式 Item／photos；AI 草稿此時落成正式建議（`POST /api/items/{id}/suggestions`，帶 model／confidence／來源照片追溯）再逐筆接受
- ✓ **取消清理**：新增 `POST /api/inbox/discard`（只清 inbox/ 子樹、冪等、不碰資料庫）；已建檔後放棄走既有 void＋purge 清乾淨；離開頁面也清掉未消化的暫存
- ✓ **上傳回應帶 `staged`**：標記本次實際落盤的檔案，清理只針對自己的暫存（`InboxUploadListing`）
- ✓ **重試防重複**：intake 只跑一次；已建立的建議以 `createdSuggestionIds` 追蹤；已套用草稿以 index 追蹤；重複 intake 因暫存已消化而 404（不重複建檔）
- ✓ **AI 失敗不擋儲存**：草稿分析失敗（無 key／provider 錯誤）回 400，審閱照常、手動填寫照樣存檔
- ✓ **規劃清理**：相機記憶卡大量照片匯入（`/unsorted`）自 ROADMAP 與產品文件移除（非已確認需求；多張選取／拍照／上傳／追加照片功能不受影響）
- ✓ 測試 +10（test_capture_ui.py 9＋test_v3_core_slice.py 1）：草稿不建紀錄、選擇政策與索引映射、路徑守衛、discard 冪等、取消端到端零殘留、延遲建檔端到端（含來源照片追溯）、重複 intake 防護、靜態接線檢查
- ✓ 全 1083 測試通過；`node --check` 全 web JS 通過

### UX 手機優先修整 ← **COMPLETED**

完成時間：2026-10-11  
Commit：`e86f6ee` refactor: mobile-first UX refinement（已推送）  
基準：`de4922d`（Phase 3 垃圾桶完成後）

完成內容：
- ✓ **首頁簡化**：移除浮動快門按鈕、長標題與副標語；垃圾桶入口改為低視覺權重文字連結
- ✓ **詳情頁資訊優先**：移除頁首狀態標籤、卡片底部重複返回鍵；簡化 header 結構
- ✓ **i18n 完整性**：新增 `home.recordsTitle` 與 `home.recordCount` key 區分紀錄數；設定頁移除硬編碼英文
- ✓ **CSS 收斂**：移除浮動按鈕相關樣式；調整 container padding-bottom；新增語意化 classes（`.header-breadcrumb`、`.detail-meta`）
- ✓ **文件更新**：DESIGN-SYSTEM.md 和 UX-DESIGN.md 移除過時浮動快門描述、更新示意圖
- ✓ **測試驗證**：全 1073 pytest 通過、JS 語法檢查通過、無迴歸
- ✓ **工程指引修正**：AGENTS.md 和 AGENT_GUIDE.md 更新為標準交付流程（實作→測試→commit→推送），移除「待指示」條款

### Phase 3：垃圾桶與刪除 ← **COMPLETED**

完成時間：2026-10-11  
Commit：`de4922d` feat: phase-3 trash lifecycle（已推送）  
基準：`5896562`（serial inspect / edit semantics 修正後）

完成內容：
- ✓ **移至垃圾桶（軟刪除）**：沿用既有 `void` 機制（零 schema migration、無 `deleted_at` 欄位）；詳情頁「移至垃圾桶」附說明性確認（會隱藏但資料保留）；記錄 `field.changed`（狀態 → void）
- ✓ **預設列表排除**：`repo.list_items` 未指定 `status` 時一律排除 void（首頁與一般搜尋不再顯示）；`archived` 仍留在預設檢視；垃圾桶以 `status='void'` 查詢（`GET /api/items?status=void`，帶縮圖）
- ✓ **還原**：`POST /api/items/{id}/restore`；移入前狀態由事件歷史推導（最近一次「status → void」的 prev_value），active／archived 皆能正確還原；歷史不可靠時安全預設 `active`（有測試）；反覆移入→還原以最近一次為準
- ✓ **永久刪除**：`DELETE /api/items/{id}`（僅限垃圾桶，active/archived 回 400）；單一交易清除 items／observations／photos／identifiers／suggestions 與全部相關 events（含已刪子項的 json payload 補掃）；外鍵 RESTRICT 為最後防線
- ✓ **檔案清理安全**：照片目錄交易提交前先可逆改名至 `.purge/`（被鎖住→中止且資料庫零變更）；提交後才真正移除暫存目錄與 `evidence/<id>/`；刪不掉的檔案回 500（`PurgeError`）並列出完整路徑 —— 不假裝完整刪除；照片路徑不在 `files/<id>/` 底下時拒絕刪除
- ✓ **編號不回收**：`schema_meta.items_seq` 於配發與 purge 時記錄（零 DDL；舊庫自動由 items 最大值補齊），永久刪除後新紀錄不會重用舊編號
- ✓ **無自動清理**：不新增定期排程清除；備份保留／prune 機制未動；備份快照不會被永久刪除觸及（UI 訊息明示）
- ✓ **前端**：`/trash` 垃圾桶頁（還原／永久刪除＋二次確認、空狀態）；首頁 🗑 入口；詳情頁移至垃圾桶（void 時隱藏）；`web/core/api.js` 4 個方法；繁中＋英文 i18n；`.trash-view`／`.trash-item`／`.btn-mini-danger` 樣式
- ✓ **測試 +21**：repo×13（預設排除、還原原狀態／預設值／事件、purge 全清、路徑守衛、鎖檔零副作用、刪檔失敗回報、編號不回收）＋API×6（端點、400/404、500 診斷、children/files 全清）＋V3×2（端到端驗收＋前端接線靜態檢查）；更新 1 個既有契約測試（void 搜尋行為反轉，依產品要求）
- ✓ 全 1073 測試通過；`node --check` 全 web JS 通過；pyflakes 無新增警告（2 個既有警告與本階段無關）

### SR-2 資源上限、資訊衛生與列印安全（前序；已完成）

完成時間：2026-10-10  
Commit：`547a522` feat: sr-2 resource limits, caching hygiene, and print pipeline hardening（已推送）
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
Commit：`24d1909` feat: sr-1 host/origin guard, key forwarding fix, lan opt-in, media hardening（已推送）
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
| 描述性 `attribute:*`（非購買類） | 空值自動填入；`auto` 來源可自動修訂；使用者動過 → 僅「新證據＋自報信心 >= 0.90」可自動修訂，否則確認 |
| 購買資訊（vendor/amount/price/purchase_date… ） | 僅「現值為空＋使用者未動＋同一張照片也提供身分資訊」自動；否則衝突確認 |
| `name` | 空值自動填入；`auto` 來源可自動修訂；使用者設定的非空品名 → 永遠確認（不自動覆蓋） |
| `brand`／`model` | 空值自動填入；`auto` 來源可自動修訂；使用者編輯／確認／復原後，僅「修改後追加的新照片證據＋自報信心 >= 0.90」可自動修訂，否則確認 |
| `identifier:*`、`category`、`condition`、`notes` | 永遠待確認（T0／T2） |
| 矛盾值（同一輪同欄位不同值） | 全部轉衝突確認 |
| 無來源照片 | 不自動（沒有可追溯證據） |
| 與現值相同 | 直接丟棄（不佔建議） |
| 曾被拒絕／撤回的值 | 永不自動套用；有新證據時可再次提出，僅進入待確認 |
| 信心值 | 輔助門檻（僅用於「使用者編輯過欄位的新證據修訂」；不證明證據充分，其餘規則不看信心） |

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
| 測試檔案數 | 41 | conftest＋39 個 test_*.py＋__init__（本階段新增 test_capture_inputs.py） |
| 總測試數 | 1199 | 1196 基線；裝置文案掛載修正 +3 |
| 通過 | 1199 ✓ | 100% pass rate |
| 失敗 | 0 | 零失敗 |
| 跳過 | 0 | 無跳過（本機有 Chromium／PyMuPDF／node，列印、canary 與 JS 邏輯測試皆實跑） |
| 覆蓋率 | 未測 | 建議後續補充 |

**測試框架**：pytest（可選 pytest-cov 補充覆蓋率）

**主要測試分類**：
- API 端點：test_api.py (88), test_phase8a_api.py (35), test_settings_api.py (43) 等
- 資料庫 & Repo：test_repo_*.py (13-23 each), test_db_transactions.py (8)
- AI & 分析：test_ai_*.py (15-78), test_analyze_item.py (78)
- 前端與 UI：test_capture_ui.py (6), test_inbox_ui.py (35)
- 列印：test_print.py (31), test_print_settings_api.py (20)
- **V3 核心驗收**：test_v3_core_slice.py (20) —— 原始 5 情境 + 各階段驗收（1B-A／2A／2B／2C-B／2C-D／Phase 2 編輯介面／Phase 3）
- **評測 harness**：test_evaluate_models.py (7)、test_validate_autonomy_live.py (2) —— 離線守門（不碰網路）
- **安全（SR-1）**：test_security.py (17) —— Host／Origin／自訂標頭、key 不轉送（canary＋接收器）、綁定 opt-in、媒體標頭、CSP/escaping 靜態守門
- **安全（SR-2）**：test_security_sr2.py (30) —— body／單檔／檔數／像素／列印尺寸上限、AI 節流、docs 開關、快取政策、錯誤訊息去路徑化、註解／實體 mXSS、render-time 驗證、sandbox 命令、raster MIME、真實 Chromium canary PDF

**最近運行**：2026-10-12，`pytest` → 1199 passed，failures=0，exit=0（本階段：裝置文案掛載修正 +3）

---

## 已完成功能

使用四層狀態區分：

| 狀態 | 定義 | 範例 |
|---|---|---|
| **Implemented** | 程式碼存在且功能可用 | SQLite schema, FastAPI endpoints, V3 前端已實作 |
| **Tested** | 實作已驗證，測試通過 | 1083 個 pytest 全通過，V3 core slice test 驗收 |
| **Committed** | 變更已進入版本控制 | main branch 上的所有程式碼 |
| **Pushed** | 變更已推送到遠端 | origin/main 的最新狀態（本地與遠端同步） |

### 核心產品體驗
- ✓ 手機隨手拍照 (Capture) — **Implemented, Tested, Committed, Pushed**
- ✓ 拍照與相簿／檔案匯入雙入口（含 HEIC 明確提示） — **Implemented, Tested, Committed, Pushed**
- ✓ AI 自動整理與建議 — **Implemented, Tested, Committed, Pushed**
- ✓ 超低摩擦確認（一鍵存起來） — **Implemented, Tested, Committed, Pushed**
- ✓ 紀錄詳細檢視與大圖展示 — **Implemented, Tested, Committed, Pushed**
- ✓ 即時文字 & 序號搜尋 — **Implemented, Tested, Committed, Pushed**
- ✓ 隨手追加照片與筆記 — **Implemented, Tested, Committed, Pushed**
- ✓ V3 前端（Capture/Home/Detail/Settings 完整實作） — **Implemented, Tested, Committed（2879904）, Pushed**
- ✓ 首頁最新紀錄置頂與保存後回首頁（Phase 1B-A） — **Implemented, Tested, Committed（98edc0c）, Pushed**
- ✓ AI 建議生命週期與部分失敗語意（Phase 2A） — **Implemented, Tested, Committed（15f2e9b）, Pushed**
- ✓ 證據累積與情境式重新理解（Phase 2B） — **Implemented, Tested, Committed（22b0c22）, Pushed**
- ✓ AI 評測 harness 與自主性政策（Phase 2C-A；工具＋文件，未改產品行為） — **Implemented, Tested, Committed（dda8b61）, Pushed**
- ✓ 可回復的 AI 自動更新（Phase 2C-B：選擇策略、自動套用、undo、衝突升級） — **Implemented, Tested, Committed（7927faf）, Pushed**
- ✓ 自主性驗證與殘餘缺口（Phase 2C-C：Live 實測、報告、fixture／錄製） — **Evaluated, Committed（5a4c792）, Pushed**
- ✓ 撤銷安全、描述性理解與衝突處理（Phase 2C-D） — **Implemented, Tested, Committed（79eaecc）, Pushed**
- ✓ 桌面應用安全稽核（Security Audit 1；唯讀） — **Audited, Committed（3e002d2）, Pushed**（F1–F8 見 SECURITY-AUDIT.md）
- ✓ SR-1 安全修復（Host/Origin＋標頭、key 不轉送、LAN opt-in、媒體硬化、前端 escaping） — **Implemented, Tested, Committed（24d1909）, Pushed**
- ✓ 垃圾桶與刪除（Phase 3：移至垃圾桶／還原／永久刪除、預設列表排除、檔案與事件全清、無自動清理） — **Implemented, Tested, Committed, Pushed**

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

### 立即待做
- Phase 3 垃圾桶與刪除已完成。**本輪刻意不含 30 天自動清理**——避免在垃圾桶與還原行為尚未經實際使用確認前，讓不可逆的排程自動刪除資料；未來要做需先定案
- 收尾選項（可穿插）：R 型跨照片身分的下一輪評測；屬性逐鍵來源標籤；Phase 1B-B

### 安全後續（F4／F7／F8）— SR-2 已完成
- F4：body／單檔／檔數／像素／列印尺寸上限、analyze 節流（單行程；多 worker 限制已文件化）
- F7：`/docs` 預設關閉（`enable_docs`）、錯誤訊息去路徑化、`Cache-Control: private`／`no-store`
- F8：列印輸出重新序列化（註解丟棄＋文字 escape＋屬性白名單＋render 前重驗）；sandbox 預設保留
- 殘餘（已知）：列印瀏覽器 JS 引擎仍啟用（防線在「輸出不含可執行內容」）；單行程節流重啟歸零；未對 HTML 解析器差異做 fuzzing

### 短期（Phase 2–3）
- Phase 2：AI Contract 2.0 —— **完成（2A/2B/2C-A/2C-B/2C-C/2C-D）**
- Phase 3：垃圾桶與刪除 —— **完成（移至垃圾桶／還原／永久刪除；30 天自動清理未做，見「立即待做」）**

### 中期（Phase 4–6）
- 分類系統與 AI 自動分類（Phase 4）
- SQLite FTS5 全文搜尋、繁簡互搜（Phase 5；未採納未排程，現行 LIKE）
- 外觀比對器（Compare）完善（Phase 6）

### 長期（Phase 7）
- 同一物品匹配（重複紀錄識別）
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
| 模型自報信心無鑑別力 | 低 | 已驗證（全場 0.9~1.0） | 不作主要依據；僅在「使用者編輯過欄位的新證據修訂」作為保守輔助門檻（>= 0.90），不代表證據已被獨立驗證 |
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

## SR-2 變更清單（commit `547a522`）

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
| Ahead/Behind | 0 ahead, 0 behind（本階段 commits 已推送） |
| Uncommitted Changes | 0（所有變更已 commit 並 push） |
| 衝突 | 無 |
| 先前 checkpoint | `2879904`、`4318ae0`、`6bfdeda`、`98edc0c`、`ef85450`、`15f2e9b`、`22b0c22`、`dda8b61`、`7927faf`、`5a4c792`、`79eaecc`、`3e002d2`、`24d1909`、`547a522`、`e57f9ef`、`5896562` —— 未修改、未 amend、未 rebase |

---

## 下一個明確任務

### Phase 4：分類系統與 AI 自動分類
檢查清單：
- [ ] 分類欄位設計與 schema 更新
- [ ] 分類 API 端點
- [ ] 前端分類 UI
- [ ] AI 自動分類提案
- [ ] 測試與回歸驗證

（收尾選項可穿插：R 型跨照片身分的下一輪 prompt 評測；屬性逐鍵來源標籤；Phase 1B-B；生活備忘欄位設計。）

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
- **2026-10-11**：Phase 3 垃圾桶與刪除完成——移至垃圾桶（沿用 void、零 migration）＋首頁／搜尋預設排除＋垃圾桶頁（還原至移入前 active／archived，歷史不可靠時安全預設 active）；永久刪除（僅限垃圾桶、單一交易清 DB 與事件、可逆改名後清檔案、刪檔失敗 500 列出路徑不假裝成功、路徑守衛、編號不回收）；無自動清理、備份機制未動；`/trash` UI＋繁英 i18n；測試基線 1052 → 1073（+21；另更新 1 個既有契約測試）
- **2026-10-11**：UX 手機優先修整完成——首頁移除浮動快門、簡化 hero section；詳情頁移除狀態標籤、重組 DOM；新增 i18n keys 區分紀錄數／照片數；收斂 inline styles 到 CSS classes；設定頁完整 i18n 化；AGENTS.md＋AGENT_GUIDE.md 更新為標準交付流程；測試基線維持 1073；commit `e86f6ee` 已推送至 origin/main
- **2026-10-11**：工程文件清理完成——修復本檔 UTF-8 編碼損壞（UTF-16 尾端併回 UTF-8）；AGENTS／AGENT_GUIDE 移除停工式規則（同步門檻／整 Phase 才可提交／額外工作即停工等待指示／文件任務強制完整回歸），改為風險導向測試與「調查→修復→驗證→繼續」；ROADMAP 合併重複的兩代 Phase 規劃，垃圾桶與資料生命週期標記完成（`status='void'`＋還原＋使用者明示永久刪除，無自動過期）；DECISIONS 校準 D2/D3/D4/D5、O1/O5 結案、新增 D11（文件效力範圍與已取消 UI 清單）；SPEC-v1 標記為歷史規格；product-v3 定位為參考文件（README），已取消 UI 註記於相關文件；測試基線維持 1073（本輪純文件變更，僅執行文件／編碼檢查）
- **2026-10-11**：capture 建檔流程修正——「確認儲存才建立正式紀錄」：審閱階段改用新端點 `POST /api/inbox/analyze`（草稿分析，零持久化），「存起來」才 intake 建立 Item／photos 並把 AI 草稿落成正式建議（create→accept，保留 model／來源照片追溯）；取消／離開以新端點 `POST /api/inbox/discard` 清理本次暫存（冪等、只限 inbox/ 子樹），已建檔後放棄走 void＋purge；重試與重複點擊不重複建檔（intake 單次＋建議追蹤＋暫存消化後 404）；AI 失敗不擋手動儲存；`/unsorted` 記憶卡大量匯入自規劃移除；測試基線 1073 → 1083（+10）
