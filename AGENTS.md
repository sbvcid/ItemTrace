# ItemTrace — Agent Workflow Entry Point

所有 Agent 施工開始時必須閱讀此文件。

---

## 快速導航

每次開始工作時，按順序進行：

### 1️⃣ 理解當前狀態（3 分鐘）
- 閱讀 [`docs/engineering/STATUS.md`](docs/engineering/STATUS.md)
  - 當前完成進度
  - 測試基線
  - 下一個明確任務

### 2️⃣ 瞭解工程藍圖（5 分鐘）
- 查看 [`docs/engineering/ROADMAP.md`](docs/engineering/ROADMAP.md)
  - 各 Phase 的目標與範圍
  - 工作依賴關係
  - 驗收條件

### 3️⃣ 掌握技術決策（3 分鐘）
- 參考 [`docs/engineering/DECISIONS.md`](docs/engineering/DECISIONS.md)
  - 已接受的設計決定
  - 取捨與理由
  - 開放問題

### 4️⃣ 遵守施工規則（5 分鐘）
- 必讀 [`docs/engineering/AGENT_GUIDE.md`](docs/engineering/AGENT_GUIDE.md)
  - 開始工作前的檢查清單
  - 施工時的禁止項與規則
  - 測試 & 提交規範
  - 問題處理流程

### 5️⃣ 檢查產品規格（按需）
- 涉及 UX 改動時查閱 [`docs/product-v3/`](docs/product-v3/)
- 重點檔案：IMPLEMENTATION-PLAN.md, FEATURE-PLAN.md, UX-DESIGN.md

---

## 項目概況

**產品定位**：「拍下來，AI 幫你記住，以後找得到。」

**核心流程**：Capture → AI Understand & Organize → Save → Retrieve

**技術棧**：
- 後端：Python + FastAPI + SQLite (WAL mode)
- 前端：零建置 ESM 純 JavaScript SPA
- 測試：pytest (1013 tests)
- 部署：local-first, 無外部依賴

**當前階段**：Phase 3 垃圾桶與刪除完成，UX 手機優先修整完成（推送至遠端）；下一步：Phase 4 分類系統與 AI 自動分類

---

## 主要責任文件

| 檔案 | 責任 | 更新頻率 |
|---|---|---|
| `docs/engineering/STATUS.md` | 當前真實進度狀態 | 每個 Phase 完成後 |
| `docs/engineering/ROADMAP.md` | 施工階段、依賴、驗收 | 工程計畫改變時 |
| `docs/engineering/DECISIONS.md` | 技術決策與取捨 | 新決策確定時 |
| `docs/engineering/AGENT_GUIDE.md` | 施工流程與規則 | 規則改變時 |
| `docs/product-v3/` | 產品規格 & UX | 產品方向改變時 |

---

## 開始工作

確認上述 5 個步驟後，開始實作。

**施工標準流程**：

1. **實作與測試**：實作功能 → 新增必要測試 → 執行完整測試套件 → 確保無迴歸
2. **品質檢查**：前端 JS 語法檢查 (`node --check`) → 代碼審查自身改動 → 確認文檔更新
3. **版本控制**：staged 所有改動 → 撰寫清晰的 commit 信息 → 提交到本機
4. **遠端同步**：檢查 origin 狀態 → 必要時 fetch/merge 處理衝突 → 快轉推送到 origin/main
5. **完成報告**：提供實際測試結果、修改摘要、commit SHA 與遠端確認

**例外情況** — 只在使用者明確要求時才改變流程：
- 「只做本機」→ 停在 commit，不推送
- 「草稿模式」→ 提交草稿 commit，待審后再推送
- 「緊急修復」→ 加速流程，跳過非必要驗證

一般程式開發工作應完整執行上述流程，包括推送。

若有疑問，參考 [`docs/engineering/AGENT_GUIDE.md`](docs/engineering/AGENT_GUIDE.md) 的「遇到問題時」章節。

---

祝施工順利！

