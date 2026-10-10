"""items 的 CRUD 與 events 連動。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shop.errors import NotFoundError, PurgeError, ValidationError
from shop.models import Item
from tests.conftest import make_jpeg


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


# ----------------------------------------------------------------------
# Phase 3：垃圾桶（void 預設排除、還原、永久刪除）
# ----------------------------------------------------------------------


def _archive_photo(repo, config, item_id, observation_id, name="a.jpg"):
    """在 files/<item-id>/original/ 放一張真實檔案並登記為 photos 列。"""
    directory = config.files_dir / item_id / "original"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(make_jpeg())
    return repo.add_photo(
        item_id, config.relative(path), observation_id=observation_id
    )


def _stocked_for_purge(repo, config):
    """一件事實齊全的紀錄：觀測、真實照片、識別碼、建議、事件。"""
    item = repo.create_item(name="待永久刪除", brand="ACME")
    observation = repo.add_observation(item.id, note="第一次看到")
    photo = _archive_photo(repo, config, item.id, observation.id)
    repo.add_identifier(item.id, "SN-777", source_photo_id=photo.id)
    repo.add_suggestion(item.id, "model", "X-100")
    return item, observation, photo


def test_list_items_excludes_void_by_default(repo):
    """首頁與一般搜尋不顯示垃圾桶紀錄；archived 仍留在預設檢視。"""
    first = repo.create_item(name="還在使用")
    second = repo.create_item(name="不要了")
    third = repo.create_item(name="已離手")
    repo.void_item(second.id)
    repo.update_item(third.id, {"status": "archived"})

    assert [item.id for item in repo.list_items()] == [third.id, first.id]
    assert [item.id for item in repo.list_items(status="void")] == [second.id]
    assert repo.list_items(q="不要了") == []
    assert [
        item.id for item in repo.list_items(q="不要了", status="void")
    ] == [second.id]


def test_restore_item_returns_previous_active_status(repo):
    item = repo.create_item(name="主機板")
    repo.void_item(item.id)
    restored = repo.restore_item(item.id)
    assert restored.status == "active"
    assert [row.id for row in repo.list_items()] == [item.id]


def test_restore_item_returns_previous_archived_status(repo):
    """原本是 archived 的紀錄，還原後回到 archived 而不是 active。"""
    item = repo.create_item(name="已離手的老相機")
    repo.update_item(item.id, {"status": "archived"})
    repo.void_item(item.id)
    assert repo.restore_item(item.id).status == "archived"


def test_restore_item_after_repeated_trash_cycles(repo):
    """反覆「移入 → 還原」後，看的永遠是最近一次的移入前狀態。"""
    item = repo.create_item(name="循環")
    repo.update_item(item.id, {"status": "archived"})
    repo.void_item(item.id)
    repo.restore_item(item.id)  # → archived
    repo.update_item(item.id, {"status": "active"})
    repo.void_item(item.id)
    assert repo.restore_item(item.id).status == "active"


def test_restore_item_rejects_item_not_in_trash(repo):
    item = repo.create_item()
    with pytest.raises(ValidationError):
        repo.restore_item(item.id)


def test_restore_item_defaults_to_active_without_reliable_history(repo):
    """歷史不可靠（例如資料被外部直接改成 void）→ 明確的安全預設 active。"""
    item = repo.create_item()
    repo.conn.execute("UPDATE items SET status = 'void' WHERE id = ?", (item.id,))
    assert repo.restore_item(item.id).status == "active"


def test_restore_item_records_event(repo):
    item = repo.create_item()
    repo.void_item(item.id)
    repo.restore_item(item.id)
    changes = [
        event
        for event in repo.list_events("item", item.id)
        if event.type == "field.changed" and event.field == "status"
    ]
    assert [(e.prev_value, e.next_value) for e in changes] == [
        ("void", "active"),
        ("active", "void"),
    ]


def test_purge_item_removes_everything_and_files(repo, config):
    """永久刪除：四張子表、事件歷史、照片檔案與目錄一次清空。"""
    item, _, _ = _stocked_for_purge(repo, config)
    directory = config.files_dir / item.id
    assert directory.exists()
    repo.void_item(item.id)

    report = repo.purge_item(item.id)

    assert report["item_id"] == item.id
    assert report["observations_deleted"] == 1
    assert report["photos_deleted"] == 1
    assert report["identifiers_deleted"] == 1
    assert report["suggestions_deleted"] == 1
    assert report["events_deleted"] >= 6  # item/obs/photo/identifier/suggestion 建立與狀態事件
    assert report["files_deleted"] == 1
    assert not directory.exists()

    with pytest.raises(NotFoundError):
        repo.get_item(item.id)
    counts = repo.counts()
    assert counts == {
        "items": 0,
        "observations": 0,
        "photos": 0,
        "identifiers": 0,
        "suggestions": 0,
        "events": 0,
    }
    # 暫存區不留檔案（成功清理的目錄會被移除，只剩 .purge 空殼）
    staging = config.data_root / ".purge"
    leftovers = list(staging.rglob("*")) if staging.exists() else []
    assert leftovers == []


def test_purge_item_requires_trash(repo):
    item = repo.create_item()
    with pytest.raises(ValidationError):
        repo.purge_item(item.id)
    assert repo.get_item(item.id).status == "active"


def test_purge_missing_item_raises_not_found(repo):
    with pytest.raises(NotFoundError):
        repo.purge_item("ITM-9999")


def test_purge_refuses_photo_outside_item_directory(repo, config):
    """照片路徑不在 files/<item-id>/ 底下時拒絕刪除，保護範圍外的檔案。"""
    item = repo.create_item()
    other_dir = config.files_dir / "OTHER" / "original"
    other_dir.mkdir(parents=True)
    stray = other_dir / "x.jpg"
    stray.write_bytes(make_jpeg())
    repo.add_photo(item.id, config.relative(stray))
    repo.void_item(item.id)
    with pytest.raises(ValidationError):
        repo.purge_item(item.id)
    assert stray.exists()


def test_purge_locked_files_abort_without_touching_database(
    repo, config, monkeypatch
):
    """檔案目錄被鎖住：明確失敗、資料庫完全未動、紀錄留在垃圾桶。"""
    item, _, photo = _stocked_for_purge(repo, config)
    repo.void_item(item.id)
    before_events = repo.counts()["events"]

    def boom(self, target):
        raise OSError("locked for test")

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(PurgeError) as excinfo:
        repo.purge_item(item.id)
    assert "紀錄尚未刪除" in str(excinfo.value)

    assert repo.get_item(item.id).status == "void"  # 還在垃圾桶
    assert config.resolve(photo.filename).exists()  # 檔案原地不動
    assert repo.counts()["photos"] == 1
    assert repo.counts()["events"] == before_events  # 零副作用


def test_purge_file_removal_failure_is_reported_not_hidden(
    repo, config, monkeypatch
):
    """交易提交後檔案仍刪不掉：PurgeError 要列出殘留路徑、不假裝完整刪除。"""
    from shop import repo as repo_mod

    item, _, _ = _stocked_for_purge(repo, config)
    repo.void_item(item.id)

    def failing_remove(root):
        return 0, [f"{root}/original/a.jpg"]

    monkeypatch.setattr(repo_mod, "_remove_tree", failing_remove)
    with pytest.raises(PurgeError) as excinfo:
        repo.purge_item(item.id)
    message = str(excinfo.value)
    assert "已從資料庫永久刪除" in message
    assert "a.jpg" in message

    # 資料庫已刪（訊息也如實說明）；磁碟殘留是「已知、被回報」的。
    with pytest.raises(NotFoundError):
        repo.get_item(item.id)
    staging = config.data_root / ".purge"
    assert [p for p in staging.iterdir() if p.is_dir()]

