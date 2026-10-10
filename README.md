# 商品證據與歸檔工具

local-first 的商品紀錄系統。出貨前把實體商品建成一份可信的數位紀錄：原始照片、
外觀狀況、序號等識別碼，以及這些資訊是**從哪裡來的**。日後對方說「這不是我寄的那個」，
你手上有東西可以反駁。

**v1 不含 AI**。商品欄位只放人工確認過的值；外部辨識工具（自己寫的 Vision 腳本、
Claude Code、任何程式）只能寫「建議」，要有人按下接受才會進正式欄位。核心程式不會
呼叫任何模型。

規格見 [SPEC-v1.md](SPEC-v1.md)。

## 需要什麼

* Windows / macOS / Linux
* Python 3.11 以上（[python.org](https://www.python.org/downloads/) 安裝時記得勾選
  **Add Python to PATH**）
* 一支手機（同一個 Wi-Fi）

## 開始使用

```bash
pip install -r requirements.txt   # 只有 HTTP 層需要，依賴 FastAPI
python shopctl.py init            # 建立 config.json 與 catalog.db
python serve.py                   # http://127.0.0.1:8731/
```

`init` 可以重複執行，不會清掉既有資料。啟動後打開
**<http://127.0.0.1:8731/>** 就是 Inbox 頁。

Windows 也可以直接雙擊 **`啟動 ItemTrace.bat`**，它會依序做上面三件事。

### 用手機連進來

服務預設只綁 `127.0.0.1`，只有本機連得上。要讓手機連：

1. 用文字編輯器打開 `config.json`，把 `server_host` 改成 `"0.0.0.0"`，
   並加上 `"allow_lan": true`
2. 重新啟動 `python serve.py`
3. 手機連到**同一個 Wi-Fi**，瀏覽器打 `http://<電腦的IP>:8731/`

   查電腦 IP：Windows 在命令提示字元執行 `ipconfig`，看「IPv4 位址」。

> `0.0.0.0` 代表監聽所有網路介面，**同一個區網內的任何人只要知道網址就能連進來，
> 而且沒有密碼**。這是設計給自己家裡用的，不要放在公開的網路或路由器轉發出去的環境。
> 用完記得改回 `127.0.0.1`。
>
> 因為沒有登入機制，**開放區網必須是明示的選擇**：`server_host` 不是 loopback
> 而沒有設 `"allow_lan": true` 時，`serve.py` 會拒絕啟動並印出說明 —— 不會
> 無聲地把資料開放出去。信任區網的前提是「網路上只有你信任的裝置」，這件事
> 不能取代登入。

### 頁面

| 網址 | 用途 |
|---|---|
| `/` | Inbox：拍照與上傳照片 → 依拍攝時間分組 → 選取建檔 |
| `/items` | 商品列表：搜尋、狀態／分類篩選 |
| `/items/<item-id>` | 商品詳細：個人物品檔案、照片牆、AI 輔助建議、識別碼、修改歷史、**列印** |
| `/settings` | AI 辨識設定（Gemini / OpenRouter / Custom） |
| `/settings/printing` | 列印設定（預設印表機／範本）與**範本管理** |
| `/docs` | API 文件（Swagger UI） |
| `/design` | UI Showcase / visual reference（UI 基準頁） |

### Architecture

```text
Browser / Phone
    ↓ (HTTP)
ItemTrace server (FastAPI)
    ├── repository / persistence (SQLite + files/ + inbox/)
    ├── evidence (read-only bundle: item / observations / identifiers / events / photos / manifest)
    ├── template rendering (HTML/CSS → headless Chromium → PDF)
    ├── printing (PDF → win32print / GDI → Windows printer)
    └── optional AI adapter (external producer; suggestions only, not source of truth)
```

Evidence Export is **read-only output** from the server; it never modifies DB, creates events, or updates item status. Print sends PDF to the Windows print backend running on the same computer. AI suggestions are validated by the user before being written to item fields.

### 語言（繁體中文 / English）

UI 可以用繁體中文或 English 顯示。所有主要頁面右上角 topbar 均提供語言控制（中文 | EN），選擇後立刻套用到整個畫面。

* 預設語言是 **繁體中文**。
* 選擇記在瀏覽器 `localStorage["itemtrace.locale"]`，**只存語言偏好**：
  不寫進資料庫、不送到 server、不存 API key 或商品資料，所以換裝置就是
  各自的選擇，也**不需要重啟 server**。
* 切換只翻 **UI**（標題、欄位 label、按鈕、錯誤訊息、空狀態、placeholder、
  日期格式）。**商品資料不翻**：商品名稱、品牌、類型、狀態、備註，以及
  Template 裡的文字，都是你自己的內容，兩種語言下都原樣顯示。

翻譯全部集中在 **`ui/i18n.js`** 這一支檔案（純物件，沒有 build step、
沒有 npm、沒有前端框架）：

| 做法 | 說明 |
|---|---|
| `t("common.save")` | 頁面 script 產生動態文字 |
| `data-i18n="common.save"` | markup 的靜態文字 |
| `data-i18n-placeholder` / `-title` / `-aria-label` | placeholder、title、aria-label |
| `i18nSwitch("en")` | 切換語言（會重新套用 markup 並通知訂閱者） |
| `i18nFormatDateTime(iso)` | 日期時間跟著語言格式化 |

| 語言 | key 數 |
|---|---|
| Language `zh-TW` | 352 |
| Language `en` | 352 |

兩邊的 key 必須完全一致（`tests/test_i18n.py` 會驗）。查不到 key 時的
fallback 是 **目前語言 → `zh-TW` → key 本身**，並在 console 警告：畫面會
顯示 `item.foo_label` 這種明顯不是翻譯的字串，但**不會讓整頁 JS 初始化
失敗**。

新增或修改 UI 文字的流程：先在 `ui/i18n.js` 的兩個語言都加 key，再用
`t()` 或 `data-i18n` 引用，最後補 `tests/test_i18n.py` 的對應檢查。

## 列印標籤

列印功能分成兩個地方：

**`/settings/printing`（設定 → 列印）** 負責長期設定與範本管理：

- 列印設定：預設印表機、預設範本（存進 `tools/print_config.local.json`）
- 範本管理：新增、編輯、預覽、移除

**商品頁** 只保留三個操作：範本替換 → 更新預覽 → 列印。

在商品頁按 **［列印］**，對話框裡有：

- **列印預覽** —— 就是送進 PDF 的那一份 HTML，所以看到的就是會印的
- **範本** —— 預設帶入設定裡的預設範本；切換會重新取得預覽（不修改範本本身）
- **印表機** —— 來自 `/api/printers`，預設帶入設定裡的預設印表機
- **［列印 1 份］** —— 固定 1 份

只有預覽內容會印出來；網頁上的商品資訊、按鈕、範本選擇區都不在標籤上。
沒有印表機、印表機清單讀取失敗、或列印預覽載入失敗時，對話框會直接顯示原因，
不會留一片空白。

手機操作流程相同（手機 → ItemTrace → 商品 → 列印 → 選範本 → 看預覽 → 列印）。
印表機清單來自**跑 server 的那台電腦**，不是手機自己的；長期設定在手機上也能改
（列印設定不含機密，與商品資料同一個信任模型）。

實際輸出尺寸等於 Template 自己的 `width` / `height`（例如 TPL-0002 是
100 × 150 mm），不會被縮放成印表機的預設紙張。

列印走的是 headless Chromium 的排版引擎，跟畫面上的預覽同一套排版，
所以照片、文字、空欄位、data-bind 替換結果都與預覽一致。

需要的額外依賴（`pip install -r requirements.txt` 已包含，缺了也不影響
其他功能，只是列印會回 400 並說明原因）：

| 需求 | 說明 |
|---|---|
| Chrome 或 Edge | 排版引擎。Windows 10/11 內建 Edge，通常不用另外裝 |
| PyMuPDF | 校正 PDF 頁面尺寸為精確 mm 並光柵化 |
| pywin32 | 送列印工作到 Windows 印表機 |

瀏覽器位置可以用 `ITEMTRACE_BROWSER` 覆寫：

```powershell
$env:ITEMTRACE_BROWSER = "D:\Browser\chrome.exe"
```

## Evidence Export（證據匯出）

單一商品的完整讀取-only 證據 bundle，可帶走、保存、交付：

```text
GET /api/items/{item_id}/evidence/export
→ JSON manifest (format / version / item_id / generated_at / files[])
```

Bundle 內容（不建立第二套資料來源，直接從現有表 / 檔案複製）：

```text
item.json
observations.json
identifiers.json
events.json
photos/          ← 原始照片 bytes 完整複製（無重新壓縮）
manifest.json     ← file path / sha256 / size（manifest 自身用 baseline hash）
```

下載單一檔案：

```text
GET /api/items/{item_id}/evidence/export/file?path=manifest.json
```

特性：

* **Read-only**：不修改 DB、item 狀態、event、照片 metadata、timestamp
* **完整性**：manifest 對每個 exported file 計算 `sha256` + `size`；照片 bytes 與原始 `files/` 一致
* **路徑安全**：禁止 `..`、絕對路徑、反斜線
* **空資料可成功**：無 observations / identifiers / events / photos 時輸出空 array，但不失敗
* **不存在 Item**：回傳現有一致的 404

UI：商品頁提供 `[匯出證據]` 按鈕；點擊後顯示產生時間與檔案摘要，並提供下載連結。

## 離線工具

| 指令 | 用途 |
|---|---|
| `python shopctl.py init` | 建立 `config.json` 與資料庫（可重複執行） |
| `python shopctl.py stats` | 各表筆數 |
| `python shopctl.py verify` | 完整性檢查：找出有記錄但檔案不見的照片 |
| `python shopctl.py backup` | 完整快照到 `backups/` |

## 測試

```bash
python -m pytest                     # 全套
python -m pytest -q tests/test_api.py  # 只跑 API
python -m pyflakes shop tools tests   # 靜態檢查（選裝）
node --check ui/item.js               # JS 語法（有 node 才需要）
```

測試各自使用暫存 DATA_ROOT，不會碰到你的資料。

## DATA_ROOT 與 config.json

`config.json` 決定資料放在哪（預設就是專案目錄本身）：

| 欄位 | 預設 | 說明 |
|---|---|---|
| `data_root` | `.` | 所有資料的根目錄 |
| `database` | `catalog.db` | SQLite 檔名（WAL 模式） |
| `backup_dir` | `backups` | 快照放置位置 |
| `backup_keep` | `30` | 保留最近幾份快照 |
| `server_host` | `127.0.0.1` | 綁定位址；非 loopback 必須同時設 `allow_lan` |
| `allow_lan` | `false` | 明確開放區網（沒有登入機制，請只在受信任網路開啟） |
| `allowed_hosts` | `[]` | 額外允許的 Host 名稱（例如自訂主機名） |
| `enable_docs` | `false` | 開發用：開啟 `/docs` 與 `/openapi.json`（預設關閉） |
| `max_request_bytes` | `33554432` | 單次 HTTP 請求 body 上限（32 MiB） |
| `max_upload_bytes` | `25165824` | 單一上傳檔案上限（24 MiB） |
| `max_upload_files` | `20` | 一次請求最多幾個檔案 |
| `max_image_pixels` | `50000000` | 單張圖片像素上限（50 MP，防解壓縮炸彈） |
| `analyze_per_minute` | `10` | 每分鐘 AI provider 呼叫上限（0＝停用節流） |
| `server_port` | `8731` | 連接埠 |

`config.example.json` 是樣板，`init` 會由它產生 `config.json`。

### 本機安全防護（SR-1）

沒有登入系統的桌面應用，防的是「瀏覽器替攻擊者送請求」：

* **Host 白名單**：只接受 loopback 位址／名稱與設定中的 `allowed_hosts`；
  其他 Host（DNS rebinding 的網域）一律 403
* **Origin 驗證**：請求帶 Origin 時，其主機與埠必須與請求一致
* **自訂標頭**：變更類請求（POST／PATCH／PUT／DELETE）必須帶
  `X-Requested-With: ItemTrace`（ItemTrace 網頁會自動附加；用 curl 或
  腳本時請自己加）——外部網頁帶不了自訂標頭，跨站簡單請求因此被擋下
* **媒體安全**：`/files/*` 回應帶 `X-Content-Type-Options: nosniff` 與嚴格
  CSP；非圖片副檔名一律以附件下載（上傳的 HTML 不會以網頁執行）
* **AI key 不外送**：測試 API 時，已儲存的 key 只會送到已知 provider
  端點；自訂 base URL 必須在該次請求明確帶上臨時 key

### 資源上限與輸出衛生（SR-2）

第二輪安全強化（對應 `docs/engineering/SECURITY-AUDIT.md` 的 F4／F7／F8）：

* **請求與上傳上限**：body、單檔、檔數、圖片像素都在落盤前擋（413／400）；
  超限時**先前已成功的檔案保持不變**，不會靜默丟掉合法證據。數值可由
  config.json 調整（見上表）。
* **AI 呼叫節流**：`analyze` 與「測試 API」共用每分鐘 10 次的滑動視窗（429＋
  `Retry-After`）。這是**單一行程**的計數器；本應用正常只有一個 worker，
  若未來改用多 worker，每個行程各有自己的視窗。
* **列印尺寸上限**：Template 尺寸換算後的光柵像素超過 60 MP 就直接 400，
  不啟動瀏覽器、不讓記憶體爆掉。
* **API 文件預設關閉**：`/docs`、`/openapi.json`、`/redoc` 預設 404；
  開發時在 config.json 設 `"enable_docs": true`。
* **快取政策**：API 回應 `Cache-Control: no-store`（含私人資料）；照片是
  `private, max-age`（只進自己的瀏覽器快取）；靜態資產維持正常快取。
* **列印管線硬化**：模板渲染重新序列化輸出（文字 escape、註解丟棄、屬性
  走白名單、渲染前重新驗證），列印瀏覽器**預設保留 sandbox**；只有環境
  真的起不來時才用 `ITEMTRACE_PRINT_NO_SANDBOX=1` 明確退回。

**整個資料夾就是全部資料**：`catalog.db` + `files/`（原始照片）+ `inbox/`。
關掉程式、整份搬到任何位置、重新啟動即可，不需改任何設定 —— 資料庫裡只存相對於
`data_root` 的路徑。

備份請用 `python shopctl.py backup`（SQLite 跑在 WAL 模式，直接複製檔案會漏資料）。
快照放在 `backups/shop-<時間戳>/`，整個資料夾複製回去就還原了。

### 照片的刪除語意

* **正常生命週期中**：`files/<item-id>/original/` 的照片不可覆寫，也不做日常刪除。
  歸檔時遇到同名檔會自動加流水號，永不蓋掉既有證據
* **`void` 只是狀態**：把商品移出日常清單而已，資料庫每一列與每個檔案都原封不動，
  隨時改得回來
* **永久淘汰由你明確決定**：判定某件商品永久不保留時，未來會允許一次性刪除該 Item
  及其所有相關資料與 `files/<item-id>/` 整棵目錄樹
* **不做自動過期**：不會有「滿一年自動清掉」之類的時間軸清理

衍生檔案（縮圖）在 `derived/`，可以整個刪掉重生。

## AI 辨識（選用，core 之外）

`tools/analyze_item.py` 是一支**外部**腳本：把商品照片送到 Vision 模型，
結果以 **pending 建議**寫回來。它不會動商品資料 —— 要人工在商品頁逐筆
看過、按接受才會生效。商品頁也有「AI 自動填入」按鈕，做的是同一件事
（server 端分析、結果一樣是 pending 建議）。

### 設定（用網頁）

1. 啟動 ItemTrace，開 **<http://127.0.0.1:8731/settings>**
2. 選 Provider（Google Gemini / OpenRouter / Custom）並填入 API key
3. Base URL 與 model（選預設 provider 會自動帶入；Custom 可填任何
   OpenAI 相容 API 的端點基址，例如
   `https://generativelanguage.googleapis.com/v1beta/openai/`）
4. 按「測試 API」確認連得上
5. 回到商品頁按「AI 自動填入」或執行 AI adapter

設定存在 **`tools/ai_config.local.json`** —— 那是後台實作細節，你平常
不需要碰它。也可以直接複製 `tools/ai_config.example.json` 改名成
`ai_config.local.json` 編輯。該檔案已被 `.gitignore` 排除，不會被 commit。

> **API key 不會離開這台電腦。** 任何 API 回應都不含 key，
> 頁面上的密碼欄每次載入都是空的。寫入（存檔／清除／測試）
> 開放給能連到這台 server 的裝置 —— server 刻意只服務受信任
> 區網（`server_host` + 防火牆），與「區網裝置本來就能讀寫所有
> 商品資料」的信任模型一致。若不信任區網，把 `config.json` 的
> `server_host` 改回 `127.0.0.1`。
>
> SR-1 之後，**「測試 API」不會把已儲存的 key 轉送到任意網址**：
> 已存的 key 只會送往 Google／OpenRouter 等已知端點；自訂 base URL
> 必須在同一張表單上輸入臨時 key 才能測試。

### 執行

```bash
python tools/analyze_item.py ITM-0001
```

## 舊概念驗證程式
v1 之前的概念驗證版本（交易紀錄）**已從 repo 移除**，v1 不需要它們。

其中出貨單的排版技術 —— SPEC-v1 §9 指名要保留的可攜資產 —— 現已單獨放在
[`prototype/shipping/`](prototype/shipping/)，個人資料全部改為 placeholder。
