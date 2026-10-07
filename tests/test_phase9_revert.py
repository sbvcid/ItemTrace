"""Phase 9：事件復原後端契約與 Repository 測試。

資料語意：
A → B → 復原 → A 的完整事件鏈、原事件不變由後端負責。
復原本身必須變成一筆可追溯的新事件，而不是把舊事件改掉。
"""

from __future__ import annotations

import pytest


def _raw_event(repo, event_id):
    """直接從 events 表讀原始列（含 prev_value / next_value 的 JSON 編碼）。"""
    row = repo.conn.execute(
        "SELECT * FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    return {key: row[key] for key in row.keys()}


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
