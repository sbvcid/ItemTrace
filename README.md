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

1. 用文字編輯器打開 `config.json`，把 `server_host` 改成 `"0.0.0.0"`
2. 重新啟動 `python serve.py`
3. 手機連到**同一個 Wi-Fi**，瀏覽器打 `http://<電腦的IP>:8731/`

   查電腦 IP：Windows 在命令提示字元執行 `ipconfig`，看「IPv4 位址」。

> `0.0.0.0` 代表監聽所有網路介面，**同一個區網內的任何人只要知道網址就能連進來，
> 而且沒有密碼**。這是設計給自己家裡用的，不要放在公開的網路或路由器轉發出去的環境。
> 用完記得改回 `127.0.0.1`。

### 頁面

| 網址 | 用途 |
|---|---|
| `/` | Inbox：上傳照片 → 依拍攝時間分組 → 選一組建檔 |
| `/items` | 商品列表：搜尋、狀態／分類篩選 |
| `/items/<item-id>` | 商品詳細：照片牆、建議、欄位、識別碼、歷史、復原 |
| `/docs` | API 文件（Swagger UI） |

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
| `server_host` | `127.0.0.1` | 改成 `0.0.0.0` 才讓手機連得進來 |
| `server_port` | `8731` | 連接埠 |

`config.example.json` 是樣板，`init` 會由它產生 `config.json`。

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
看過、按接受才會生效。

第一次使用：

1. 複製 `tools/ai_config.example.json` → `tools/ai_config.local.json`
2. 把 `api_key` 換成自己的 OpenRouter API key
3. `model` 不填就用預設值，也可以改成自己確認過的**免費**模型
4. 執行：`python tools/analyze_item.py ITM-0001`

`tools/ai_config.local.json` 已被 `.gitignore` 排除，不會被 commit。
這支腳本只從這個檔案讀憑證，不使用環境變數，也不共用其他工具的 key。

## 舊概念驗證程式
v1 之前的概念驗證版本（交易紀錄）**已從 repo 移除**，v1 不需要它們。

其中出貨單的排版技術 —— SPEC-v1 §9 指名要保留的可攜資產 —— 現已單獨放在
[`prototype/shipping/`](prototype/shipping/)，個人資料全部改為 placeholder。
