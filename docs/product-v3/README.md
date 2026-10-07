# ItemTrace V3 — Product Proposal

> 狀態：Proposal（設計提案，尚未施工）
> 日期：2026-10-07
> 範圍：產品重新定義 → UX 架構 → 視覺系統 → 前端架構 → 後端演進分級 → 施工階段
> 前提：舊 frontend（`ui/`）已移除，不作為設計約束；backend（`shop/`）視為成熟資產。

---

## 一句話

**ItemTrace V3 是一份「實體物品的可信履歷」：用手機在一分鐘內把一件東西變成一份會持續長大的紀錄，日後找得到、認得出、而且證明得了它當時的樣子。**

V2 是「一個有 Inbox、列表、詳細頁的資料管理工具」。
V3 是「物品履歷」：拍照即建檔、AI 打草稿、人確認、在每一次物品**轉手的時刻**追加快照、用一張貼在實體上的 QR 標籤把實體與紀錄綁在一起。

---

## 閱讀順序

給下一個 Agent：**依序讀完 1–5 才動手寫任何 code。** 6–14 是施工時的規格。

| # | 文件 | 回答的問題 |
|---|---|---|
| 1 | [PRODUCT-VISION.md](PRODUCT-VISION.md) | 這個產品是什麼、為什麼存在、原則、Flywheel |
| 2 | [TARGET-USERS.md](TARGET-USERS.md) | 為誰設計、不為誰設計 |
| 3 | [JOB-TO-BE-DONE.md](JOB-TO-BE-DONE.md) | 使用者雇用 ItemTrace 做什麼、核心使用情境 |
| 4 | [PRODUCT-ARCHITECTURE.md](PRODUCT-ARCHITECTURE.md) | 產品物件模型、狀態模型、重大決策紀錄（Inbox、Item、Timeline…） |
| 5 | [INFORMATION-ARCHITECTURE.md](INFORMATION-ARCHITECTURE.md) | 導覽、路由、畫面清單、術語表 |
| 6 | [USER-JOURNEYS.md](USER-JOURNEYS.md) | 11 條完整旅程，逐階段的目標／摩擦／回應／錯誤 |
| 7 | [AI-EXPERIENCE.md](AI-EXPERIENCE.md) | AI 的角色、審核模型、狀態、失敗處理 |
| 8 | [FEATURE-PLAN.md](FEATURE-PLAN.md) | Core / Important / Optional / Future / Reject；Keep / Change / Merge / Remove / Add |
| 9 | [BACKEND-IMPACT.md](BACKEND-IMPACT.md) | Level 0–3 後端變更規格、不可動的資產 |
| 10 | [UX-DESIGN.md](UX-DESIGN.md) | 互動模型、畫面規格、狀態、Responsive 策略、無障礙 |
| 11 | [VISUAL-DIRECTION.md](VISUAL-DIRECTION.md) | 視覺方向、字體、色彩角色、照片處理、AI 呈現 |
| 12 | [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) | Tokens、元件規格 |
| 13 | [FRONTEND-ARCHITECTURE.md](FRONTEND-ARCHITECTURE.md) | `web/` 結構、技術選型、狀態、上傳佇列、測試 |
| 14 | [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | 施工階段、驗收標準、風險與取捨 |

---

## 十個最重要的產品變化

| # | 變化 | 一句話理由 |
|---|---|---|
| 1 | **定位收斂為「可信履歷」**，不是泛用居家盤點 | backend 最強的資產是 provenance；泛用盤點是低留存的擁擠市場 |
| 2 | **Inbox 作為一個「地方」被移除**，改成「拍照建檔 Capture Session」+ 只在有東西時出現的「未整理照片」 | 使用者想建立的是「一件東西」，不是「整理一堆照片」 |
| 3 | **Observation → 快照 Snapshot，並且帶「目的」**（取得、出貨前、收回、維修…） | 有價值的紀錄發生在物品轉手的時刻 |
| 4 | **Item Detail → 物品履歷 Dossier**：照片優先、身分其次、時間軸收尾 | 打開一件東西時，第一個問題是「是這個嗎？」 |
| 5 | **Events + Observations 合併成一條時間軸** | 使用者不區分「資料變更」和「拍照紀錄」，他只想知道「發生過什麼」 |
| 6 | **AI 從按鈕變成背景草稿員**：拍完自動辨識、建議直接長在欄位上、識別碼一律逐筆確認 | AI 的價值是省掉打字，不是多一個要記得按的按鈕 |
| 7 | **「待確認」是一個衍生的佇列**，不是 Item 的狀態 | 尊重 backend「沒有 draft」的決策，同時給使用者明確的待辦 |
| 8 | **列印 → 標籤 Label，帶 QR 連回履歷** | 讓實體物品自己帶著通往紀錄的入口，形成回訪迴圈 |
| 9 | **Evidence Export → 證據包**：一個 zip + 一份人看得懂的報告 | 需要證據的對象（買家、平台客服、保險）讀不懂 JSON |
| 10 | **手機是一級公民**：Capture 與查詢以 390px 為主場設計；桌機負責審核、整理、輸出 | 物品在哪裡，拍照就在哪裡；印表機在哪裡，輸出就在哪裡 |

---

## 後端結論（摘要）

* **V3 不需要任何 Level 3（核心資料模型破壞性）變更。** 六張核心表、events／revert、suggestion 與事實分離、identifier 正規化與撞號語意、照片不可變與 sha256、intake 原子性、template allowlist、預覽即列印 pipeline、AI key 安全模型 —— 全部原樣保留。
* 需要的是一組 **Level 1** 小型增補（SPA 服務、縮圖、列表衍生欄位、修改後接受、supersede、證據 zip、capture session、QR binding、網路資訊、備份 API）與四項 **Level 2**（AI 背景工作、證據報告、快照目的欄位與遷移機制、LAN 開關）。
* 詳見 [BACKEND-IMPACT.md](BACKEND-IMPACT.md)。

> 結論的語氣是：**資料模型是對的，錯的是包在它外面的產品形狀。**

---

## 最終 IA（摘要）

```text
手機（底部列）           桌機（左側欄）
┌──────────────────┐    ┌──────────────┬──────────────────────────┐
│ 物品庫 │ ◉拍照 │ 待確認 │    │ 物品庫        │                          │
└──────────────────┘    │ 待確認  (3)   │      內容區               │
                        │ 未整理照片 (12)*│                          │
                        │ ─────────    │                          │
                        │ 設定          │                          │
                        └──────────────┴──────────────────────────┘
                        * 只在非空時出現

物品履歷 /i/ITM-0042   ← QR 標籤直接開這裡
  照片 → 身分（含 AI 建議）→ 事實與識別碼 → 時間軸（快照 + 變更）
  動作：新增快照 · 標籤 · 證據包 · ⋯（標記離手／作廢／比對快照）
```

---

## 文件撰寫原則

* 每個重大決策都以 **Problem → Insight → Decision → Why → Trade-off → Alternative** 記錄（集中在 [PRODUCT-ARCHITECTURE.md §5](PRODUCT-ARCHITECTURE.md#5-重大決策紀錄)）。
* 中文為主、技術名詞保留英文；UI 文案以 zh-TW 為準，en 為對照。
* 「backend 名稱」與「產品名稱」分開記錄（術語表見 [INFORMATION-ARCHITECTURE.md §7](INFORMATION-ARCHITECTURE.md#7-術語表)）。施工時 API 用 backend 名稱，UI 只出現產品名稱。

