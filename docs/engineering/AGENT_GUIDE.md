# Agent Engineering Guide

ItemTrace 工程施工流程與規則。所有 Agent 必須遵守。

---

## 開始工作前

### 1. 瞭解當前狀態

每次施工開始時，依序閱讀（不必全部背下，但要掌握脈絡）：

1. **`docs/engineering/STATUS.md`** —— 當前真實狀態
   - 最新測試結果
   - 已完成 vs 未完成功能
   - 下一個明確任務
   - 已知問題與阻塞

2. **`docs/engineering/ROADMAP.md`** —— 施工藍圖
   - 各 Phase 的目標與範圍
   - 工作依賴關係
   - 資料庫遷移策略

3. **`docs/engineering/DECISIONS.md`** —— 技術決策
   - 關鍵設計選擇與取捨
   - 開放問題與決策待決

4. **`docs/product-v3/*.md`** —— 產品規格（選讀）
   - 不必全讀，但涉及 UX 改動時應檢查相關文件

### 2. 確認 Git 與未提交工作

執行並檢查結果：

```bash
git status --short --branch
git diff --stat
git diff --cached --stat
git log -3 --oneline
```

**必須執行的驗證**：
- [ ] 當前 branch 是否正確（通常 `main`）
- [ ] 本地與遠端是否同步（`0 ahead, 0 behind`）
- [ ] 未提交修改是什麼（modified vs untracked）
- [ ] 是否有 Git conflict 或其他異常

**禁止操作**：
- 不可執行 `git reset --hard` 或 `git clean -fd`
- 不可使用 `git checkout -- .` 覆蓋未知修改
- 不可無差別執行 `git add .` 後再 commit
- 如果不確定，詢問或報告，不要擅自決定

---

## 施工時

### 3. 一次只處理一個主要目標

遵守「單一責任」原則：

- 一個 commit ≈ 一個 Phase 工作 ≈ 一個邏輯完整的功能
- 不要在同一個 commit 中混合無關的修改
- 如果發現需要做額外工作，先記錄到 STATUS，完成當前目標後再評估

### 4. 優先重用現有資源

新增功能前，檢查：

- **API 端點**：需要的端點是否已經存在？（查 `shop/api.py` 與 `GET /api/docs`）
- **資料庫表與欄位**：所需欄位是否已存在？（查 `shop/schema.sql`）
- **測試**：是否已有相關測試？（查 `tests/test_*.py` 中的相似測試用例）
- **前端元件**：所需 UI 元件是否已實作？（查 `web/views/*.js` 與 `web/core/*.js`）

**查證清單**：
```bash
# 檢查 API
curl -s http://127.0.0.1:8731/api/docs | grep -i "<path>" | head -20

# 檢查 schema
grep -n "your_field" shop/schema.sql

# 檢查測試
grep -r "your_functionality" tests/
```

### 5. 資料庫變更的明確說明

若需要修改 schema、新增欄位或 migration：

1. **說明必要性**：為什麼現有欄位不足？
2. **描述 Migration 策略**：
   - 向下相容性（舊資料如何處理）
   - 異常處理（migration 失敗時的回復策略）
3. **驗證計畫**：
   - 在測試環境執行 migration
   - 驗證舊資料與新資料的一致性
   - 確認索引與約束完整

**禁止**：
- 執行 migration 而不驗證
- 破壞舊資料而不提供回復方案
- 新增欄位而不填充預設值

### 6. 永久刪除的嚴格驗證

若涉及刪除紀錄、照片或檔案：

**必須確認以下三個層次都已清理**：
1. **搜尋索引** —— FTS5 虛擬表、快取、索引
2. **照片檔案** —— `files/` 目錄中的實體檔案
3. **資料庫紀錄** —— items、photos、observations、suggestions、events 等表中的相關紀錄

**驗證清單**：
```bash
# 確認照片檔案已移除
ls -la files/ITM-{item_id}/

# 確認資料庫無遺留
sqlite3 catalog.db "SELECT COUNT(*) FROM items WHERE id='ITM-xxxx';"

# 確認 events 記錄了刪除操作
sqlite3 catalog.db "SELECT * FROM events WHERE entity_id='ITM-xxxx' AND type='deleted';"
```

**交易回滾**：
- 若任何一步失敗，應回滾所有變更，確保資料一致性
- 記錄刪除日誌（time, item_id, file_count, reason）

### 7. 測試與回歸

