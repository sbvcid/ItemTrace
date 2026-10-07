# 5. Information Architecture

## 1. 結構總覽

```text
ItemTrace
├── 物品庫 Library                       /                    （首頁）
│   ├── 注意事項列 Attention strip          （待確認・未整理照片・AI 未設定・備份提醒）
│   ├── 搜尋 Search                         /?q=…
│   ├── 篩選 Filters                        /?status=…&category=…&view=…
│   └── 批次選取 Bulk select                （標籤・類別・標記離手）
│
├── 拍照建檔 Capture                      /capture             （全螢幕流程）
│   ├── 新物品                              /capture
│   └── 為既有物品新增快照                  /capture?item=ITM-0042
│
├── 待確認 Review                         /review              （佇列 + 專注審核）
│   └── 專注審核                            /review/ITM-0042
│
├── 未整理照片 Unsorted                   /unsorted            （只在非空時出現於導覽）
│   └── 匯入 Import                         /unsorted?import=1   （桌機拖放）
│
├── 物品履歷 Dossier                      /i/ITM-0042          （QR 標籤指向這裡）
│   ├── 照片檢視器                          /i/ITM-0042/photos/:photoId
│   ├── 比對快照                            /i/ITM-0042/compare?a=…&b=…
│   ├── 完整變更紀錄                        /i/ITM-0042/history
│   ├── [Sheet] 新增快照 → 轉到 /capture?item=…
│   ├── [Sheet] 新增註記
│   ├── [Dialog] 列印標籤
│   ├── [Dialog] 證據包
│   └── [Dialog] 標記離手／恢復／作廢
│
└── 設定 Settings                         /settings
    ├── AI 辨識                             /settings/ai
    ├── 標籤與列印                          /settings/labels
    │   └── 標籤樣式編輯（進階）            /settings/labels/:templateId
    ├── 手機連線                            /settings/phone
    ├── 資料與備份                          /settings/data
    └── 語言與關於                          /settings/about
```

**一級目的地只有三個**：物品庫、待確認、設定。「拍照建檔」是一級**動作**；「未整理照片」是條件式目的地。

---

## 2. 導覽

### 2.1 手機（< 768px）

```text
┌─────────────────────────────────┐
│  ItemTrace          🔍   ⚙       │  ← 頂列：搜尋（展開為全寬）、設定
├─────────────────────────────────┤
│                                 │
│           內容                   │
│                                 │
├─────────────────────────────────┤
│   ▤ 物品庫    ( ◉ )    ✓ 待確認 3 │  ← 底部列：中央拍照為凸起主按鈕
└─────────────────────────────────┘
```

* 底部列只有 3 個位置：**物品庫、拍照（主按鈕）、待確認**。
* 「未整理照片」在手機上**不佔導覽位置**，只出現在物品庫的注意事項列（手機上的整理主要在桌機做）。
* 進入履歷、比對、設定子頁時，底部列保留（履歷有自己的底部動作列時，導覽列隱藏，見 UX-DESIGN §5.4）。
* Capture 是全螢幕，沒有導覽列。

### 2.2 平板（768–1279px）

* 左側**收合的 icon rail**（64px）：物品庫、待確認、未整理（條件式）、設定；頂部「＋ 新物品」。
* 768–1023：rail；1024–1279：rail，可展開為 sidebar。

### 2.3 桌機（≥ 1280px）

```text
┌───────────────┬──────────────────────────────────────────────┐
│ ◧ ItemTrace   │  🔍 搜尋物品、序號、ITM-…              [＋ 新物品] │
│               ├──────────────────────────────────────────────┤
│ ▤ 物品庫       │                                              │
│ ✓ 待確認    3  │                                              │
│ ▦ 未整理   12  │               內容                            │
│               │                                              │
│ ─────────     │                                              │
│ ⚙ 設定         │                                              │
│               │                                              │
│ ● 手機已連線    │                                              │
└───────────────┴──────────────────────────────────────────────┘
```

