# 出貨單排版技術（保留資產）

SPEC-v1 §9 指名保留的技術資產：**出貨單的 mm 級版面控制與標籤機列印**。
未來做獨立出貨單模組時直接重用（§13 擴充點「出貨單」）。

## 為什麼和 v1 主程式分開

原本這些檔案在舊概念驗證版本（交易紀錄）裡，和 v1 的資料模型完全無關。
舊版混入了賣家本人的姓名、電話、地址與社群 QR，不適合放在公開 repo，
已全部移除，只留下排版技術本身。

## 檔案

| 檔案 | 內容 |
|---|---|
| `shipping.html` | 版面骨架，聯絡資訊為 placeholder |
| `shipping.css` | mm / pt 級定位，列印尺寸與 `@page` 控制 |
| `shipping.js` | 尺寸切換、縮放預覽、網址參數帶入 |

純原生 HTML/CSS/JS，**不建置、不依賴框架**，開啟 `shipping.html` 即可預覽。

## 技術重點

- 尺寸用 `mm` 定位，`@page { size: 101.6mm 152.4mm }` 控制實際列印範圍，
  預覽縮放用 `transform: scale()`，所以畫面放大不會影響實際列印尺寸
- 商品固定三列高度（`.goods-row { height: 3.9mm }`），填幾行版面都不會跑掉
- 可切 4×6 吋與 100×150 mm，選擇記在 `localStorage`
- 網址參數：`?i=品名1|品名2&n=序號&c=編號&x=備註&d=日期&s=4x6`

## 接回 v1

只需讀 `items` / `identifiers` 填欄位即可，不需修改 v1 的資料模型或 API。
序號欄位對應 `identifiers.value`，編號欄位對應 `items.id`。

## 已移除

- `logo.png`（賣家個人 logo）
- `qr.png`（社群 QR 碼）
- 姓名、電話、地址、社群連結 —— 全部改為 placeholder 或註解

`.card .logo` 與 `.foot .qr` 的 CSS 定位規則保留著，方便日後放自己的圖。