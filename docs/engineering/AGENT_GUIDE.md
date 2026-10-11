# Agent Engineering Guide

ItemTrace 工程施工流程與規則。所有 Agent 必須遵守。

核心立場：文件是協助工作的工具，不是停工的理由。遇到一般工程問題先自行調查、修復、驗證，能繼續完成的部分就繼續；只有真正阻塞（需要不可替代的使用者資訊、或無法安全解決）才停下回報。

---

## 開始工作前

### 1. 依任務了解現狀

按任務性質閱讀必要文件即可，不必每次全讀：

1. **`docs/engineering/STATUS.md`** —— 當前真實狀態（最新測試結果、已完成 vs 未完成、下一個明確任務、已知問題）
2. **`docs/engineering/ROADMAP.md`** —— 需要計畫脈絡與依賴時
3. **`docs/engineering/DECISIONS.md`** —— 涉及技術決策時
4. **`docs/product-v3/*.md`** —— 涉及 UX 改動時檢查相關文件（參考定位，見其 README）
5. **程式碼本身** —— 以實際程式與測試為準；文件與程式衝突時，以程式與目前明確要求為準，並順手修正文件

### 2. 檢查 Git 與工作區（辨認用途，不是開工門檻）

執行並檢查結果：

```bash
git status --short --branch
git diff --stat
git diff --cached --stat
git log -5 --oneline
```

檢查目的：

- [ ] 當前 branch 是否正確（通常 `main`）
- [ ] 未提交修改是什麼、屬於誰（modified vs untracked）——用來辨認既有工作、避免覆蓋、避免混入無關提交
- [ ] 是否有 Git conflict 或其他異常

工作區不乾淨或本機與遠端不同步**不是停工理由**：先 `git fetch origin` 了解遠端是否前進，辨認修改歸屬後照常開工；push 前再整合遠端即可。

**禁止操作**（資料防護）：

- 不可執行 `git reset --hard` 或 `git clean -fd`
- 不可使用 `git checkout -- .` 覆蓋未知修改
- 不可無差別執行 `git add .` 後再 commit——只 stage 屬於本次任務的變更
- 破壞性操作（刪除、覆蓋、schema 變更）前先確認目標與回復路徑

---

## 施工時

### 3. 一次只處理一個主要目標

- 一個 commit ≈ 一個邏輯完整的功能或修復；不要在同一個 commit 混合無關修改
- 與當前任務直接相關的問題就地修復；無關的額外工作記錄到 STATUS，不擅自擴大範圍
- 發現計畫未涵蓋的工作時：先評估是否屬於目前任務的合理延伸。是 → 直接做；否 → 記錄並繼續目前目標，不必停下等待指示

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

若涉及刪除紀錄、照片或檔案，重用 Phase 3 既有實作的防線（不要繞過）：

**必須確認的清理層次**：

1. **資料庫紀錄** —— items、observations、photos、identifiers、suggestions 與全部相關 events，於單一交易內清除
2. **照片檔案** —— `files/<item_id>/` 整棵目錄樹（交易提交前先可逆改名至 `.purge/`，提交後才真正移除）
3. **搜尋** —— 現行搜尋直接查詢資料表（無獨立索引表），DB 清乾淨即完成；未來若引入 FTS5，索引清理必須一併驗證

**既有防線**：

- 永久刪除僅限 `status='void'`（垃圾桶）紀錄；active／archived 回 400
- 刪檔失敗回 500（`PurgeError`）並列出完整路徑——不假裝完整刪除；鎖檔時中止且 DB 零變更
- 編號不回收（`schema_meta.items_seq`）
- **不做自動過期清除**——永久刪除只能由使用者明確執行

**驗證清單**：

```bash
# 確認照片檔案已移除
ls files/ITM-{item_id}/

# 確認資料庫無遺留
sqlite3 catalog.db "SELECT COUNT(*) FROM items WHERE id='ITM-xxxx';"

# 確認 events 無遺留（purge 會連同事件一併清除）
sqlite3 catalog.db "SELECT COUNT(*) FROM events WHERE entity_id='ITM-xxxx';"
```

### 7. 測試範圍按修改風險決定

| 變更類型 | 測試要求 |
|---|---|
| 產品程式碼（`shop/`、`web/`、`serve.py`） | 相關測試通過＋完整 `pytest -q` 回歸 |
| 測試檔本身 | 該檔測試＋完整回歸 |
| `tools/`、腳本 | 該工具的測試；影響產品行為時完整回歸 |
| 純文件（`*.md`）、註解 | Markdown／編碼／連結檢查＋`git diff --check`；不需完整 pytest |

