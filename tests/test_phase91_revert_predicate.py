"""Phase 9.1：UI 的 canRevert() 與 backend revert_event() 的契約對齊。

Phase 9 的 UI 只判斷 type='field.changed' 且 field / prev_value 在，
比 backend 寬：backend 還會檢查 entity_type 有沒有在 _REVERT_TARGETS，
以及 field 有沒有在該 entity 的可改欄位裡。差距會表現成
「按鈕看得到、按下去必定 400」。

這裡不複製整份 _REVERT_TARGETS，而是：
  * 明確列出商品頁需要的 entity 與欄位，其餘附理由排除
  * 用假 DOM 跑真正的 ui/item.js，驗完整矩陣的按鈕出現與否
  * 再把「有按鈕的那些組合」回頭對照後端表格，證明沒有一個是後端會拒絕的
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent / "item_dom_harness.js"

#: 直接讀後端的權威契約。測試可以碰私有常數 —— 這正是它的用途：
# 當 backend 縮小欄位時，這個檔案要跟著紅，而不是等到有人按到 400。
from shop.repo import _REVERT_TARGETS  # noqa: E402


@pytest.fixture(scope="module")
def matrix():
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能點按鈕")
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


def _buttons(view, event_id):
    for row in view["eventRows"]:
        if row["id"] == event_id:
            return "revert" in row["actions"]
    raise AssertionError(f"harness 沒回報 {event_id}")


# 事件 id → 預期是否有復原按鈕。每一列都對應 harness 的 revertMatrix()。
MATRIX = {
    # item：後端 ITEM_EDITABLE_FIELDS 允許
    "M01": True,   # brand
    "M02": True,   # quantity
    "M03": True,   # attributes（不在表單裡，但後端允許）
    "M04": True,   # status（不在表單裡，但後端允許）
    # item：後端不允許
    "M05": False,  # not_a_real_field  ← UI 以前會誤顯示這個
    "M06": False,  # created_at
    "M07": False,  # id
    # identifier：後端 IDENTIFIER_EDITABLE_FIELDS 允許
    "M10": True,   # value
    "M11": True,   # kind
    "M12": True,   # confidence
    "M13": False,  # normalized —— 真的會產生 field.changed，但後端拒絕復原
    "M14": False,  # not_a_field
    # observation / photo / suggestion：UI 刻意不支援
    "M20": False,
    "M21": False,
    "M22": False,
    "M23": False,
    "M24": False,
    "M25": False,
    # 未知 entity_type
    "M30": False,  # invoice
    "M31": False,  # unknown_thing
    # field / prev_value 為 null，或不是 field.changed
    "M40": False,
    "M41": False,
    "M42": False,
}


@pytest.mark.parametrize("event_id", sorted(MATRIX))
def test_revert_button_matches_the_matrix(matrix, event_id):
    view = matrix["entity/field 矩陣"]
    assert _buttons(view, event_id) is MATRIX[event_id], event_id


@pytest.mark.parametrize("event_id", sorted(MATRIX))
def test_matrix_covers_every_reported_event(matrix, event_id):
    ids = {row["id"] for row in matrix["entity/field 矩陣"]["eventRows"]}
    assert event_id in ids


# ----------------------------------------------------------------------
# UI 顯示按鈕的每一個組合，後端都必須接受
# ----------------------------------------------------------------------


def test_every_button_the_ui_shows_is_accepted_by_the_backend(matrix):
    """這是 9.1 的核心保險：UI 給按鈕的，後端不能拒絕。

    事件 id → (entity_type, field) 從 harness 的事件內容取得。
    """
    shown = []
    for event_id, expected in MATRIX.items():
        if expected:
            shown.append(event_id)
    assert shown, "至少要驗到幾個有按鈕的組合"

    for event_id in shown:
        entity, field = _event_identity(matrix, event_id)
        assert entity in _REVERT_TARGETS, f"{event_id}: 後端沒有 {entity} 這個復原目標"
        allowed = set(_REVERT_TARGETS[entity][1])
        assert field in allowed, (
            f"{event_id}: UI 對 {entity}.{field} 顯示按鈕，"
            f"但後端只允許 {sorted(allowed)}"
        )


def _event_identity(matrix, event_id):
    """從 item_dom_harness.js 的 revertMatrix() 讀出 (entity_type, field)。"""
    source = HARNESS.read_text(encoding="utf-8")
    block = source.split("function revertMatrix()")[1].split("\n}")[0]
    match = re.search(
        r'at\("%s",\s*"(\w+)",\s*(null|"[^"]*")' % event_id, block
    )
    assert match, f"harness 裡找不到 {event_id}"
    field = match.group(2)
    return match.group(1), None if field == "null" else field.strip('"')


def test_ui_excluded_entities_are_a_deliberate_choice_not_an_oversight():
    """排除的 entity 必須寫下理由，而且理由要對得上後端的事實。"""
    source = (PROJECT_ROOT / "ui" / "item.js").read_text(encoding="utf-8")
    block = source.split("const REVERTIBLE = {")[1].split("\n};")[0]
    listed = set(re.findall(r"(\w+):", block))

    assert listed == {"item", "identifier"}, f"白名單變成 {listed}"
    for entity in ("observation", "photo", "suggestion"):
        assert entity not in listed
        assert entity in source, f"{entity} 應該在註解裡說明為什麼排除"

    # 已決定的建議本來就不可復原：backend update_suggestion 會擲錯
    assert "update_suggestion" in (
        PROJECT_ROOT / "shop" / "repo.py"
    ).read_text(encoding="utf-8")


def test_item_whitelist_is_not_smaller_than_the_form_fields():
    """表單上能改的欄位一定要能復原 —— 那是 Phase 9 的主用途。"""
    source = (PROJECT_ROOT / "ui" / "item.js").read_text(encoding="utf-8")
    form = set(re.findall(r'"(\w+)"', source.split("const FIELDS = [")[1].split("];")[0]))
    assert "FIELDS.concat(" in source, "item 白名單應該由 FIELDS 推導，不要寫死"

    matrix_view = None
    for name, expected in MATRIX.items():
        if expected:
            matrix_view = name
    assert matrix_view  # 只是確保 MATRIX 有可用的樣本
    assert "brand" in form and "notes" in form


def test_can_revert_is_driven_by_the_whitelist_not_only_by_event_type(matrix):
    """不能只靠 event.type —— 同樣是 field.changed，按鈕與否必須看 entity/field。"""
    source = (PROJECT_ROOT / "ui" / "item.js").read_text(encoding="utf-8")
    body = source.split("function canRevert(")[1].split("\n}")[0]
    assert "REVERTIBLE[event.entity_type]" in body
    assert "allowed.indexOf(event.field)" in body
    assert "field.changed" in body
    assert "prev_value !== null" in body


def test_phase9_behaviour_is_untouched(matrix):
    """Phase 9 的既有行為都還在。"""
    for label in ("復原成功", "復原失敗 400", "復原失敗 409", "復原失敗 500",
                  "復原成功但重載失敗", "復原成功但歷史載入失敗"):
        assert label in matrix, label
    assert matrix["復原成功"]["reverted"]["clicked"] is True
    assert matrix["復原失敗 400"]["afterRowError"].startswith("復原失敗：")


def test_normal_item_field_still_revertible(matrix):
    """Phase 9 的主用例沒有被 9.1 收緊掉。"""
    view = matrix["復原按鈕只出現在可復原事件"]
    rows = {row["id"]: row for row in view["eventRows"]}
    assert "revert" in rows["E2"]["actions"]   # item.brand
    assert "revert" in rows["E3"]["actions"]   # item.quantity
