"""events 查詢與單欄位復原（SPEC-v1 §4.3）。"""

from __future__ import annotations

import pytest

from shop.errors import NotFoundError, ValidationError


def test_item_history_spans_item_and_children(repo):
    item = repo.create_item(name="主機板")
    observation = repo.add_observation(item.id)
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", observation_id=observation.id)
    identifier = repo.add_identifier(item.id, "6LWMF1234567", source_photo_id=photo.id)
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    repo.update_item(item.id, {"brand": "acer"})

    history = repo.item_history(item.id)
    types = [event.type for event in history]
    assert types.count("item.created") == 1
    assert "observation.created" in types
    assert "photo.created" in types
    assert "identifier.created" in types
    assert "suggestion.created" in types
    assert "suggestion.accepted" in types
    assert types.count("field.changed") == 2  # accept 寫入的 brand 與後來的 acer

    # 最新在前
    assert history[0].created_at >= history[-1].created_at
    assert {event.entity_id for event in history} == {
        item.id,
        observation.id,
        photo.id,
        identifier.id,
        suggestion.id,
    }


def test_item_history_excludes_other_items(repo):
    first = repo.create_item()
    second = repo.create_item()
    repo.add_observation(second.id)
    assert {event.entity_id for event in repo.item_history(first.id)} == {first.id}


def test_item_history_requires_existing_item(repo):
    with pytest.raises(NotFoundError):
        repo.item_history("ITM-9999")


def test_revert_restores_previous_value(repo):
    item = repo.create_item(brand="ASUS")
    repo.update_item(item.id, {"brand": "acer", "model": "B650E-F"})

    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed" and event.field == "brand"
    )
    reverted = repo.revert_event(change.id)

    assert reverted.brand == "ASUS"
    assert repo.get_item(item.id).brand == "ASUS"
    # 其他欄位不受影響
    assert repo.get_item(item.id).model == "B650E-F"


def test_revert_records_itself_so_history_stays_true(repo):
    item = repo.create_item(brand="ASUS")
    repo.update_item(item.id, {"brand": "acer"})
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    repo.revert_event(change.id)

    changes = [
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    ]
    assert len(changes) == 2
    assert [event.next_value for event in changes] == ["ASUS", "acer"]
    assert all(event.actor == "user" for event in changes)


def test_revert_is_idempotent(repo):
    """同一筆事件還原兩次結果相同 —— 「回到該事件之前的值」是明確的定義，
    不是來回切換，否則歷史會被無意義的反覆改寫淹沒。"""
    item = repo.create_item(brand="ASUS")
    repo.update_item(item.id, {"brand": "acer"})
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    repo.revert_event(change.id)
    repo.revert_event(change.id)
    assert repo.get_item(item.id).brand == "ASUS"


def test_revert_identifier_value(repo):
    item = repo.create_item()
    identifier = repo.add_identifier(item.id, "BX-807 06")
    repo.update_identifier(identifier.id, {"value": "BX-80706X"})

    change = next(
        event for event in repo.list_events("identifier", identifier.id)
        if event.type == "field.changed" and event.field == "value"
    )
    reverted = repo.revert_event(change.id)
    assert reverted.value == "BX-807 06"
    assert reverted.normalized == "BX80706"


def test_revert_observation_note(repo):
    item = repo.create_item()
    observation = repo.add_observation(item.id, note="初稿")
    repo.update_observation(observation.id, {"note": "補拍"})
    change = next(
        event for event in repo.list_events("observation", observation.id)
        if event.type == "field.changed"
    )
    assert repo.revert_event(change.id).note == "初稿"


def test_revert_photo_angle(repo):
    item = repo.create_item()
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    repo.update_photo(photo.id, {"angle": "label"})
    change = next(
        event for event in repo.list_events("photo", photo.id)
        if event.type == "field.changed"
    )
    assert repo.revert_event(change.id).angle == ""


def test_revert_item_attributes(repo):
    item = repo.create_item(attributes={"記憶體": "32GB"})
    repo.update_item(item.id, {"attributes": {"記憶體": "64GB"}})
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    assert repo.revert_event(change.id).attributes == {"記憶體": "32GB"}


def test_revert_rejects_creation_events(repo):
    item = repo.create_item()
    created = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "item.created"
    )
    with pytest.raises(ValidationError):
        repo.revert_event(created.id)


def test_revert_missing_event_raises(repo):
    with pytest.raises(NotFoundError):
        repo.revert_event("NOPE")


def test_revert_unknown_entity_type(repo):
    item = repo.create_item()
    repo.update_item(item.id, {"brand": "ASUS"})
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed"
    )
    repo.conn.execute(
        "UPDATE events SET entity_type = 'invoice' WHERE id = ?", (change.id,)
    )
    with pytest.raises(ValidationError):
        repo.revert_event(change.id)
