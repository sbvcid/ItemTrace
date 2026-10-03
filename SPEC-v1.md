# 商品證據與歸檔工具 — v1 規格

> local-first 商品證據與歸檔工具
> 個人賣家自用，非 ERP、非 SaaS、非退貨管理平台

---

## 0. 定位

**解決的問題**：出貨前，東西已經離開視線就無法再確認它的樣子。日後對方說「這不是我寄的那個」或「收到就是壞的」，你手上沒有任何東西可以反駁。

**解法**：寄出之前，把實體商品建成一份可信的數位紀錄 — 原始照片、外觀狀況、序號等識別碼、以及這些資訊是從哪裡來的。之後要查、要比對、要舉證，都從這份紀錄出發。

**不是什麼**：
- 不是交易／金流／物流系統（平台已處理）
- 不是退貨管理系統（退貨比對是附加用途）
- 不是 AI 產品（v1 不含任何 AI 呼叫）
- 不是給一般使用者的產品（技術人自行安裝修改）

**主要使用者**：本人一人。程式碼需乾淨可讀，讓其他技術人看得懂、能 fork 修改。

---

## 1. 設計原則

| 原則 | 具體要求 |
|---|---|
| **原始資料不可破壞** | 商品正常生命週期中 `original/` 照片永不刪除。日常的「刪除」用 `status='void'` 而非物理刪除。永久刪除只能由你明確決定後一次性執行（見 §2.3），**不做自動過期**。`derived/` 可重生 |
| **推論與事實分離** | AI／外部產生的值一律進 `suggestions`，主表只放已確認值。被拒的建議也保留 |
| **一切有來源** | 每個識別碼可追溯到來源照片；每次修改寫入 `events` 並保留前後值 |
| **資料夾自足** | 所有路徑相對於資料根目錄。整個資料夾可複製、搬移、備份後直接運作 |
| **可觀測** | 使用者隨時可問「這筆資料為什麼長這樣」— 透過 `events` |
| **AI 可後裝** | v1 零 AI 依賴，但資料模型與 API 已為 AI 接入預留（見 §13） |

---

## 2. 資料模型

### 2.1 實體關係

```
items 1 ──< observations 1 ──< photos
  │                              ↑
  └──< identifiers ──────────────┘ (source_photo_id)
  │
  └──< suggestions ──────────────┘ (source_photo_id)

events  ← 獨立，記錄所有寫入
```

### 2.2 DDL

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE items (
    id          TEXT PRIMARY KEY,              -- ITM-0001
    name        TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    condition   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    attributes  TEXT NOT NULL DEFAULT '{}',    -- JSON，擴充用
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','archived','void')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
) STRICT;

CREATE TABLE observations (
    id          TEXT PRIMARY KEY,              -- OBS-20261002-0001
    item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    kind        TEXT NOT NULL DEFAULT 'intake'
                CHECK (kind IN ('intake','recheck','manual')),
    note        TEXT NOT NULL DEFAULT '',
    captured_at TEXT,                          -- ISO8601，取自 EXIF 或手動
    created_at  TEXT NOT NULL
) STRICT;
CREATE INDEX idx_obs_item ON observations(item_id, captured_at);

CREATE TABLE photos (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    observation_id  TEXT REFERENCES observations(id) ON DELETE SET NULL,
    role            TEXT NOT NULL DEFAULT 'original'
                    CHECK (role IN ('original','derived')),
    filename        TEXT NOT NULL,             -- 相對於 DATA_ROOT
    orig_name       TEXT NOT NULL DEFAULT '',
    sha256          TEXT NOT NULL DEFAULT '',
    bytes           INTEGER,
    width           INTEGER,
    height          INTEGER,
    captured_at     TEXT,
    angle           TEXT NOT NULL DEFAULT '',  -- front|back|label|detail|...
    source          TEXT NOT NULL DEFAULT 'manual',
    created_at      TEXT NOT NULL
) STRICT;
CREATE INDEX idx_photos_item ON photos(item_id);
CREATE INDEX idx_photos_obs  ON photos(observation_id);
CREATE INDEX idx_photos_hash ON photos(sha256);

