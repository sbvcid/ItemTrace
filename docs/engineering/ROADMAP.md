# ItemTrace Engineering Roadmap

本文件記錄施工藍圖：已完成階段的事實紀錄，以及尚未啟動方向的候選規劃。當前真實進度以 `docs/engineering/STATUS.md` 為準；已完成階段以實際程式與測試為準，不以早期計畫文字為準。

**產品定位**：「拍下來，AI 幫你記住，以後找得到。」

**核心流程**：Capture → AI Understand & Organize → Save → Retrieve

---

## 現有技術基線（2026-10-11）

### 後端（`shop/`）
- Python + FastAPI + SQLite（WAL、STRICT 約束、`BEGIN IMMEDIATE` 交易、`busy_timeout`）
- 六張核心表：items（含 `attributes` JSON 動態屬性）、photos、observations、suggestions、identifiers、events
- 推論與事實分離（suggestions 與主表隔離）；Event sourcing 與單欄位復原
- 原始照片 byte-for-byte 保存（`files/original/`；SHA-256 去重）
- 搜尋：SQL `LIKE`（含 identifiers 正規化比對、accepted 建議值命中）——FTS5 曾實測被排除（見 DECISIONS D3）
- 安全：SR-1（Host／Origin／`X-Requested-With`／key 不外送／LAN opt-in／媒體輸出）＋ SR-2（資源上限／資訊衛生／列印管線硬化）已完成
- 垃圾桶與資料生命週期：`status='void'`＋還原＋使用者明示永久刪除；無自動過期（見 DECISIONS D5）

### 前端（`web/`）
- 零建置 ESM SPA：Capture／Home／Record Detail／Trash／Settings
- 繁中＋英文 i18n；手機優先響應式
- UX 手機優先修整完成（移除浮動快門 FAB、簡化首頁 hero 與詳情頁、i18n 完整性）

### 測試
- pytest 1096 測試全通過（38 個 `tests/test_*.py`；2026-10-11 基線）

---

## 施工階段

### 已完成

| 階段 | 內容 | 完成時間 | Commit |
|---|---|---|---|
| Phase 0 | 基線盤點與工程文件 | 2026-10-09 | `6bfdeda` |
| Phase 1A | V3 前端正式整合與核心驗收 | 2026-10-09 | `2879904` |
| Phase 1B-A | 首頁基本流程（最新置頂、保存回首頁） | 2026-10-09 | `98edc0c` |
| Phase 2A | AI 建議生命週期與部分失敗語意 | 2026-10-09 | `15f2e9b` |
| Phase 2B | 證據累積與情境式重新理解 | 2026-10-09 | `22b0c22` |
| Phase 2C-A | AI 評測與自主性政策 | 2026-10-10 | `dda8b61` |
| Phase 2C-B | 可回復的 AI 自動更新 | 2026-10-10 | `7927faf` |
| Phase 2C-C | 自主性 Live 驗證 | 2026-10-10 | `5a4c792` |
| Phase 2C-D | 撤銷安全、描述與衝突處理 | 2026-10-10 | `79eaecc` |
| Security Audit 1 | 桌面應用唯讀稽核（F1–F8） | 2026-10-10 | `3e002d2` |
| SR-1 | 安全修復（Host／Origin／key／LAN／媒體） | 2026-10-10 | `24d1909` |
| SR-2 | 資源上限／資訊衛生／列印安全 | 2026-10-10 | `547a522` |
| Phase 2 編輯介面 | 紀錄欄位編輯與序號照片映射修正 | 2026-10-11 | `e57f9ef` |
| Phase 3 | 垃圾桶與資料生命週期 | 2026-10-11 | `de4922d` |
| UX 手機優先修整 | 首頁／詳情頁簡化、i18n 完整性 | 2026-10-11 | `e86f6ee` |
| capture 建檔流程修正 | 儲存前草稿分析，確認存檔才建立正式紀錄 | 2026-10-11 | `68b1399` |
| AI 重新分析流程改善 | 完整紀錄歷史上下文、證據時間軸與合理更新政策 | 2026-10-11 | 當前階段 |

