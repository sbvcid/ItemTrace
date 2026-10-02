"""identifiers：可追溯來源照片、撞號看得見而不是被擋掉。"""

from __future__ import annotations

import pytest

from shop.errors import ConflictError, NotFoundError, ValidationError
from shop.ids import normalize_identifier


@pytest.fixture()
def item(repo):
    return repo.create_item(name="主機板")


def test_add_identifier_normalizes_value(repo, item):
    identifier = repo.add_identifier(item.id, "BX-807 06_1234")
    assert identifier.value == "BX-807 06_1234"
    assert identifier.normalized == "BX807061234"
    assert identifier.kind == "serial"
    assert identifier.source == "human"
    assert identifier.source_photo_id is None


def test_identifier_records_source_photo(repo, item):
    """SPEC-v1 §2.3：序號要能追到是哪一張照片。"""
    photo = repo.add_photo(item.id, f"files/{item.id}/original/20261002-143355_IMG_4824.jpg")
    identifier = repo.add_identifier(item.id, "6LWMF1234567", source_photo_id=photo.id)
    assert identifier.source_photo_id == photo.id

    payload = repo.list_events("identifier", identifier.id)[0].payload
    assert payload["source_photo_id"] == photo.id


def test_identifier_rejects_photo_from_another_item(repo, item):
    other = repo.create_item()
    photo = repo.add_photo(other.id, f"files/{other.id}/original/a.jpg")
    with pytest.raises(ValidationError) as excinfo:
        repo.add_identifier(item.id, "6LWMF1234567", source_photo_id=photo.id)
    assert other.id in str(excinfo.value)


def test_identifier_requires_existing_item(repo):
    with pytest.raises(NotFoundError):
        repo.add_identifier("ITM-9999", "6LWMF1234567")


def test_identifier_kind_and_source_are_restricted(repo, item):
    with pytest.raises(ValidationError):
        repo.add_identifier(item.id, "X1", kind="uuid")
    with pytest.raises(ValidationError):
        repo.add_identifier(item.id, "X1", source="ocr")


def test_identifier_value_cannot_be_blank(repo, item):
    with pytest.raises(ValidationError):
        repo.add_identifier(item.id, "   ")
    with pytest.raises(ValidationError):
        repo.add_identifier(item.id, "---", kind="serial")


def test_confidence_must_be_between_zero_and_one(repo, item):
    assert repo.add_identifier(item.id, "X1", confidence=0.82).confidence == 0.82
    assert repo.add_identifier(item.id, "X2", confidence=None).confidence is None
    with pytest.raises(ValidationError):
        repo.add_identifier(item.id, "X3", confidence=1.4)


def test_duplicate_within_same_item_is_rejected(repo, item):
    repo.add_identifier(item.id, "6LWMF1234567")
    with pytest.raises(ConflictError):
        repo.add_identifier(item.id, "6LWMF1234567")


def test_same_value_other_kind_is_allowed(repo, item):
    """同一商品同一組字串但不同種類，不算重複。"""
    repo.add_identifier(item.id, "12345678", kind="serial")
    imei = repo.add_identifier(item.id, "12345678", kind="imei")
    assert imei.kind == "imei"


def test_collision_across_items_is_stored_and_reported(repo):
    """SPEC-v1 §2.3：刻意不設全域 UNIQUE，撞號要看得見讓人判斷。"""
    first = repo.create_item(name="第一件")
    second = repo.create_item(name="第二件")
    repo.add_identifier(first.id, "6LWMF1234567")

    duplicate = repo.add_identifier(second.id, "6lwmf 1234567")
    assert duplicate.id  # 寫得進去

    conflicts = repo.find_identifier_conflicts("6LWMF-1234567", exclude_item_id=second.id)
    assert [conflict.item_id for conflict in conflicts] == [first.id]


def test_find_identifier_conflicts_can_filter_kind(repo):
    first = repo.create_item()
    repo.add_identifier(first.id, "12345678", kind="serial")
    assert [row.item_id for row in repo.find_identifier_conflicts("12345678")] == [first.id]
    assert repo.find_identifier_conflicts("12345678", kind="imei") == []
    assert repo.find_identifier_conflicts("12345678", exclude_item_id=first.id) == []


def test_find_identifier_conflicts_uses_normalization(repo, item):
    repo.add_identifier(item.id, "BX-807 06_1234")
    assert repo.find_identifier_conflicts("bx807061234") != []
    assert repo.find_identifier_conflicts("807061234") == []


def test_list_identifiers_by_item(repo):
    first = repo.create_item()
    second = repo.create_item()
    repo.add_identifier(first.id, "AAA", kind="serial")
    repo.add_identifier(first.id, "BBB", kind="imei")
    repo.add_identifier(second.id, "CCC")

    assert [row.value for row in repo.list_identifiers(item_id=first.id)] == ["AAA", "BBB"]
    assert [row.value for row in repo.list_identifiers(kind="imei")] == ["BBB"]
    assert len(repo.list_identifiers()) == 3


def test_update_identifier_recomputes_normalized(repo, item):
    identifier = repo.add_identifier(item.id, "BX-807 06")
    updated = repo.update_identifier(identifier.id, {"value": "BX-80706X"})
    assert updated.normalized == "BX80706X" == normalize_identifier("BX-80706X")

    events = repo.list_events("identifier", identifier.id)
    changed = {event.field: (event.prev_value, event.next_value) for event in events
               if event.type == "field.changed"}
    assert changed["value"] == ("BX-807 06", "BX-80706X")
    assert changed["normalized"] == ("BX80706", "BX80706X")


def test_update_identifier_keeps_normalized_when_value_unchanged(repo, item):
    identifier = repo.add_identifier(item.id, "BX-807 06")
    events_before = len(repo.list_events("identifier", identifier.id))
    repo.update_identifier(identifier.id, {"value": "BX-807 06"})
    assert len(repo.list_events("identifier", identifier.id)) == events_before


def test_update_identifier_cannot_collide_within_item(repo, item):
    repo.add_identifier(item.id, "AAA")
    other = repo.add_identifier(item.id, "BBB")
    with pytest.raises(ConflictError):
        repo.update_identifier(other.id, {"value": "AAA"})


def test_update_identifier_cannot_move_to_another_photo_owner(repo, item):
    other = repo.create_item()
    photo = repo.add_photo(other.id, f"files/{other.id}/original/a.jpg")
    identifier = repo.add_identifier(item.id, "AAA")
    with pytest.raises(ValidationError):
        repo.update_identifier(identifier.id, {"source_photo_id": photo.id})


def test_update_identifier_refuses_normalized_and_id(repo, item):
    identifier = repo.add_identifier(item.id, "AAA")
    for field in ("normalized", "id", "item_id"):
        with pytest.raises(ValidationError):
            repo.update_identifier(identifier.id, {field: "X"})


def test_delete_identifier_keeps_snapshot_in_events(repo, item):
    identifier = repo.add_identifier(item.id, "6LWMF1234567")
    repo.delete_identifier(identifier.id)
    assert repo.list_identifiers(item_id=item.id) == []
    with pytest.raises(NotFoundError):
        repo.get_identifier(identifier.id)

    deleted = repo.list_events("identifier", identifier.id)[0]
    assert deleted.type == "identifier.deleted"
    assert deleted.payload["value"] == "6LWMF1234567"
    assert deleted.payload["normalized"] == "6LWMF1234567"