* Sidebar 240px；底部一個連線／資料健康的小狀態（點擊進入對應設定）。
* 頂列搜尋**全域常駐**（`/` 快捷鍵聚焦）。
* 「＋ 新物品」在桌機開啟一個選擇：**從電腦匯入照片**／**用手機拍**（顯示連線 QR）。

### 2.4 導覽原則

1. **任何畫面最多 2 次點擊回到物品庫。**
2. **履歷可從任何地方直達**（搜尋、QR、待確認、時間軸連結、撞號卡片），而且 URL 短到可以印在標籤上。
3. **流程（Capture、專注審核）是全螢幕的**，有明確的「完成」與「離開」，不與導覽混在一起。

---

## 3. 路由表

| 路由 | 畫面 | 類型 | 主要裝置 | 說明 |
|---|---|---|---|---|
| `/` | 物品庫 | 目的地 | 全部 | query：`q`、`status`（`in_hand` 預設／`gone`／`voided`／`all`）、`category`、`view`（`grid`／`list`）、`filter`（`unnamed`／`no_identifier`／`warranty_soon`）、`sort`（`updated` 預設／`created`／`id`） |
| `/capture` | 拍照建檔 | 全螢幕流程 | 手機 | 新物品；`?item=ITM-…` 為新增快照；`?purpose=…` 預選目的 |
| `/review` | 待確認佇列 | 目的地 | 桌機 | 列出有 pending 建議的物品 |
| `/review/:id` | 專注審核 | 全螢幕流程 | 桌機／平板 | 審核一件，「下一件」前進 |
| `/unsorted` | 未整理照片 | 條件式目的地 | 桌機 | 時間分組建議、建立物品、加入既有物品；`?import=1` 開啟拖放匯入 |
| `/i/:id` | 物品履歷 | 頁面 | 全部 | **標籤 QR 的目標**；必須在手機上快速載入 |
| `/i/:id/photos/:photoId` | 照片檢視器 | Overlay 路由 | 全部 | 可分享的深連結；返回關閉 |
| `/i/:id/compare` | 比對快照 | 頁面 | 全部 | `?a=OBS-…&b=OBS-…`，預設為「建檔」vs「最新」 |
| `/i/:id/history` | 完整變更紀錄 | 頁面 | 桌機 | 原始 events，含復原 |
| `/items/:id` | — | 重新導向 | — | → `/i/:id`（相容舊連結） |
| `/settings` | 設定首頁 | 目的地 | 全部 | 手機：清單；桌機：左清單右內容 |
| `/settings/ai` | AI 辨識 | 子頁 | 全部 | |
| `/settings/labels` | 標籤與列印 | 子頁 | 桌機 | |
| `/settings/labels/:tpl` | 標籤樣式編輯 | 子頁 | 桌機 | 進階 |
| `/settings/phone` | 手機連線 | 子頁 | 桌機 | 顯示 QR |
| `/settings/data` | 資料與備份 | 子頁 | 桌機 | |
| `/settings/about` | 語言與關於 | 子頁 | 全部 | |
| `/docs` | API 文件 | 既有 | — | 不在產品導覽中，只從「關於」連結 |

**Overlay 規則**：Dialog／Sheet（列印、證據包、離手、新增註記）**不改變路由**（避免返回鍵行為混亂），但照片檢視器例外（需要深連結與返回關閉）。

---

## 4. 畫面清單與內容優先序

### 4.1 物品庫

| 優先 | 內容 |
|---|---|
| 1 | 搜尋（桌機在頂列；手機點 🔍 展開） |
| 2 | 注意事項列（僅在有事項時顯示，可逐項關閉，關閉狀態存 localStorage） |
| 3 | 狀態分段：**在手上**／已離手／全部（已作廢在篩選選單中） |
| 4 | 物品（照片優先的卡片網格；桌機可切換為表格列表） |
| 5 | 篩選與排序（類別、未命名、無識別碼、保固即將到期） |

