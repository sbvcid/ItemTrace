# 商品證據與歸檔工具

local-first 的商品紀錄系統。**出貨前**把實體商品建成一份可信的數位紀錄 ——
原始照片、外觀狀況、序號等識別碼，以及這些資訊是從哪裡來的。日後對方說
「這不是我寄的那個」，你手上有東西可以反駁。

不是交易／金流／物流系統，不是退貨管理系統，不含任何 AI 呼叫。
規格見 [SPEC-v1.md](SPEC-v1.md)。

## 開始使用

```bash
pip install -r requirements.txt      # 只有 HTTP 層需要，依賴 FastAPI
python shopctl.py init               # 產生 config.json 與 catalog.db
python serve.py                      # http://127.0.0.1:8731/docs
```

手機連同一個區網，用瀏覽器開 `http://<電腦IP>:8731/` 就能上傳照片。

`shopctl.py` 是離線工具：

| 指令 | 用途 |
|---|---|
| `init` | 建立 `config.json` 與資料庫 |
| `stats` | 各表筆數 |
| `verify` | 完整性檢查（找出有記錄但檔案不見的照片） |
| `backup` | 完整快照（資料庫 + 檔案樹）到 `backups/` |

## 測試

```bash
python -m pytest          # 全套
python -m pytest -q tests/test_api.py    # 只跑 API
python -m pyflakes shop tests            # 靜態檢查（選裝）
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
| `server_host` / `server_port` | `127.0.0.1` / `8731` | 只綁本機；要讓手機連入要自己改成 `0.0.0.0` |

`config.example.json` 是樣板，`init` 會由它產生 `config.json`。

**整個資料夾就是全部資料**：`catalog.db` + `files/`（原始照片）+ `inbox/`。
關掉程式、整份搬到任何位置、重新啟動即可，不需改任何設定 ——
資料庫裡只存相對於 `data_root` 的路徑。備份請用 `shopctl.py backup`
（SQLite 跑在 WAL 模式，直接複製檔案會漏資料）。

原始照片放在 `files/<item-id>/original/YYYYMMDD-HHMMSS_<原始檔名>`，
永不覆寫、永不刪除。衍生檔案（縮圖）在 `derived/`，可以整個刪掉重生。

## 舊概念驗證程式

v1 之前的概念驗證版本（交易紀錄：`db.py`、`server.py`、`web/`、`*.bat`）
**已從 repo 移除**，v1 不需要它們。其中混入賣家個人的聯絡資訊與社群 QR，
不適合放在公開 repo。

唯一保留下來的是出貨單的排版技術 —— 那是 SPEC-v1 §9 指名要保留的可攜資產，
現已單獨放在 [`prototype/shipping/`](prototype/shipping/)，個人資料全部改為
placeholder。詳見該目錄的 README。