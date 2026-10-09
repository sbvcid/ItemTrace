"""items 的 CRUD 與 events 連動。"""

from __future__ import annotations

import pytest

from shop.errors import NotFoundError, ValidationError
from shop.models import Item


def test_create_item_assigns_readable_id_and_defaults(repo):
    item = repo.create_item(name="主機板")
    assert item.id == "ITM-0001"
    assert item.status == "active"
    assert item.quantity == 1
    assert item.attributes == {}
    assert item.created_at and item.updated_at


def test_create_item_ids_increment(repo):
    assert repo.create_item().id == "ITM-0001"
    assert repo.create_item().id == "ITM-0002"
    assert repo.create_item().id == "ITM-0003"


def test_create_item_rejects_bad_quantity(repo):
    with pytest.raises(ValidationError):
        repo.create_item(quantity=0)
    with pytest.raises(ValidationError):
        repo.create_item(quantity="很多")


def test_create_item_writes_item_created_event(repo):
    item = repo.create_item(name="主機板", brand="ASUS")
    history = repo.list_events("item", item.id)
    assert [event.type for event in history] == ["item.created"]
    assert history[0].actor == "user"
    assert history[0].payload["brand"] == "ASUS"
    assert history[0].payload["name"] == "主機板"


def test_create_item_records_external_actor(repo):
    item = repo.create_item(name="批次匯入", actor="external")
    assert repo.list_events("item", item.id)[0].actor == "external"


def test_get_item_returns_typed_row(repo):
    item = repo.create_item(attributes={"記憶體": "64GB", "插槽": 4})
    fetched = repo.get_item(item.id)
    assert isinstance(fetched, Item)
    assert fetched.attributes == {"記憶體": "64GB", "插槽": 4}


def test_get_missing_item_raises(repo):
    with pytest.raises(NotFoundError) as excinfo:
        repo.get_item("ITM-9999")
    assert "ITM-9999" in str(excinfo.value)


def test_attributes_must_stay_json_object(repo):
    """壞掉的 attributes 要吵出來，不能被靜默吞成空物件。"""
    item = repo.create_item()
    repo.conn.execute("UPDATE items SET attributes = 'not json' WHERE id = ?", (item.id,))
    with pytest.raises(ValidationError):
        repo.get_item(item.id)


def test_list_items_filters_and_paginates(repo):
    for index in range(5):
        repo.create_item(name=f"item{index}", category="主機板" if index < 2 else "顯卡")
    assert len(repo.list_items()) == 5
    assert len(repo.list_items(category="主機板")) == 2
    assert len(repo.list_items(status="active")) == 5
    assert len(repo.list_items(status="void")) == 0
    # 預設由新到舊：created_at DESC，同一秒以 id DESC 決勝。
    assert [item.id for item in repo.list_items(limit=2)] == ["ITM-0005", "ITM-0004"]
    assert [item.id for item in repo.list_items(limit=2, offset=2)] == [
        "ITM-0003",
        "ITM-0002",
    ]


def test_list_items_sorts_by_created_at_desc(repo):
    """排序看 created_at 而不是 id：時間戳被更正過的資料依真實建立時間排。"""
    older_id = repo.create_item(name="較早建立").id
    newer_id = repo.create_item(name="較晚建立").id
    repo.conn.execute(
        "UPDATE items SET created_at = '2099-01-01T00:00:00' WHERE id = ?",
        (older_id,),
    )
    assert [item.id for item in repo.list_items()] == [older_id, newer_id]


def test_update_item_does_not_change_list_order(repo):
    """修改舊紀錄只動 updated_at，不會讓它跳到清單最前面。"""
    first = repo.create_item(name="第一件")
    second = repo.create_item(name="第二件")
    assert [item.id for item in repo.list_items()] == [second.id, first.id]

    repo.update_item(first.id, {"name": "第一件（改名）"})
    assert [item.id for item in repo.list_items()] == [second.id, first.id]


def test_list_items_rejects_bad_paging(repo):
    with pytest.raises(ValidationError):
        repo.list_items(limit=0)
    with pytest.raises(ValidationError):
        repo.list_items(offset=-1)


def test_update_item_writes_one_event_per_field(repo):
    item = repo.create_item(name="主機板", brand="ASUS", model="ROG STRIX B650E-F")
    updated = repo.update_item(item.id, {"brand": "acer", "condition": "正常使用"})

    assert updated.brand == "acer"
    assert updated.condition == "正常使用"
    assert updated.updated_at >= item.updated_at

    history = repo.list_events("item", item.id)
    changes = [event for event in history if event.type == "field.changed"]
    assert {event.field for event in changes} == {"brand", "condition"}
    by_field = {event.field: event for event in changes}
    assert by_field["brand"].prev_value == "ASUS"
    assert by_field["brand"].next_value == "acer"
    assert by_field["condition"].prev_value == ""


def test_update_item_with_same_value_records_nothing(repo):
    item = repo.create_item(brand="ASUS")
    result = repo.update_item(item.id, {"brand": "ASUS"})
    assert result.updated_at == item.updated_at
    assert len(repo.list_events("item", item.id)) == 1


def test_update_item_empty_patch_is_a_noop(repo):
    item = repo.create_item()
    assert repo.update_item(item.id, {}) == item


def test_update_item_refuses_identity_fields(repo):
    """id 與時間戳由系統維護，不能從外面改。"""
    item = repo.create_item()
    for field in ("id", "created_at", "updated_at", "item_id"):
        with pytest.raises(ValidationError) as excinfo:
            repo.update_item(item.id, {field: "x"})
        assert field in str(excinfo.value)


def test_update_item_coerces_types_from_json_input(repo):
    item = repo.create_item()
    updated = repo.update_item(item.id, {"quantity": "3"})
    assert updated.quantity == 3
    assert isinstance(updated.quantity, int)


def test_update_item_rejects_invalid_status(repo):
    item = repo.create_item()
    with pytest.raises(ValidationError) as excinfo:
        repo.update_item(item.id, {"status": "draft"})
    assert "draft" in str(excinfo.value)


def test_failed_update_leaves_no_trace(repo):
    item = repo.create_item()
    with pytest.raises(ValidationError):
        repo.update_item(item.id, {"quantity": 0, "brand": "acer"})
    assert repo.get_item(item.id).brand == ""
    assert len(repo.list_events("item", item.id)) == 1


def test_void_item_is_soft_delete(repo):
    item = repo.create_item(name="主機板")
    voided = repo.void_item(item.id)
    assert voided.status == "void"
    # 資料還在，只是換了狀態
    assert repo.get_item(item.id).name == "主機板"
    assert [event.field for event in repo.list_events("item", item.id)] == [
        "status",
        None,
    ]


def test_void_item_keeps_observations_and_photos(repo):
    item = repo.create_item()
    observation = repo.add_observation(item.id)
    repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", observation_id=observation.id)
    repo.void_item(item.id)
    assert len(repo.list_observations(item.id)) == 1
    assert len(repo.list_photos(item_id=item.id)) == 1


def test_void_item_twice_records_once(repo):
    item = repo.create_item()
    repo.void_item(item.id)
    repo.void_item(item.id)
    assert len(repo.list_events("item", item.id)) == 2


def test_voided_item_id_is_never_reused(repo):
    voided = repo.create_item()
    repo.void_item(voided.id)
    assert repo.create_item().id == "ITM-0002"
