# ItemTrace — Agent Workflow Entry Point

所有 Agent 施工開始時必須閱讀此文件。

---

## 快速導航

依照任務性質閱讀必要的文件即可，不必每次開工都完整讀完所有規劃文件：

- **任何任務**：先看 [`docs/engineering/STATUS.md`](docs/engineering/STATUS.md) —— 當前進度、測試基線、下一個明確任務
- **施工規則**：[`docs/engineering/AGENT_GUIDE.md`](docs/engineering/AGENT_GUIDE.md) —— 開工檢查、施工禁項、測試 & 提交規範、問題處理
- **涉及計畫與依賴時**：[`docs/engineering/ROADMAP.md`](docs/engineering/ROADMAP.md)
- **涉及技術決策時**：[`docs/engineering/DECISIONS.md`](docs/engineering/DECISIONS.md)
- **涉及 UX 改動時**：查閱 [`docs/product-v3/`](docs/product-v3/) 相關文件 —— 產品文件是背景與參考；實作以目前的明確要求與已確認決定為準
- **涉及資料模型與歷史設計時**：[`SPEC-v1.md`](SPEC-v1.md)（歷史 v1 規格，僅供參考）

---

## 項目概況

**產品定位**：「拍下來，AI 幫你記住，以後找得到。」

**核心流程**：Capture → AI Understand & Organize → Save → Retrieve

**技術棧**：
- 後端：Python + FastAPI + SQLite (WAL mode)
- 前端：零建置 ESM 純 JavaScript SPA
- 測試：pytest (1083 tests)
- 部署：local-first, 無外部依賴

**當前階段**：Phase 3 垃圾桶與刪除完成，UX 手機優先修整完成，工程文件清理完成（均已推送）；下一個候選：Phase 4 分類系統與 AI 自動分類（啟動前需確認範圍）

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

**施工標準流程**：

1. **檢查現況**：`git status`／`git log` 辨認既有未提交修改的歸屬（用來避免覆蓋既有工作，不是開工門檻）；依任務閱讀必要文件
2. **實作**：按任務範圍實作；優先重用既有端點、欄位、測試與元件
3. **適當測試**：測試範圍按修改風險決定——程式碼變更跑相應測試＋完整 pytest 回歸；純文件修訂做 Markdown／編碼／連結檢查即可
4. **修正問題**：發現問題先調查、修復、驗證；能繼續完成的部分就繼續
5. **版本控制**：只 stage 屬於本次任務的變更（不要無差別 `git add .`）→ 清晰的 commit 信息
6. **遠端同步**：fetch 檢查 origin → 必要時整合衝突 → 推送到 origin/main → 確認遠端與本機 HEAD 一致
7. **完成報告**：實際測試結果、修改摘要、commit SHA 與遠端確認

**例外情況** — 只在使用者明確要求時才改變流程：
- 「只做本機」→ 停在 commit，不推送
- 「草稿模式」→ 提交草稿 commit，待審后再推送
- 「緊急修復」→ 加速流程，跳過非必要驗證

一般程式開發工作應完整執行上述流程，包括推送。

若有疑問，參考 [`docs/engineering/AGENT_GUIDE.md`](docs/engineering/AGENT_GUIDE.md) 的「遇到問題時」章節。

---

祝施工順利！

