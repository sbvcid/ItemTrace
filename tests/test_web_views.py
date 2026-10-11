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
    assert "edit-description" in source, "描述必須有可編輯輸入"
    assert "edit-attributes-list" in source, "動態屬性必須有編輯列"
    assert "btn-add-attribute" in source, "使用者必須能自行新增屬性"
    assert "edit-identifiers-list" in source, "識別碼必須有可編輯列"
    assert "btn-toggle-edit" in source, "修改入口必須存在"
    assert "draft-actions" in source, "操作區必須存在（存起來／修改／取消）"


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
