# 5. Information Architecture & Navigation

本文件定義 ItemTrace V3 的極簡資訊架構、路由設計、導覽結構與生活化術語對照表。

---

## 1. 導覽結構（Navigation Hierarchy）

為了徹底消除使用者的認知負擔，導覽結構圍繞產品最核心的兩大動作——**「📷 拍下來」** 與 **「🔍 找回來」** 展開：

```text
ItemTrace
├── 紀錄首頁 (所有紀錄)        /                    [已記住的內容・秒級搜尋・分類卡片]
├── 拍照記錄 (相機)            /capture             [隨手拍 2~4 張・AI 即時整理・存起來]
├── 紀錄詳情 (圖文卡片)        /i/:id               [大圖・AI 整理之品名規格序號・備註・歷程]
│   └── ［進階動作選單 ⋯］                         [列印標籤・比對・匯出封存包・標記離手]
└── 系統設定                  /settings            [AI 金鑰・手機連線・資料備份・關於]
```

### 1.1 手機端導覽（Mobile Navigation: < 768px）
* **頂部列 (Topbar)**：簡潔品牌、搜尋圖示 `🔍`、設定齒輪 `⚙`。
* **底部導覽列 (Bottom Nav)**：
  - 左：`[ ▤ 紀錄 ]`（瀏覽所有已記住的內容）
  - 中：`[ ◉ 拍照 ]`（突出懸浮圓形大按鈕，單手點擊直接啟動相機，拍下即整理）
  - 右：`[ 🔍 找東西 ]`（快速聚焦搜尋輸入框）

### 1.2 桌面端導覽（Desktop Navigation: ≥ 1024px）
* **左側簡潔側邊欄 (Sidebar - 200px)**：
  - `▤ 所有紀錄`（預設在手上之物件與紀錄）
  - `📦 已離手`（已賣出、送出或淘汰之存檔）
  - `─────────`
  - `⚙ 設定`
* **頂部常駐搜尋列 (Topbar Search)**：
  - 佔據中央的寬幅搜尋框：`🔍 搜尋品名、型號、序號、特徵... (按 / 聚焦)`
  - 右側醒目主按鈕：`[ 📷 拍照記錄 / 匯入 ]`

---

## 2. 路由對照表（Route Map）

| 路由 | 畫面名稱 | 產品層級 | 描述與用途 |
|---|---|---|---|
| `/` | 紀錄首頁 | Core | 展示所有在手中的紀錄卡片；支援即時文字與序號搜尋、標籤切換。 |
| `/capture` | 拍照記錄 | Core | 全螢幕相機流；拍完 2~4 張後，AI 自動理解整理並呈現，一鍵存起來。 |
| `/i/:id` | 紀錄詳情 | Core | 大圖展示、品名型號、序號、狀況、生活備忘（購買日期/保固/存放位置）與歷史。 |
| `/i/:id/compare` | 狀態比對 | Advanced | 進階：雙視窗並排比對兩次拍照的細節（退貨或送修前後）。 |
| `/settings` | 系統設定 | Supporting | AI 模型配置、手機連線 QR Code、本機備份與完整性檢查。 |
| `/unsorted` | 照片匯入 | Advanced | 進階：桌機將相機記憶卡大批照片拖放上傳，依拍攝時間智慧切分。 |

---

## 3. 生活化搜尋模型（Search Model）

搜尋框是使用者找回實體世界資訊的主要動脈：
1. **輸入即時反應 (Instant Debounce 100ms)**：
   - 輸入「顯卡」或「4070」：立刻篩選出對應卡片。
   - 輸入序號末碼「1234」：精確命中序號並置頂呈現。
2. **搜尋範圍自動覆蓋**：
   - 品名、品牌、型號、類別、備註、存放位置。
   - 所有登錄的序號（大小寫不拘，自動忽略連字號與空格）。
3. **無結果友善指引**：
   - 若在「在手上」查無結果，一鍵提供：「在已離手的紀錄中尋找？」

---

## 4. 生活化術語對照表（Everyday Glossary）

介面語言全面生活化，禁止將資料庫術語或二手電商糾紛名詞硬塞給使用者：

| 介面生活化中文 (zh-TW) | 介面生活化英文 (en) | 過去生硬術語（已淘汰） | 後端對應實作 |
|---|---|---|---|
| **整理好的紀錄 / 物品** | Record / Item | 商品、資產、資料庫筆數 | `items` 表 |
| **所有紀錄** | Records / Library | 庫存列表、Items Page、物品庫 | `GET /api/items` |
| **拍下來 / 拍照記錄** | Capture | 拍照建檔、新增物品、建庫 | `/capture` |
| **存起來** | Save | 入庫、儲存物品、提交 | `POST /api/items` |
| **在手上** | In Hand | Active、在庫 | `status='active'` |
| **已離手** | Gone | Archived、封存、出貨 | `status='archived'` |
| **作廢** | Voided | 軟刪除、Void | `status='void'` |
| **照片** | Photos | Observations、Derived | `photos` 表 |
| **追加照片與筆記** | Add Photo & Note | 新增觀測、Recheck | `add_observation` |
| **AI 自動整理** | AI auto-organize | AI 自動填入、Suggestion | `suggestions` 表 |
| **序號 / 條碼** | Serial Number / Barcode | Identifiers、識別碼抽象 | `identifiers` 表 |
| **更動歷史** | History | Events、稽核日誌 | `events` 表 |
| **標籤貼紙** | Label | Template 印表機輸出 | `templates` 表 |
| **匯出完整封存包** | Export Package | Evidence Bundle、存證包 | `evidence.py` |
| **存放位置** | Location | — | `attributes.location` |
| **保固到期** | Warranty Until | — | `attributes.warranty_until` |

