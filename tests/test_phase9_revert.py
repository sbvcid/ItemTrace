"""Phase 9：事件復原 UI。

純 UI 測試，用 node 的 vm 在假 DOM 上跑真正的 ui/item.js，真的去點「復原」。

資料語意那一半（A → B → 復原 → A 的完整事件鏈、原事件不變）由後端負責，
這裡另外用真實的 Repository 端到端驗一次，因為那是 Phase 9 真正的價值：
復原本身必須變成一筆可追溯的新事件，而不是把舊事件改掉。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "item_dom_harness.js"

#: 可復原 = type='field.changed' 且 field 與 prev_value 都在
REVERTIBLE = {"E2", "E3"}
#: 不可復原：item.created、field 為 null、prev_value 為 null、suggestion.*、刪除事件
NOT_REVERTIBLE = {"E1", "E4", "N1", "N2", "N3", "N4", "N5"}


@pytest.fixture(scope="module")
def views():
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能點按鈕")
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


def _rows(views, label):
    return {row["id"]: row for row in views[label]["eventRows"]}


# ----------------------------------------------------------------------
# 1. 哪些事件有復原按鈕
# ----------------------------------------------------------------------


def test_revertible_field_changed_has_a_revert_button(views):
    rows = _rows(views, "復原按鈕只出現在可復原事件")
    for event_id in REVERTIBLE:
        assert "revert" in rows[event_id]["actions"], event_id
        assert rows[event_id]["disabled"] == [False]


@pytest.mark.parametrize("event_id", sorted(NOT_REVERTIBLE))
def test_non_revertible_events_have_no_button(views, event_id):
    """item.created、field 為 null、prev_value 為 null、suggestion 事件都不該有。

    按了必定 400 的按鈕不該出現。條件和後端 events.revert() 相同。
    """
    rows = _rows(views, "復原按鈕只出現在可復原事件")
    assert rows[event_id]["actions"] == [], event_id


def test_can_revert_matches_the_backend_predicate():
    """UI 的判斷條件必須和 shop/events.py 的 revert() 一致。"""
    source = (Path(__file__).resolve().parents[1] / "ui" / "item.js").read_text(
        encoding="utf-8"
    )
    body = source.split("function canRevert(")[1].split("\n}")[0]
    assert "field.changed" in body
    assert "event.field" in body
    assert "prev_value !== null" in body

    backend = (Path(__file__).resolve().parents[1] / "shop" / "events.py").read_text(
        encoding="utf-8"
    )
    revert = backend.split("def revert(")[1].split("return None")[0]
    assert "type = 'field.changed'" in revert
    assert 'row["field"]' in revert
    assert 'row["prev_value"] is None' in revert


# ----------------------------------------------------------------------
# 2-4. 成功路徑
# ----------------------------------------------------------------------


def test_revert_uses_the_existing_endpoint(views):
    assert "POST /api/events/E2/revert" in views["復原成功"]["calls"]


def test_revert_does_not_invent_an_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/events/{event_id}/revert" in paths
    # 沒有「全部復原」「批次復原」「時間點復原」之類的新端點
    revert_paths = [p for p in paths if "revert" in p]
    assert revert_paths == ["/api/events/{event_id}/revert"]


def test_revert_success_reloads_and_shows_the_new_value(views):
    row = views["復原成功"]
    assert row["reverted"]["clicked"] is True
    assert row["afterBrand"] == ""      # prev_value 寫回


def test_revert_creates_a_new_event_instead_of_editing_the_old_one(views):
    """復原必須留下新事件，原事件一個字都不能改。"""
    row = views["復原成功"]
    assert row["afterEventCount"] == "5"          # 原本 4 筆
    assert row["afterEventIds"][0] == "E5"       # 新的在最前面
    # 原本四筆都還在，而且順序沒變
    assert row["afterEventIds"][1:] == ["E1", "E2", "E3", "E4"]


def test_revert_leaves_the_original_event_row_untouched(views):
    rows = _rows(views, "復原成功")
    assert "field.changed" in rows["E2"]["text"]
    assert "華碩" in rows["E2"]["text"]


def test_revert_button_is_disabled_while_in_flight(views):
    assert views["復原成功"]["reverted"]["busyDuring"] is True


# ----------------------------------------------------------------------
# 5. 失敗不假裝成功
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "status"),
    [("復原失敗 400", 400), ("復原失敗 409", 409), ("復原失敗 500", 500)],
)
def test_revert_failure_shows_the_real_api_message(views, label, status):
    row = views[label]
    assert row["afterRowError"].startswith("復原失敗：")
    assert "HTTP" not in row["afterRowError"], "要顯示伺服器的訊息，不是籠統的狀態碼"


def test_revert_failure_does_not_remove_the_event(views):
    row = views["復原失敗 400"]
    assert row["afterEventCount"] == "4"
    assert row["afterEventIds"] == ["E1", "E2", "E3", "E4"]


def test_revert_failure_restores_the_button(views):
    """伺服器沒動 → 歷史沒變 → 按鈕要能再按。"""
    row = views["復原失敗 400"]
    assert row["afterRowActions"] == ["revert"]
    assert row["afterRowDisabled"] == [False]


def test_revert_failure_does_not_leak_to_the_page_error_box(views):
    """逐列的錯誤就放在那一列，不要動頁面層級的提示。"""
    assert views["復原失敗 400"]["afterPageError"] == []


def test_revert_failure_does_not_wedge_the_page(views):
    for label in ("復原失敗 400", "復原失敗 409", "復原失敗 500"):
        assert views[label]["notFoundShown"] is False, label


# ----------------------------------------------------------------------
# 6. 復原成功但重載失敗 —— 不可說成「復原失敗」
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "label", ["復原成功但重載失敗", "復原成功但歷史載入失敗"]
)
def test_reload_failure_is_not_reported_as_a_failed_revert(views, label):
    row = views[label]
    message = " ".join(row["afterPageError"])
    assert row["afterRowError"] in ("", None), "逐列的錯誤槽不該被寫"
    assert "復原失敗" not in message
    assert "復原成功" in message
    assert "重新整理" in message


@pytest.mark.parametrize(
    "label", ["復原成功但重載失敗", "復原成功但歷史載入失敗"]
)
def test_revert_is_not_repeatable_after_a_reload_failure(views, label):
    """復原已經發生了，再對同一事件按一次只會拿到 400。按鈕必須鎖住。"""
    assert views[label]["afterRowDisabled"] == [True]


@pytest.mark.parametrize(
    "label", ["復原成功但重載失敗", "復原成功但歷史載入失敗"]
)
def test_reload_failure_message_quotes_the_error(views, label):
    message = " ".join(views[label]["afterPageError"])
    assert "無法回應" in message


def test_revert_and_reload_failures_are_separate_code_paths():
    """結構上的保險：POST 與 refresh 不在同一個 try 裡。"""
    source = (Path(__file__).resolve().parents[1] / "ui" / "item.js").read_text(
        encoding="utf-8"
    )
    body = source.split("async function revert(")[1].split("\nasync function")[0]
    assert body.count("} catch (err) {") == 2
    post_at = body.index('"/api/events/"')
    first_catch = body.index("} catch (err) {")
    refresh_at = body.index("await refresh()")
    assert post_at < first_catch < refresh_at


def test_revert_error_slot_is_on_the_event_row():
    """復原失敗的訊息留在那一列；reload 失敗才用頁面層級（列可能已被換掉）。"""
    source = (Path(__file__).resolve().parents[1] / "ui" / "item.js").read_text(
        encoding="utf-8"
    )
    body = source.split("async function revert(")[1].split("\nasync function")[0]
    post_catch = body.split("} catch (err) {")[1]
    assert "slot.textContent" in post_catch, "POST 失敗要寫進該列的錯誤槽"
    reload_catch = body.split("} catch (err) {")[2]
    assert "showError(" in reload_catch, "reload 失敗要走頁面層級"


# ----------------------------------------------------------------------
# 7. 每個事件獨立操作
# ----------------------------------------------------------------------


def test_each_event_has_its_own_revert_button(views):
    rows = _rows(views, "復原按鈕只出現在可復原事件")
    revertible = [e for e, r in rows.items() if "revert" in r["actions"]]
    assert sorted(revertible) == sorted(REVERTIBLE)


def test_no_bulk_revert_anywhere():
    """不做全部復原、批次復原、undo stack、時間點快照。"""
    joined = "".join(
        (Path(__file__).resolve().parents[1] / "ui" / n).read_text(encoding="utf-8")
        for n in ("item.js", "item.html")
    )
    for forbidden in ("全部復原", "revertAll", "revert-all", "undoStack",
                      "undo_stack", "checkpoint", "restoreTo", "回到某一時間"):
        assert forbidden not in joined, f"不該出現 {forbidden}"


def test_revert_only_calls_the_single_event_endpoint(views):
    posts = [c for c in views["復原成功"]["calls"] if c.startswith("POST")]
    assert posts == ["POST /api/events/E2/revert"]


# ----------------------------------------------------------------------
# 8. A → B → 復原 → A 的完整事件鏈（真實後端）
# ----------------------------------------------------------------------


def test_revert_chain_produces_a_to_b_to_a_events(repo):
    """這是 Phase 9 真正的核心：復原本身也必須是可追溯的新事件。

    A → B → 復原 必須得到 A → B → A 三筆 field.changed，
    而不是把中間那筆改掉或刪掉。
    """
    item = repo.create_item(brand="A")

    repo.update_item(item.id, {"brand": "B"})          # A → B
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    repo.revert_event(change.id)                          # B → A

    changes = [
        (event.prev_value, event.next_value)
        for event in reversed(repo.list_events("item", item.id))
        if event.type == "field.changed"
    ]
    assert changes == [("A", "B"), ("B", "A")], "必須是 A → B → A 的完整鏈"
    assert repo.get_item(item.id).brand == "A"


def test_revert_does_not_modify_the_original_event(repo):
    """原事件的每一欄都必須一模一樣 —— 直接比對資料庫裡的原始列。"""
    item = repo.create_item(brand="A")
    repo.update_item(item.id, {"brand": "B"})
    original = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    before = _raw_event(repo, original.id)

    repo.revert_event(original.id)

    assert _raw_event(repo, original.id) == before, "原事件不能被修改"


def _raw_event(repo, event_id):
    """直接從 events 表讀原始列（含 prev_value / next_value 的 JSON 編碼）。"""
    row = repo.conn.execute(
        "SELECT * FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    return {key: row[key] for key in row.keys()}


def test_revert_event_is_recorded_as_a_new_field_changed(repo):
    item = repo.create_item(brand="A")
    repo.update_item(item.id, {"brand": "B"})
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    repo.revert_event(change.id)

    newest = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    assert newest.id != change.id
    assert (newest.prev_value, newest.next_value) == ("B", "A")
    assert newest.actor == "user"


def test_revert_chain_can_be_repeated(repo):
    """復原復原：再按一次會回到 B，四筆事件都在。"""
    item = repo.create_item(brand="A")
    repo.update_item(item.id, {"brand": "B"})
    first = next(e for e in repo.list_events("item", item.id)
                 if e.type == "field.changed")
    repo.revert_event(first.id)
    second = next(e for e in repo.list_events("item", item.id)
                  if e.type == "field.changed")
    repo.revert_event(second.id)

    assert repo.get_item(item.id).brand == "B"
    changes = [
        (e.prev_value, e.next_value)
        for e in reversed(repo.list_events("item", item.id))
        if e.type == "field.changed"
    ]
    assert changes == [("A", "B"), ("B", "A"), ("A", "B")]


def test_only_field_changed_events_are_revertible(repo):
    """後端也要擋住沒有可還原值的事件（UI 只是不顯示按鈕）。"""
    item = repo.create_item()
    created = next(e for e in repo.list_events("item", item.id)
                   if e.type == "item.created")
    from shop.errors import ValidationError

    with pytest.raises(ValidationError):
        repo.revert_event(created.id)


def test_missing_event_is_not_found(repo):
    from shop.errors import NotFoundError

    with pytest.raises(NotFoundError):
        repo.revert_event("NOPE")


def test_revert_endpoint_returns_the_updated_entity(client):
    item = client.post("/api/items", json={"brand": "A"}).json()
    client.patch(f"/api/items/{item['id']}", json={"brand": "B"})
    change = next(
        e for e in client.get(f"/api/items/{item['id']}/events").json()
        if e["type"] == "field.changed"
    )
    response = client.post(f"/api/events/{change['id']}/revert")
    assert response.status_code == 200
    assert response.json()["brand"] == "A"


def test_revert_endpoint_400s_on_creation_event(client):
    item = client.post("/api/items", json={}).json()
    created = next(
        e for e in client.get(f"/api/items/{item['id']}/events").json()
        if e["type"] == "item.created"
    )
    assert client.post(f"/api/events/{created['id']}/revert").status_code == 400


def test_revert_endpoint_404s_on_missing_event(client):
    assert client.post("/api/events/NOPE/revert").status_code == 404