### 4.2 物品履歷（詳見 UX-DESIGN §5.4）

| 優先 | 區塊 | 為什麼在這個位置 |
|---|---|---|
| 1 | **照片**（主照片 + 縮圖列） | 第一個問題永遠是「是這個嗎？」 |
| 2 | **身分**：名稱、品牌·型號、類別、ID、狀態 | 第二個問題：「它是什麼？」 |
| 2a | **AI 建議**（若有）直接長在身分欄位上 | 待辦就在它要改的地方 |
| 3 | **識別碼**（含來源照片縮圖） | 對主要使用者，序號是身分證 |
| 4 | **狀況**與**備註** | 證據敘述 |
| 5 | **選用事實**：取得、保固、位置、數量（空的收合） | 對 B 重要，但不是每件都有 |
| 6 | **完整度**清單（可收合；全滿時隱藏） | 提示，不打擾 |
| 7 | **時間軸** | 經歷 |
| — | **動作**：新增快照（主要）、標籤、證據包、⋯ | 桌機在身分區右上；手機在底部動作列 |

### 4.3 待確認

| 優先 | 內容 |
|---|---|
| 1 | 佇列計數與「開始審核」（進入第一件的專注審核） |
| 2 | 物品清單：縮圖、AI 建議的名稱（以建議樣式顯示）、建議數、建檔時間 |
| 3 | 辨識中／辨識失敗的物品（分組顯示，可重試） |

### 4.4 未整理照片

| 優先 | 內容 |
|---|---|
| 1 | 匯入（拖放區；手機上為「從相簿選擇」） |
| 2 | 分組建議（依拍攝時間），每組：縮圖、時間、張數 |
| 3 | 每組動作：**建立物品**／**加入既有物品**（搜尋選擇）／拆分／合併 |
| 4 | 無時間資訊的照片（單獨一組，需手動處理） |

### 4.5 設定

| 區塊 | 內容 |
|---|---|
| AI 辨識 | Provider、API key（只顯示已設定）、model、測試、**建檔後自動辨識**開關 |
| 標籤與列印 | 預設印表機、預設標籤樣式、**標籤連結網址**、樣式清單（預覽）、新增／編輯（進階） |
| 手機連線 | 目前綁定位址、LAN 網址 + QR、若未開放 LAN 則逐步說明 |
| 資料與備份 | 資料夾位置、物品／照片數量、最近備份、立即備份、完整性檢查 |
| 語言與關於 | zh-TW／en、版本、schema 版本、API 文件連結 |

---

## 5. 搜尋模型

### 5.1 單一搜尋框，多種意圖

| 輸入 | 意圖判斷 | 行為 |
|---|---|---|
| `ITM-0042`、`itm42`、`42`（純數字且 ≤ 6 位） | 物品 ID | 置頂「直接前往 ITM-0042」；Enter 直達履歷 |
| `http(s)://…/i/ITM-0042`（掃描結果貼上） | 標籤 QR 內容 | 直達履歷 |
| 英數混合 ≥ 4 字元（如 `6LWMF`、`1234567`） | 可能是識別碼 | 結果中識別碼命中**置頂**並標示「序號相符：…F1234567」 |
| 其他文字 | 名稱／品牌／型號／類別／備註／選用事實 | 一般結果，標示命中欄位 |

### 5.2 後端對應

* `GET /api/items?q=` 已涵蓋 name、brand、model、category、notes、attributes、identifiers（含正規化）。
* 命中欄位標示：前端以回傳資料自行比對（Level 0）。識別碼命中需要識別碼資料 —— Level 1 讓列表回傳 `matched_identifiers`（見 BACKEND-IMPACT B1-3）；在那之前，前端額外呼叫 `GET /api/identifiers/lookup?value=` 平行查詢。
* 預設範圍：**全部狀態**中搜尋（找東西時不應被「在手上」篩掉），結果中以狀態標籤區分。瀏覽時才預設「在手上」。