各階段的細節變更清單見 `docs/engineering/STATUS.md`。

### Phase 3：垃圾桶與資料生命週期（已完成；實作即規格）

依現有實作記錄（取代早期「`items.deleted_at` 欄位＋30 天保留＋背景清除 job」提案——該提案**未採用**，見 DECISIONS D5）：

- **移至垃圾桶（軟刪除）**：沿用既有 `status='void'`，零 schema migration、無 `deleted_at` 欄位；詳情頁附說明性確認
- **預設列表排除 void**：`repo.list_items` 未指定 `status` 時一律排除 void（首頁與一般搜尋不再顯示）；`archived` 仍留在預設檢視；垃圾桶以 `GET /api/items?status=void` 查詢
- **還原**：`POST /api/items/{id}/restore`；移入前狀態由事件歷史推導（最近一次 `status → void` 的 prev_value），不可靠時安全預設 `active`
- **永久刪除**：`DELETE /api/items/{id}`，僅限垃圾桶紀錄（active／archived 回 400），由使用者明確執行；單一交易清除 DB 紀錄與全部相關 events；照片目錄先可逆改名 `.purge/` 再移除；刪檔失敗回 500 並列出完整路徑
- **編號不回收**：`schema_meta.items_seq`（零 DDL；舊庫自動由 items 最大值補齊）
- **不做自動過期清除**：無排程清理 job；備份快照不受永久刪除觸及。未來若要自動清除，需先定案資料安全政策並明示使用者

---

### 未啟動（候選方向；啟動前需確認範圍）

#### Phase 4：分類系統與 AI 自動分類（下一個候選）

**依賴**：Phase 2（AI Contract 基礎）✓

**目標**：建立分類系統，支援 AI 自動建議、使用者維護、分類正規化。

**候選工作範圍**：

1. **分類體系**：預定義分類清單（清單內容待定案，DECISIONS O2）、支援自訂分類、同義詞與別名對應
2. **AI 自動分類**：Vision 分析擴充分類推薦；沿用 suggestions 生命週期（不覆蓋主表、可復原、衝突升級）
3. **分類正規化與索引**：同義詞轉換、分類篩選與計數

**技術備註**：現有 `items.category` 為自由文字欄位；若需分類表與外鍵（`categories`＋`items.category_id`），屬 schema 變更，需依 AGENT_GUIDE §5 做向下相容 migration 計畫。既有 `attribute:<key>` 與建議生命週期可直接重用。

#### Phase 5：搜尋強化（依需求評估，未排程）

現行 LIKE 搜尋在目前資料量下足夠，且是刻意決策（FTS5 `trigram` 兩字中文 0 命中、`unicode61` 不切中文——見 DECISIONS D3 與 SPEC-v1 §7.2）。**FTS5 目前未採納、未排程**。

若未來資料量成長使全表掃描不足，候選方案：FTS5 `trigram`＋短查詢退回 LIKE 的混合方案；繁簡互搜（OpenCC，見 D4）屆時一併評估。

#### Phase 6：進階能力完善

列印（Chromium＋GDI，SR-2 硬化）、外觀比對、封存包匯出（evidence bundle，read-only）已有基礎。剩餘候選：

1. **外觀比對器完善**：雙視窗同步縮放平移、差異標註（DECISIONS O4）

#### Phase 7：同一物品匹配（未來）

1. **同一物品識別**：序號與照片相似度判斷（embedding 或視覺哈希）；可選自動合併或提示使用者

依賴 Phase 4（分類正規化）與搜尋效率。

#### Phase 8：Windows 發行準備（未來）

應用程式中繼資料（版本號、CHANGELOG、圖示）、MSIX／EXE 打包與簽名、使用者資料位置標準化（%APPDATA%，DECISIONS D7）、安裝／更新機制。依賴核心功能穩定。

---

## 工作依賴關係