#### 不可削弱既有測試

- 不可刪除測試
- 不可降低 assertion 強度
- 不可跳過失敗的測試（skip 需理由並記錄）

#### 若測試失敗

- 先分類原因：本次修改造成？既有 bug 暴露？環境問題？
- 修正根本原因，不得通過刪除測試來規避
- 無法立即修復時：與問題無關的部分照常完成（見「遇到問題時」）

---

## 完成與報告

### 8. 提供實際測試結果與變更摘要

完成工作後，清晰報告：

#### 測試結果

```
測試總數：1073
通過：1073 ✓
失敗：0
新增測試：+N（本次功能測試）
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

成立條件（不要求整個 Phase 完成；邏輯完整的單元即可提交）：

- [ ] 這個邏輯單元完整、自查無誤
- [ ] 依 §7 的風險範圍完成測試並通過
- [ ] 只包含本次任務的變更（無關的既有修改不混入）
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
- All 1073 tests pass (no regressions)
```

### 10. 遠端同步與推送

完成 commit 後：

1. **檢查 origin 狀態**：

   ```bash
   git fetch origin
   git status --branch
   ```

2. **處理衝突**（若遠端前進）：
   - 先整合（merge origin/main 或 rebase），不覆蓋遠端變更
   - 解決衝突，測試通過後再推送

3. **推送**：

   ```bash
   git push origin main
   ```

4. **驗證**：確認 `git rev-parse HEAD origin/main` 一致

**不自動 push 的例外情況**（僅限使用者明確要求）：

- 使用者明確要求「只做本機」
- 使用者明確要求「草稿模式」
- 使用者明確要求「不推送」

### 11. 完成報告

提交推送後，提供清晰的實作報告，包括：

1. **實際做了什麼** —— 功能、改動、決策
2. **測試結果** —— pytest／靜態檢查／瀏覽器測試
3. **Commit SHA** —— 本地與遠端確認
4. **尚未解決的問題** —— 具體事項、優先級、建議解決順序

---

## 遇到問題時

### 12. 問題處理原則：調查 → 修復 → 驗證 → 繼續

發現計畫外的必要工作、資料一致性風險或工程方案衝突時：

1. **先調查**：確認問題真實性與影響範圍（跑測試、讀程式、查文件）
2. **能修就修**：一般工程問題自行採取合理方案修復並驗證
3. **能繼續就繼續**：與問題無關的部分照常完成，不要整體停工
4. **記錄**：把發現與處理寫進 STATUS（必要時 DECISIONS 開放問題）
5. **真正阻塞才回報**：僅限「必須由使用者提供不可替代的資訊」或「無法安全解決（有資料損失風險）」；回報時附上已嘗試的方案與建議

**資料安全紅線**（不受上述影響）：任何可能破壞既有資料的操作（migration、永久刪除、覆蓋檔案），先確認備份／回復路徑再動手；做不到安全保護時，停止**該操作**並回報——但不因此停止任務的其他部分。

### 13. 測試失敗無法立即修正

1. 分析失敗原因（本次修改？既有 bug？環境問題？）
2. 修正根本原因；是設計問題就調整設計
3. 短時間無法修正且不阻塞任務其他部分：記錄到 STATUS，繼續能完成的部分
4. 阻塞任務本身時才回報並說明已嘗試的方案

**不可**：

- 刪除失敗的測試
- 弱化 assertion
- 無理由跳過（skip 需明確理由並記錄在案）

---

## 檢查清單

開始工作前，逐項檢查：

- [ ] 已依任務閱讀必要文件（至少 STATUS）
- [ ] 已檢查 Git 狀態：辨認未提交修改歸屬與遠端位置（目的是避免覆蓋，不是門檻）
- [ ] 瞭解本任務的目標與驗收條件
- [ ] 已確認不會覆蓋使用者工作
- [ ] 已識別需要重用的現有資源
- [ ] 已規劃測試策略（按 §7 風險範圍）

完成工作後：

- [ ] 依風險範圍的測試通過
- [ ] 已生成清晰的變更摘要
- [ ] STATUS 已更新（進度、測試基線、下一步）
- [ ] 已 commit 並 push，遠端與本機 HEAD 一致

---

## 修改歷史

- **2026-10-09**：初始版本建立
- **2026-10-11**：移除停工式規則（本遠端同步門檻、整 Phase 才可提交、額外工作即停工等待指示、文件任務強制完整回歸、測試失敗即全面等待決策）；改為風險導向測試與「調查→修復→驗證→繼續」問題處理；永久刪除章節對齊 Phase 3 實作；去除重複章節並修正編號
