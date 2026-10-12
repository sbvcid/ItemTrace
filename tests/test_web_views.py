"""前端視圖的靜態完整性檢查。

P0 迴歸：詳情頁的 `renderDetail` 參照了 UI 精簡時已移除的 `#status-badge`
元素 —— `querySelector` 回傳 null，`statusBadge.textContent = …` 直接拋
TypeError，整個 render 中斷；`loadDetail` 的 catch 又把所有例外一律標成
「找不到此紀錄」，於是 API 明明回 200，每個既有紀錄卻都顯示找不到。

pytest 環境沒有瀏覽器，所以這裡用原始碼層級的護欄釘住兩件事：
1. 視圖查詢的每個 element id 都必須在同一檔案宣告（此類災情的唯一入口）。
2. 詳情頁的錯誤分類必須以 404 為界，其餘錯誤各有符合實際狀況的訊息。

真實瀏覽器行為以人工驗收（見交付報告），不在此自動化範圍。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

QUERY_ID = re.compile(r"querySelector\(\s*['\"]#([a-zA-Z0-9-]+)['\"]\s*\)")
DECLARED_ID = re.compile(r"id=[\"']([a-zA-Z0-9-]+)[\"']")


def test_every_queried_element_id_is_declared_in_the_same_file():
    """`querySelector('#id')` 的每個 id 都必須在該檔案有 `id="…"` 宣告。

    （動態產生的節點——例如 renderDetail 寫入 innerHTML 後再查詢——其
    `id="…"` 也出現在同一份原始碼字串中，因此同樣會被計入。）
    """
    offenders: dict[str, list[str]] = {}
    for path in sorted(WEB.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        queried = set(QUERY_ID.findall(text))
        declared = set(DECLARED_ID.findall(text))
        missing = sorted(queried - declared)
        if missing:
            offenders[path.relative_to(WEB).as_posix()] = missing
    assert offenders == {}, f"查詢了不存在的元素 id（會回 null）：{offenders}"


def test_detail_view_classifies_errors_before_showing_not_found():
    """只有後端確實回 404 才顯示「找不到此紀錄」；其餘錯誤分流並可重試。"""
    source = (ROOT / "web" / "views" / "record-detail.js").read_text(encoding="utf-8")

    # 404 分支存在，且 not-found 文案只在該分支使用
    assert "status === 404" in source
    assert "t('detail.notFoundTitle')" in source

    # 各錯誤情境的訊息與重試入口
    for key in (
        "detail.loadErrorTitle",
        "detail.errorAuthTitle",
        "detail.loadErrorServer",
        "detail.loadErrorNetwork",
        "detail.retry",
    ):
        assert f"t('{key}'" in source, f"record-detail.js 缺少 {key}"
    assert "btn-detail-retry" in source

    # 已被 UI 精簡移除的 status badge 不得再被查詢（災情根因）
    assert "#status-badge" not in source


def test_detail_error_keys_exist_in_both_locales():
    """新增的錯誤訊息 key 必須同時存在 zh-TW 與 en。"""
    keys = (
        "loadErrorTitle",
        "errorAuthTitle",
        "loadErrorServer",
        "loadErrorNetwork",
        "retry",
    )
    for name in ("zh-TW.js", "en.js"):
        text = (WEB / "i18n" / name).read_text(encoding="utf-8")
        for key in keys:
            assert re.search(rf"\b{key}\s*:", text), f"{name} 缺少 {key}"


def test_capture_review_surfaces_all_generated_suggestions():
    """審閱畫面必須呈現並可編輯動態屬性（含描述）與識別碼，才能按「存起來」。

    迴歸目標：舊版只渲染固定欄位 —— attribute:* 建議會被存檔流程
    靜默套用，使用者看不到、改不到、也刪不掉。
    """
    source = (ROOT / "web" / "views" / "capture.js").read_text(encoding="utf-8")
    assert "attribute:" in source, "審閱必須認得 attribute:<key> 建議"
    assert "edit-description-list" in source, "描述候選列必須有編輯區塊"
    assert "edit-attributes-list" in source, "動態屬性必須有編輯列"
    assert "btn-add-attribute" in source, "使用者必須能自行新增屬性"
    assert "edit-identifiers-list" in source, "識別碼必須有可編輯列"
    assert "btn-toggle-edit" in source, "修改入口必須存在"
    assert "draft-actions" in source, "操作區必須存在（存起來／修改／取消）"


def test_capture_description_candidates_are_visible_and_resolvable():
    """多筆 attribute:description 候選（不同照片、不同值）必須全部可操作。

    迴歸目標（本修正的核心缺陷）：舊版只把第一筆描述讀進單一輸入框、
    其餘描述列被排除在編輯 UI 之外，但存檔驗證又檢查重複的 attribute
    key —— 使用者被阻止存檔，卻找不到也無法移除那筆多出來的候選
    （驗證會檢查、介面卻無法操作的隱藏列死結）。
    """
    source = (ROOT / "web" / "views" / "capture.js").read_text(encoding="utf-8")

    # 描述候選專屬區塊：渲染「全部」描述列（不再只讀第一筆、也不再排除其餘）
    assert "edit-description-list" in source
    assert "renderDescriptionEditRows" in source
    assert "attributeRows.filter(r => r.key === 'description')" in source

    # 明確選擇機制：多筆候選時以 radio 選取要保存的一筆（不沉默擇一）
    assert "isPrimary" in source
    assert "chosenDescriptionRow" in source
    assert "description-primary" in source
    assert "descriptionChooseRequired" in source

    # 未選取候選的呈現與保存語意：看得見、標「未採用」、不寫入主表
    assert "descriptionNotUsed" in source
    assert "descriptionMultiHint" in source
    assert "addDescription" in source
    assert "removeDescription" in source

    # 重試：曾寫入的舊描述值 value-aware 清除，不誤刪新選取的值
    assert "descriptionRemovals" in source
    assert "descriptionDeletes" in source

    # 每一列都能：修改（textarea 寫回）、移除（✕）、選擇（radio）、
    # 辨識來源照片（inspectPhoto 按鈕）
    body = _function_body(source, "function renderDescriptionEditRows()")
    assert "row.value = valueInput.value" in body
    assert "✕" in body
    assert "radio" in body
    assert "inspectPhoto" in body

    # 存檔決策：未選取的描述候選一律未採用（不會被後面的 accept 覆蓋）
    save_body = _function_body(
        source, "btnSaveConfirm.addEventListener", end_marker="\n  });")
    assert "chosenDescription" in save_body
    assert "unchosenDescription" in save_body

    # 驗證訊息與新文案：雙語齊全
    for name in ("zh-TW.js", "en.js"):
        text = (WEB / "i18n" / name).read_text(encoding="utf-8")
        for key in (
            "descriptionPrimary",
            "descriptionNotUsed",
            "descriptionMultiHint",
            "descriptionChoiceHint",
            "descriptionChooseRequired",
            "descriptionSetPrimary",
            "addDescription",
            "removeDescription",
        ):
            assert re.search(rf"\b{key}\s*:", text), f"{name} 缺少 {key}"


def _function_body(source: str, signature: str, end_marker: str = "\n  }\n") -> str:
    """抓兩格縮排函式（到同層收尾）的原始碼片段。"""
    start = source.index(signature)
    end = source.index(end_marker, start)
    return source[start:end]


def test_capture_validates_before_intake():
    """名稱為必填、屬性 key 驗證（規則／重複／缺名）必須在第一次
    api.intake 之前完成 —— 驗證失敗不留半套正式紀錄。"""
    source = (ROOT / "web" / "views" / "capture.js").read_text(encoding="utf-8")
    assert "validateDraftForSave" in source
    assert "ATTRIBUTE_KEY_RE" in source
    # 驗證的呼叫必須出現在 api.intake 之前
    assert source.index("validateDraftForSave()") < source.index("api.intake(")
    # 不合法 key 不得進入正式資料（驗證不通過直接 return，尚未 intake）
    assert "return;" in source

    for name in ("zh-TW.js", "en.js"):
        text = (WEB / "i18n" / name).read_text(encoding="utf-8")
        for key in (
            "nameRequired",
            "attributeKeyInvalid",
            "attributeKeyDuplicate",
            "attributeKeyMissing",
        ):
            assert re.search(rf"\b{key}\s*:", text), f"{name} 缺少 {key}"


def test_detail_view_renders_description_as_reading_entry():
    """詳情頁以標題＋描述為主要閱讀入口；描述不重複列在補充資訊。"""
    source = (ROOT / "web" / "views" / "record-detail.js").read_text(encoding="utf-8")
    assert "detail-description" in source
    assert "key !== 'description'" in source