### 5.3 搜尋結果呈現

* 即時（debounce 200ms），桌機在頂列下拉預覽前 6 筆，Enter 進入完整結果（物品庫套用 `q`）。
* 手機：全螢幕搜尋層，結果為列表（縮圖 + 名稱 + 命中說明）。
* 空結果：「找不到『xxx』。試試序號的後半段，或[建立新物品]」。

---

## 6. 注意事項列（Attention strip）

依優先排序，最多顯示 3 項，其餘收進「還有 N 項」。

| 項目 | 條件 | 動作 |
|---|---|---|
| 待確認 | pending 建議的物品數 > 0 | 「3 件物品等你確認 → 開始」 |
| 辨識失敗 | AI 工作失敗的物品 > 0 | 「2 件辨識失敗 → 查看」 |
| 未整理照片 | inbox 中非 session 進行中的照片 > 0 | 「12 張未整理照片 → 整理」 |
| AI 未設定 | 未設定且使用者未關閉 | 「設定 AI，讓建檔更快（選用）」 |
| 備份提醒 | 最近備份 > 14 天或從未 | 「上次備份是 20 天前 → 立即備份」 |
| 手機未連線 | 桌機、從未有非本機裝置連線、且使用者未關閉 | 「用手機拍照建檔 → 連接手機」 |

---

## 7. 術語表

**UI 只使用「產品名稱」欄。** API／程式碼使用 backend 名稱。

| 產品名稱 zh-TW | 產品名稱 en | backend | 備註 |
|---|---|---|---|
| 物品 | Item | `items` | 不用「商品」 |
| 物品履歷 | Item record（頁面標題） | `GET /api/items/{id}` | en 不用 dossier（太罕見） |
| 物品庫 | Library | `GET /api/items` | |
| 在手上 | In hand | `status='active'` | |
| 已離手 | Gone | `status='archived'` | |
| 已作廢 | Voided | `status='void'` | |
| 快照 | Snapshot | `observations` | |
| 快照目的 | Purpose | `observations.purpose`（新） | |
| 建檔 | Recorded | `kind='intake'` / `purpose='intake'` | 第一個快照 |
| 註記 | Note | 無照片的快照 | |
| 照片 | Photo | `photos (role='original')` | |
| 角度 | Angle | `photos.angle` | 正面／背面／標籤／細節／瑕疵／收據 |
| 識別碼 | Identifier | `identifiers` | |
| 序號 | Serial number | `kind='serial'` | |
| IMEI | IMEI | `kind='imei'` | |
| 條碼 | Barcode | `kind='barcode'` | |
| 自訂碼 | Custom ID | `kind='custom'` | |
| 撞號 | Duplicate identifier | 409 conflict | 「另一件物品也有這個序號」 |
| AI 建議 | AI suggestion | `suggestions (pending)` | |
| 接受／修改後接受／略過 | Accept / Edit & accept / Dismiss | accept / accept+value / reject | 不用「拒絕」（太強烈） |
| 待確認 | To review | 衍生 | |
| 辨識 | Recognize | `POST /ai/analyze` | 不用「AI 自動填入」 |
| 時間軸 | Timeline | observations ∪ events | |
| 變更 | Change | `events` | |
| 復原 | Undo / Revert | `POST /api/events/{id}/revert` | toast 用 Undo；歷史中用 Revert |
| 拍照建檔 | Capture | inbox session + intake | |
| 未整理照片 | Unsorted photos | `inbox/` | |
| 標籤 | Label | print | |
| 標籤樣式 | Label design | `templates` | |
| 證據包 | Evidence package | evidence export | |
| 完整性 | Integrity | sha256 manifest | |
| 狀況 | Condition | `items.condition` | 不用「品況」（太賣家） |
| 類別 | Category | `items.category` | |
| 取得 | Acquired | `attributes.acquired_*` | |
| 保固 | Warranty | `attributes.warranty_until` | |
| 存放位置 | Location | `attributes.location` | |