完成功能後，**必須驗證**：

#### A. 新增測試通過
```bash
pytest tests/test_your_feature.py -v
```

#### B. 不能削弱既有測試
- 不可刪除測試
- 不可降低 assertion 強度
- 不可跳過失敗的測試（@pytest.skip 需理由）

#### C. 完整回歸測試
```bash
pytest -q  # 全部 pytest 測試
```

**預期結果**：
- 新功能對應測試通過
- 所有既有測試仍通過（或失敗原因可解釋）

**若測試失敗**：
- 首先分類原因：
  - 本次修改造成？
  - 既有 bug 暴露？
  - 環境問題？
- 修正根本原因，不得通過刪除測試來規避

---

## 完成與報告

### 8. 提供實際測試結果與變更摘要

完成工作後，清晰報告：

#### 測試結果
```
測試總數：921
通過：921 ✓
失敗：0
新增測試：+5（Phase X feature tests）
```

#### 變更摘要
```
修改檔案：
  - shop/api.py (新增 endpoint, +30 lines)
  - web/views/home.js (ui update, +15 lines)
  - tests/test_api.py (新增驗證, +25 lines)

刪除：
  - 無

新增：
  - 無
```

#### 剩餘問題
- 列出本次未解決但發現的新問題
- 標示優先級與建議解決順序

### 9. Git Checkpoint

**符合以下條件時才建立 commit**：

- [ ] 該 Phase 工作完整（無依賴等待）
- [ ] 所有新測試通過
- [ ] 完整 pytest 回歸通過
- [ ] 變更範圍清晰可審查
- [ ] 提交信息清楚描述做了什麼

**Commit 信息格式**：
```
feat: [phase] brief description

- Point 1
- Point 2
- Affected tests: test_*.py (+N new)
```

**示例**：
```
feat: phase-1a integrate V3 frontend and core validation

- Add web/ SPA frontend (Capture, Home, Detail, Settings)
- Add test_v3_core_slice.py with 5 core scenarios
- Update shop/api.py for SPA static routing
- All 921 tests pass (no regressions)
```

**未經要求不可自動 push**：
- 本地 commit 後，等待明確指示再 push
- 允許 code review 或進一步修改

### 10. 階段完成後更新 STATUS

每個 Phase 工作完成後，**必須更新** `docs/engineering/STATUS.md`：

```markdown
## 當前階段

**Phase X：[工作名稱]** ← **COMPLETED**

完成時間：2026-10-XX
Commit：abc1234

完成內容：
- ✓ 工作項 1
- ✓ 工作項 2

下一步：Phase X+1
```

**不要**：
- 更新 ROADMAP（除非工程計畫本身改變）
- 修改已通過的 Phase 描述
- 混淆「計畫」（ROADMAP）與「進度」（STATUS）

---

## 遇到問題時

### 11. 發現未知工作或資料風險

若施工中發現：
- 計畫未涵蓋的必要工作
- 資料一致性風險
- 工程方案衝突

**立即停止該 Phase**，並：
1. 清楚記錄問題到 DECISIONS 或 STATUS（Open Question）
2. 不繼續擴大實作
3. 報告並等待指示

### 12. 測試失敗無法修正

若新增功能導致測試失敗但無法修正：

1. 分析失敗原因
2. 評估是設計問題還是實作問題
3. 提議改進方案（可能需要 design change）
4. 停止該 Phase，等待決策

**不可**：
- 刪除失敗的測試
- 弱化 assertion
- 跳過失敗（除非有明確理由記錄在案）

---

## 檢查清單

每次開始工作前，逐項檢查：

- [ ] 已閱讀 STATUS / ROADMAP / DECISIONS
- [ ] 已確認 Git 狀態正常（無 conflict，本地與遠端同步）
- [ ] 瞭解本 Phase 的目標與驗收條件
- [ ] 已確認不會覆蓋使用者工作
- [ ] 已識別需要重用的現有資源
- [ ] 已規劃測試策略（new tests + regression）
- [ ] 已確認資料庫變更的 migration 方案（若需要）
- [ ] 已預估工時與依賴
- [ ] 知道如何報告完成狀態

完成工作後：

- [ ] 所有新測試通過
- [ ] 完整 pytest 回歸通過
- [ ] 已生成清晰的變更摘要
- [ ] 已更新 STATUS
- [ ] 已準備好 Git commit 或報告阻塞

---

## 修改歷史

- **2026-10-09**：初始版本建立