```text
Phase 0 ✓ → Phase 1A ✓ → Phase 1B-A ✓
                          ├→ Phase 2 ✓（2A → 2B → 2C-A/B/C/D）
                          │    └→ Phase 4 分類（候選）→ Phase 7 同一物品匹配（未來）
                          ├→ Phase 3 垃圾桶 ✓
                          ├→ Security Audit ✓ → SR-1 ✓ → SR-2 ✓
                          ├→ Phase 5 搜尋強化（依需求，未排程）
                          ├→ Phase 6 進階完善（部分已有基礎）
                          └→ Phase 8 Windows 發行（未來）
```

**關鍵路徑**：Phase 4 候選是下一個決策點；Phase 5／6／7 可在分類系統之外獨立評估。

---

## 資料庫 Migration 原則

- 至今零 migration：所有功能（含垃圾桶生命週期）以既有欄位與狀態機達成
- 未來任何 schema 變更：向下相容、新欄位帶預設值、先在測試環境驗證、提供回復方案（見 AGENT_GUIDE §5）

---

## 不在實作範圍

- 多人雲端同步／帳號系統／登入
- 自動過期刪除（產品決策：資料保留由使用者決定，見 D5）
- 相機記憶卡大量照片匯入（`/unsorted`）—— 非已確認的產品需求，不得作為規劃依據（2026-10-11 移除；現行的多張選取、拍照、上傳與追加照片功能不受影響）
- PDF 生成與高級報表設計
- 機器學習模型訓練與微調
- 移動原生 App（手機走瀏覽器）
- 自動備份到雲端儲存

---

## 施工原則

1. **最小變更範圍**：一次一個邏輯目標；commit 與邏輯單元對應（不綁整個 Phase）
2. **測試優先**：新功能補測試、不刪除既有測試；測試範圍按修改風險決定（見 AGENT_GUIDE §7）
3. **資料安全**：刪除／修改先驗證備份與回復路徑
4. **向下相容**：schema 變更不破壞舊資料
5. **交付即同步**：commit → push → 驗證遠端（見 AGENTS.md 標準流程）
6. **文件對齊現實**：狀態以 STATUS.md 為準；文件與程式衝突時以程式與目前指示為準並修正文件（見 DECISIONS D11）

---

## 已知開放問題

| 項目 | 狀態 | 備註 |
|---|---|---|
| 生活備忘欄位設計（Phase 1B-B） | 開放 | 購買日期／保固／存放位置的具名欄位化 |
| 分類體系設計 | 候選 | Phase 4 啟動前定案預定義清單（DECISIONS O2） |
| 屬性逐鍵來源標籤（✨AI／✍手動） | 開放 | 目前以 banner＋事件／建議可追溯 |
| 搜尋效能基線 | 未測 | Phase 5 候選啟動時評估 |
| Windows Store 簽名／MSIX 配置 | 未來 | Phase 8 啟動前確認（DECISIONS D7） |

---

## 修改歷史

- **2026-10-09**：初始版本建立（Phase 0 audit 基礎）；同日修正排序與依賴
- **2026-10-09（1B-A／2A／2B）**：首頁流程、建議生命週期、證據累積完成；測試基線 928 → 940 → 955
- **2026-10-10（2C-A～2C-D）**：評測、自動套用、Live 驗證、撤銷安全完成；基線 962 → 983 →（不變）→ 994
- **2026-10-10（Security Audit 1＋SR-1＋SR-2）**：稽核與兩輪安全修復完成；基線 1013 → 1049
- **2026-10-11（Phase 3／UX 修整）**：垃圾桶與資料生命週期完成（基線 1052 → 1073）；UX 手機優先修整完成
- **2026-10-11（本修訂）**：合併重複的兩代 Phase 規劃為單一藍圖；垃圾桶與資料生命週期標記完成並對齊實作（`status='void'`、還原、使用者明示永久刪除、無自動過期）；`deleted_at`／30 天清除與 FTS5 標示為未採納或未排程；移除已被實作取代的重複章節
- **2026-10-11（capture 流程修正）**：拍照建檔改為「確認儲存才建立正式紀錄」——審閱階段只做草稿分析（`POST /api/inbox/analyze`，不建紀錄），「存起來」才 intake＋建議；取消清理 inbox 暫存（`POST /api/inbox/discard`）；自規劃移除相機記憶卡大量照片匯入（`/unsorted`，非已確認需求）