CREATE TABLE identifiers (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    kind             TEXT NOT NULL DEFAULT 'serial'
                     CHECK (kind IN ('serial','imei','barcode','custom')),
    value            TEXT NOT NULL,
    normalized       TEXT NOT NULL,            -- 大寫、去除空白與連字號
    confidence       REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source           TEXT NOT NULL DEFAULT 'human'
                     CHECK (source IN ('human','accepted_suggestion')),
    source_photo_id  TEXT REFERENCES photos(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (item_id, kind, value)
) STRICT;
CREATE INDEX idx_ident_norm ON identifiers(normalized);

CREATE TABLE suggestions (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    field            TEXT NOT NULL,            -- name|brand|model|category|condition|notes|identifier:serial
    value            TEXT NOT NULL,
    confidence       REAL,
    source           TEXT NOT NULL DEFAULT 'external',
    model_name       TEXT NOT NULL DEFAULT '',
    source_photo_id  TEXT REFERENCES photos(id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','accepted','rejected','superseded')),
    created_at       TEXT NOT NULL,
    decided_at       TEXT
) STRICT;
CREATE INDEX idx_sugg_item ON suggestions(item_id, status);

CREATE TABLE events (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,                 -- item|identifier|photo|observation|suggestion
    entity_id   TEXT NOT NULL,
    type        TEXT NOT NULL,                 -- item.created, field.changed, ...
    actor       TEXT NOT NULL DEFAULT 'user' CHECK (actor IN ('user','external','system')),
    field       TEXT,
    prev_value  TEXT,                          -- JSON encoded
    next_value  TEXT,                          -- JSON encoded
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
) STRICT;
CREATE INDEX idx_events_entity ON events(entity_type, entity_id, created_at);
CREATE INDEX idx_events_time   ON events(created_at);
```

### 2.3 設計說明

**`items.id` 用可讀短碼 `ITM-0001`**
同時是主鍵與資料夾名。可排序、不會重用、你和 agent 溝通時的 handle。不用 UUID 是因為你會想自己去翻 `files/`。

**`identifiers` 不設全域 UNIQUE，只對 `(item_id, kind, value)`**
刻意如此。自動辨識讀錯序號時，硬約束會讓寫入直接失敗，你就永遠看不到這個錯誤。改為撞號時回報警告，由你判斷「是不是同一件／打錯了／拍重複」。

**`normalized` 欄位**
你手上只有半截序號，或輸入時帶空格連字號（`BX-807 06` vs `BX80706`）。`normalized` 存大寫去空白去連字號的版本並建索引，搜尋時對兩邊都做正規化。

**`source_photo_id` 追蹤來源**
這是「序號可追溯到哪張照片」的實作。值寫入時記錄來源照片；日後該商品重新拍照辨識到同一序號時，不覆蓋既有來源（那是「這筆記錄的來源」）。

**`photos.role` 區分原始／衍生**
`derived/`（縮圖等）可以整個刪掉重生。`original/` 永遠不動。

**`quantity` 預設 1**
一張照片裡是一「組」東西（10 條線）時，不需要假裝有 10 個 Item。

**沒有 `deleted_at`**
與「原始資料不可破壞」一致。日常的刪除 = `status='void'`，資料與檔案都保留。

**`void` 是狀態，不是刪除**
`void` 只是把商品從日常清單裡移開，資料庫的每一列與 `files/<item-id>/`
底下的每一個檔案都原封不動。隨時可以改回 `active`，也可以查歷史。

**永久刪除是使用者單獨決定的例外路徑**
當你明確判定某件商品要永久淘汰（賣不掉、不想留了），允許一次性刪除該
Item 及其所有相關資料與檔案。這是例外，不是預設行為：

| 規則 | 內容 |
|---|---|
| 觸發方式 | 只能由你主動執行，**不做任何自動過期** |
| 刪除範圍 | 該 item、observations、photos、identifiers、suggestions，以及 `files/<item-id>/` 整棵目錄樹 |
| events | 稽核紀錄原則上保留；若要一併清除必須另行明示 |
| 不做的事 | 不做「滿一年自動清掉」之類的時間軸清理 |

永久刪除的 API 與 UI 目前尚未實作（v1 停在規格層）。日常操作一律走
`void`，不要把永久刪除做成預設或半自動行為。

**`items.status` 只有三個值：`active` / `archived` / `void`**
沒有 `draft`。Item 一建立就是 `active`，欄位可以暫時為空。
「AI 還沒確認」由 `suggestions.status='pending'` 表達（見 §4.1），
不靠 Item 的狀態表示 —— 兩件事混在同一個欄位會讓「商品是否有效」與
「資料是否已填」互相糾纏。

**`events.prev_value` / `next_value`**
讓單一欄位復原不需要額外邏輯。

---

## 3. 檔案結構

```
shop/
├── catalog.db                    SQLite（唯一需要備份的檔案）
├── config.json                   DATA_ROOT、AI 設定
├── inbox/                        待處理：手機上傳或手動丟入
└── files/
    ├── ITM-0001/
    │   ├── original/
    │   │   ├── 20261002-143022_IMG_4821.jpg
    │   │   └── 20261002-143355_IMG_4824.jpg
    │   └── derived/
    │       └── 4821.thumb.webp
    ├── ITM-0002/
    └── .orphan/                  photos 找不到對應 item 時的暫存
```

規則：

- **資料庫只存相對路徑**（相對於 `config.json` 所在目錄）
- **檔名格式**：`YYYYMMDD-HHMMSS_<原始檔名>` — 時間戳給排序，原始檔名保留以對回手機相簿
- **`inbox/` 是真實資料夾**，不一定要走 Web 上傳
- **孤兒照片不刪除**，放 `.orphan/` 等待歸屬

---

## 4. 核心流程

### 4.1 入庫（主要流程）

```
1. 取得照片
   ├─ 手機 → LAN 網頁上傳 → inbox/
   ├─ 手機檔案直接拖進 inbox/
   └─ 其他來源

2. 按「處理」
   ├─ 讀取 EXIF，依拍攝時間分組
   ├─ 為每組建立 Item (ITM-xxxx) + Observation(kind='intake')
   ├─ 照片移入 files/ITM-xxxx/original/，寫入 photos
   ├─ 產生 suggestions（v1 由外部工具寫入，或人工填）
   └─ 寫入 events

3. 確認畫面（核心 UI）
   ┌──────────────────────────────────────┐
   │ ITM-0001                   active     │
   │ ┌────────┐ ┌────────┐ ┌────────┐      │
   │ │ photo1 │ │ photo2 │ │ photo3 │      │
   │ └────────┘ └────────┘ └────────┘      │
   │                                      │
   │ 品牌  ASUS              [接受][改]   │
   │ 型號  ROG STRIX B650E-F [接受][改]   │
   │ 序號  6LWMF1234567  ⚠ 撞號          │
   │        → 來源：20261002-143355_…jpg  │
   │                                      │
   │ 品況  正常使用、外觀有輕微刮痕  [改]  │
   │                                      │
   │        [全部接受]  [確認並封存]      │
   └──────────────────────────────────────┘
4. 接受建議 → 值寫入正式欄位
```

**Item 建立後就是 `active`，沒有 draft 狀態。**

`items.status` 只有 `active` / `archived` / `void` 三個值（見 §2.2 DDL）。
「尚未確認」這件事由 `suggestions.status = 'pending'` 表達，不靠 Item 的狀態表示：

| 階段 | 資料在哪 | Item.status |
|---|---|---|
| 匯入完成，欄位先空著 | 正式欄位暫時為空 | `active` |
| AI / 外部工具猜測 | `suggestions`（`status='pending'`） | `active` |
| 使用者接受 | 值寫入正式欄位，該建議 `status='accepted'` | `active` |

欄位可以暫時為空是刻意的：`items` 每一欄都有 `NOT NULL DEFAULT ''`，
但「空字串」與「還沒填」在 v1 語意相同，差別由 events 與 suggestions 記錄。

### 4.2 重新觀測（Observation）

同一商品任何時候可以新增 Observation：

```
在商品詳情頁 → 「新增觀測」
→ kind 選 recheck
→ 上傳照片 → 建立第二個 Observation
→ 原始 Observation 不受影響
```

用途：補拍細節、重拍外觀確認、收到退貨後拍照留存。日後的「原始 vs 現在」比對就是比對兩個 Observation。

### 4.3 事件與復原

```
任何欄位修改 → 寫 events(type='field.changed', prev_value, next_value)

商品詳情頁「歷史」分頁 → 顯示所有事件
單筆事件可「復原」→ prev_value 寫回，記錄 actor='user'
```

---

## 5. HTTP API

FastAPI，自動產生 OpenAPI（`/docs`）。這份契約是未來擴充的基礎，未來的手機 App、掃碼器、外部辨識腳本都依它。

### Items

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/items` | 列表。`?q=&status=&category=&limit=&offset=` |
| POST | `/api/items` | 建立 |
| GET | `/api/items/{id}` | 詳情（含 observations、photos、identifiers、suggestions 數量） |
| PATCH | `/api/items/{id}` | 更新欄位，自動寫 events |
| POST | `/api/items/{id}/void` | 軟刪除 |

### Observations & Photos

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/items/{id}/observations` | 該商品的所有觀測 |
| POST | `/api/items/{id}/observations` | 新增觀測 |
| POST | `/api/observations/{id}/photos` | 上傳照片（multipart），存檔 + 寫 photos |
| DELETE | `/api/photos/{id}` | 僅允許刪 `role='derived'`；original 需改 role |

### Identifiers

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/items/{id}/identifiers` | |
| POST | `/api/items/{id}/identifiers` | 新增。撞號時回 `409` + 既有 item 清單 |
| PATCH | `/api/identifiers/{id}` | |
| DELETE | `/api/identifiers/{id}` | |
| GET | `/api/identifiers/lookup` | `?value=` 正規化後模糊比對，回傳所有相符項 |

### Suggestions

| Method | Path | 說明 |
|---|---|---|
| POST | `/api/items/{id}/suggestions` | 外部工具（AI）寫入預測 |
| GET | `/api/items/{id}/suggestions` | |
| POST | `/api/suggestions/{id}/accept` | 值寫入主表，identifier 類另建 identifiers |
| POST | `/api/suggestions/{id}/reject` | |

### Events

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/items/{id}/events` | 商品歷史 |
| POST | `/api/events/{id}/revert` | 單欄位復原 |

### Inbox & System

| Method | Path | 說明 |
|---|---|---|
| POST | `/api/inbox/photos` | 手機上傳（multipart），落盤 inbox/ |
| GET | `/api/inbox` | 待處理清單 |
| POST | `/api/inbox/group` | 依 EXIF 時間分組，產生待建檔批次 |
| GET | `/api/health` | 狀態 |
| GET | `/api/stats` | 項目數、最近活動 |

### 靜態檔案

`GET /files/<path>` — 從 DATA_ROOT 提供原始照片。

---

## 6. Web UI

五個畫面。原生 HTML/CSS/JS，**不建置、不依賴前端框架**。

| 畫面 | 路徑 | 內容 |
|---|---|---|
| **Inbox** | `/` | 待處理照片、批次分組、「開始建檔」 |
| **列表** | `/items` | 搜尋列、狀態/分類篩選、縮圖網格 |
| **詳細** | `/items/{id}` | 照片牆、欄位、建議、識別碼、觀測、歷史 |
| **新增觀測** | `/items/{id}/new` | 上傳、選 kind |
| **設定** | `/settings` | DATA_ROOT、AI 設定、備份、統計 |

**設計重點**

- 照片優先。確認畫面以照片為主體，因為你說的是「瞄一眼」
- 每個建議值旁顯示信心值與來源照片縮圖連結
- 撞號用醒目提示，附既有 item 的連結供比對
- 識別碼欄位旁永遠顯示「來源照片」縮圖

---

## 7. 搜尋

### 7.1 識別碼（序號）搜尋

正規化後用 `LIKE` 比對：

```sql
normalized LIKE '%' || :q || '%'
```

兩邊都做正規化：轉大寫、移除空白、`-`、`_`。

已實測通過：

| 存入 | 搜尋 | 結果 |
|---|---|---|
| `BX-807 06_1234` | `807061234` | ✓ 命中 |
| `6LWMF1234567` | `6lwmf` | ✓ 命中（大小寫不拘） |

支援半截序號，因為實務上你手上通常只有後半段。

### 7.2 文字搜尋（品名 / 品牌 / 型號 / 備註 / attributes）

**v1 使用 `LIKE '%q%'`，不用 FTS5。**

理由是實測結果：

| 方案 | `主機板` | `主機`（2 字） | `STRIX` | `b650e` |
|---|---|---|---|---|
| FTS5 `trigram` | ✓ | **✗ 0 命中** | ✓ | ✓ |
| FTS5 `unicode61` | ✓ | ✗ | ✓ | ✗ |
| `LIKE '%q%'` | ✓ | ✓ | ✓ | ✓ |

兩個 tokenizer 都有致命限制：
- `trigram` 要求查詢詞至少 3 個字元，所以兩字中文查不到
- `unicode61` 不切中文，「主機板」只有在整詞完全相同時才命中

**而你的資料量在數千筆以內，`LIKE` 的全表掃描完全夠快。** 為了一個在這個規模下不必要的效能，換一個會讓兩字中文查不到的實作，是壞交易。

若未來資料量成長到需要 FTS5，再改用 `trigram` + 短查詢退回 `LIKE` 的混合方案。

### 7.3 搜尋範圍

```
items.name, brand, model, category, notes
items.attributes（JSON，以字串比對）
identifiers.value / normalized
```

照片內的文字需要 OCR，由未來接上的 AI 寫入 `attributes` 或 `identifiers`，v1 不做。

---

## 8. 備份與搬移

```bash
python shopctl.py backup     # 完整快照
python shopctl.py verify     # 完整性檢查
```

**備份必須是完整快照，不能只複製檔案。**

- SQLite 用 `Connection.backup()` API 取得一致副本（WAL 模式下直接複製會漏資料）
- 複製 `files/` 與 `config.json`
- 輸出到 `backups/shop-YYYYMMDD-HHMMSS/`，是一個可直接還原的資料夾
- 自動保留最近 N 份

**搬移**：關閉服務 → 整個 `shop/` 資料夾搬到任何位置 → 啟動。因為資料庫只存相對路徑，`config.json` 記 DATA_ROOT，不需要改任何東西。

---

## 9. 技術選型

| 層 | 選擇 | 理由 |
|---|---|---|
| 語言 | Python 3.11+ | 目前已在用；型別註記讓 coding agent 寫錯時可被靜態檢查抓到 |
| 後端 | FastAPI + uvicorn | `/docs` 自動產生 OpenAPI，未來擴充的契約；型別驗證 |
| 資料庫 | SQLite（WAL） | 單檔、隨資料夾走、零設定。資料量在數萬筆內無虞 |
| 搜尋 | `LIKE`（見 §7） | 實測 FTS5 對兩字中文查不到，`LIKE` 在此規模足夠且正確 |
| 前端 | 原生 HTML/CSS/JS | **不建置**。5 個畫面不需要框架，且沒有 `npm run build` 讓 coding agent 的修改迴圈變慢 |
| 照片 | 檔案系統 | 不塞資料庫。照片用檔案、資料庫只存 metadata |
| ID | 短碼 + UUIDv7 | items/observations 用可讀碼；events 等內部用 ULID |
| AI | **v1 不含** | 見 §13 |

**既有原型**：v1 之前的「交易紀錄」是概念驗證，已從 repo 移除
（其中混入賣家個人的聯絡資訊與社群 QR，不適合公開）。其中出貨單排版
（mm 級控制、標籤機列印）是可攜的技術資產，已單獨保留在
`prototype/shipping/`，個人資料全部改為 placeholder。

---

## 10. 開發順序

依 coding agent 的工作特性排序，每階段都能獨立驗證。

| 階段 | 內容 | 完成判準 |
|---|---|---|
| **1. 骨架** | 專案結構、config、DB 連線、schema 套用、CLI (`init`/`backup`) | `shopctl.py init` 可執行，產生空 catalog.db |
| **2. 資料存取層** | 型別化的 CRUD、events 寫入、ID 產生 | 單元測試通過 |
| **3. 檔案管理** | inbox 掃描、EXIF 讀取、照片歸檔、sha256 去重 | 測試資料夾能完整走一次 |
| **4. API** | FastAPI 全部端點 + OpenAPI | `/docs` 可用，OpenAPI 可匯出 |
| **5. 搜尋** | `LIKE '%q%'` 全文比對、identifier 正規化比對 | 半截序號能搜到、兩字中文能搜到 |
| **6. UI — 列表與詳細** | 搜尋、篩選、照片牆、欄位編輯、歷史 | 能手動建檔並搜尋到 |
| **7. UI — Inbox** | 上傳、分組、建檔精靈 | 丟照片 → 一鍵成 Item |
| **8. Suggestions** | 接受/拒絕流程、來源照片顯示、identifier 建議 | 分離驗證成立 |
| **9. 復原** | 事件復原 UI | 能把改錯的欄位還原 |
| **10. 收尾** | README、啟動腳本、錯誤處理打磨、完整測試 | — |

**搜尋不使用 FTS5。** §7.2 早已實測決定 v1 用 `LIKE '%q%'`：FTS5 的
`trigram` 要求查詢詞至少 3 字元（兩字中文 0 命中），`unicode61` 不切中文。
既然不用 FTS5，就沒有「FTS5 建表與維護」這件事，階段 5 只剩驗收搜尋行為。
若未來資料量成長到全表掃描不夠，再改用 `trigram` + 短查詢退回 `LIKE` 的混合方案。

階段 1–5 已完成。搜尋行為隨階段 4 的 API 一併落地
（`GET /api/items?q=` 與 `GET /api/identifiers/lookup?value=`），
階段 5 補齊的是驗收測試，不是新架構。

---

## 11. v1 驗收標準

以「我自己的實際使用」驗收：

1. 從手機傳 8 張照片到 inbox，按一次按鈕能產出一個 Item
2. 照片在磁碟上被重新命名並歸檔，原始檔名保留
3. 能填品牌／型號／品況，並且填錯時可復原
4. 手輸序號的**後半段**能搜到該商品
5. 序號旁看得到「這是從哪張照片來的」
6. 關閉程式再開，資料都在
7. 整個 `shop/` 資料夾複製到 D 槽，執行後一切正常
8. 跑一次 `backup`，產生的資料夾可單獨還原
9. 能對同一商品新增第二個 Observation，原始照片不受影響
10. 整個 UI 在 100 筆以上資料時搜尋仍秒回

---

## 12. 明確不做

```
❌ 銷售 / 交易 / 金流 / 付款 / 物流 / 訂單同步
❌ 客戶管理
❌ 多使用者 / 登入 / 權限
❌ 雲端 / SaaS / 公開部署
❌ 內建 AI、LLM 呼叫、token 管理、模型路由
❌ Agent runtime / permission framework
❌ 手機原生 App（LAN 網頁即可）
❌ 退貨比對的自動報告（人工比對足夠）
❌ 商品合併 / 拆分
❌ 商品組合 / 套組關係（bundle）
❌ 前端框架與建置流程
❌ 自動過期刪除（例：滿一年自動清掉舊資料）
❌ 搜尋索引 / FTS5（§7.2 已決定用 `LIKE`，見 §10 階段 5）
```

**自動過期刪除 v1 不做（已確認）**
資料會留著。日常移除用 `status='void'`，資料與檔案都保留；
永久刪除只能由你明確決定後一次性執行，見 §2.3。工具不替你決定
「這件東西多久該消失」。

**組合商品 v1 不做（已確認）**

「主機板 + CPU + RAM + 散熱器」拆成四個獨立 Item，不建立
`bundle` / `parent_item` / `component_relationship`。
真正的需求是「能不能追蹤這個實體」，不是「能不能建組合銷售系統」。

未來若需要，新增一張 `item_relations(id, from_item, to_item, kind)` 即可，
不影響現有六張表 — 因為所有 FK 都是 `ON DELETE RESTRICT`，擴充是加表不是改表。

---

## 12.1 v1 定義完成：唯一需要跑通的路徑

規格規模不小，但 **v1 完成只看這條主線**：

```
拍照 / 匯入
  → Inbox
  → 建立 Item
  → 建立 Observation
  → 原始照片保存到 files/ITM-xxxx/original/
  → 建立 suggestions
  → 人工確認
  → Identifier 正式成立（帶 source_photo_id）
  → 搜尋得到
  → 歸檔完成
```

這條路徑跑通即為 v1。API 的完整端點清單、復原功能、統計等是沿路補齊的，不是獨立目標。

**從此凍結規格，不再增加抽象層。**

---

## 13. 擴充點

**v1 不做，但架構已預留：**

| 擴充 | 預留方式 |
|---|---|
| **AI 辨識** | `suggestions` 表 + `POST /api/items/{id}/suggestions`。任何外部腳本、Claude Code、簡單 `.py` 都能接入，主程式不需改動 |
| **本地模型** | 同上。AI 端完全在產品之外，換實作不影響資料層 |
| **退貨比對報告** | Observation 已有 `kind='recheck'`，比對是兩個 Observation 之間的衍生產物，可存 `files/ITM-xxxx/reports/` |
| **商品合併** | 所有 FK 都是 `ON DELETE RESTRICT`，合併是重新指派而非刪除，資料完整性有保障 |
| **條碼掃描** | 掃描器就是鍵盤輸入，輸入框加 autofocus 即可。`identifiers.kind` 已預留 `barcode` |
| **多品類欄位** | `items.attributes` JSON |
| **其他客戶端** | OpenAPI 契約 |
| **出貨單** | 獨立模組，與本專案資料模型解耦，只需讀 items/identifiers |

---

## 14. 已決案事項（原先的待確認，freeze 時結案）

| # | 議題 | 決定 | 理由 |
|---|---|---|---|
| 1 | ID 格式 | `ITM-0001` / `OBS-20261002-0001` | 可排序、不重用、是人類與 agent 的 handle，同時是資料夾名 |
| 2 | `observation.kind` 還要哪些值 | v1 只做 `intake` / `recheck` / `manual` | 需要時在 CHECK 加值即可，改 schema 成本低 |
| 3 | 組合商品 | **v1 不做**（見 §12） | 拆成獨立 Item 即可，未來加一張關係表 |
| 4 | EXIF 讀取失敗退路 | 退回檔案 mtime；再失敗則用檔案名開頭的時間戳；都沒有就留空由使用者手填 | 手機上傳常丟 EXIF，不能因此中斷流程 |
| 5 | `config.json` 多資料夾 | v1 單一 DATA_ROOT | 內部碟 + 外接碟是假設情境，先不做；資料夾本來就可整份複製 |

### 檔案遷移策略

原先並存的 `db.py`、`server.py`、`web/` 是概念驗證版本，v1 為重寫、互不引用。
這三個路徑已於 Phase 4 收尾時從 repo 移除 —— 其中含賣家個人的姓名、電話、
地址與社群 QR，不適合公開。

其中出貨單的 mm 級排版技術是 §9 指名要保留的可攜資產，已單獨保留在
`prototype/shipping/`（HTML/CSS/JS，個人資料全改為 placeholder），
未來出貨單模組會重用。v1 主程式不引用 `prototype/` 的任何內容。

---

## 15. 給 coding agent 的工作方式

實作時建議逐階段提交，每階段可獨立驗證。預期指令範例：

> 「實作 SPEC-v1 階段 1（骨架）。不要擴充範圍。」

之後 AI 功能一律寫成外部腳本消費 API，核心不動：

```python
# tools/analyze_inbox.py — 外部腳本，不在產品內
import httpx
resp = httpx.post(f"{BASE}/api/items/{item_id}/suggestions", json={
    "field": "model", "value": "ROG STRIX B650E-F", "confidence": 0.82,
    "model_name": "claude-opus-4", "source_photo_id": photo_id,
})
```