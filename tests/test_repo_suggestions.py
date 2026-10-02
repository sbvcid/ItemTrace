"""suggestions：推論與事實分離，接受後才進主表。"""

from __future__ import annotations

import pytest

from shop.errors import ConflictError, NotFoundError, ValidationError


@pytest.fixture()
def item(repo):
    return repo.create_item(name="主機板")


def test_add_suggestion_does_not_touch_main_table(repo, item):
    suggestion = repo.add_suggestion(
        item.id, "brand", "ASUS", confidence=0.82, model_name="claude-opus-4"
    )
    assert suggestion.status == "pending"
    assert suggestion.source == "external"
    assert suggestion.decided_at is None
    # 主表完全沒被動到
    assert repo.get_item(item.id).brand == ""


def test_suggestion_keeps_source_photo(repo, item):
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    suggestion = repo.add_suggestion(item.id, "model", "B650E-F", source_photo_id=photo.id)
    assert suggestion.source_photo_id == photo.id


def test_suggestion_field_is_restricted(repo, item):
    for field in ("price", "identifier:uuid", "notes"):
        with pytest.raises(ValidationError):
            repo.add_suggestion(item.id, field, "x")


def test_suggestion_requires_existing_item(repo):
    with pytest.raises(NotFoundError):
        repo.add_suggestion("ITM-9999", "brand", "ASUS")


def test_accept_writes_value_into_item(repo, item):
    repo.add_suggestion(item.id, "brand", "ASUS", confidence=0.9)
    accepted = repo.accept_suggestion(repo.list_suggestions(item_id=item.id)[0].id)

    assert accepted.status == "accepted"
    assert accepted.decided_at is not None
    assert repo.get_item(item.id).brand == "ASUS"


def test_accepting_field_suggestion_writes_item_event(repo, item):
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed" and event.field == "brand"
    )
    assert (change.prev_value, change.next_value) == ("", "ASUS")


def test_accept_identifier_suggestion_creates_identifier(repo, item):
    """SPEC-v1 §5：identifier 類建議接受後另建 identifiers。"""
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    suggestion = repo.add_suggestion(
        item.id, "identifier:serial", "6LWMF1234567", confidence=0.77, source_photo_id=photo.id
    )
    repo.accept_suggestion(suggestion.id)

    identifiers = repo.list_identifiers(item_id=item.id)
    assert len(identifiers) == 1
    assert identifiers[0].value == "6LWMF1234567"
    assert identifiers[0].kind == "serial"
    assert identifiers[0].source == "accepted_suggestion"
    assert identifiers[0].confidence == 0.77
    assert identifiers[0].source_photo_id == photo.id
    # 推論沒有變成主表欄位
    assert repo.get_item(item.id).name == "主機板"


def test_accept_records_suggestion_event(repo, item):
    suggestion = repo.add_suggestion(item.id, "condition", "正常使用")
    repo.accept_suggestion(suggestion.id)
    event = repo.list_events("suggestion", suggestion.id)[0]
    assert event.type == "suggestion.accepted"
    assert event.next_value == "正常使用"
    assert event.payload["created_identifier"] is False


def test_accepting_identifier_suggestion_flags_payload(repo, item):
    # 測試用的假 IMEI。不要放任何真實的識別碼進公開 repo。
    suggestion = repo.add_suggestion(item.id, "identifier:imei", "123456789012345")
    repo.accept_suggestion(suggestion.id)
    event = repo.list_events("suggestion", suggestion.id)[0]
    assert event.payload["created_identifier"] is True
    assert repo.list_identifiers(item_id=item.id)[0].kind == "imei"


def test_accept_twice_is_refused(repo, item):
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    with pytest.raises(ValidationError) as excinfo:
        repo.accept_suggestion(suggestion.id)
    assert "accepted" in str(excinfo.value)


def test_reject_keeps_the_suggestion(repo, item):
    """被拒的建議也要留著（SPEC-v1 §1）。"""
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS", confidence=0.3)
    rejected = repo.reject_suggestion(suggestion.id)

    assert rejected.status == "rejected"
    assert rejected.decided_at is not None
    assert repo.get_item(item.id).brand == ""
    assert repo.list_suggestions(item_id=item.id, status="rejected")[0].id == suggestion.id


def test_reject_after_accept_is_refused(repo, item):
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    with pytest.raises(ValidationError):
        repo.reject_suggestion(suggestion.id)


def test_update_suggestion_only_while_pending(repo, item):
    suggestion = repo.add_suggestion(item.id, "brand", "ASUS", confidence=0.2)
    updated = repo.update_suggestion(suggestion.id, {"confidence": 0.6})
    assert updated.confidence == 0.6

    repo.accept_suggestion(suggestion.id)
    with pytest.raises(ValidationError):
        repo.update_suggestion(suggestion.id, {"value": "acer"})


def test_list_suggestions_filters(repo):
    first = repo.create_item()
    second = repo.create_item()
    repo.add_suggestion(first.id, "brand", "ASUS")
    repo.add_suggestion(second.id, "model", "B650E-F")
    repo.reject_suggestion(repo.list_suggestions(item_id=second.id)[0].id)

    assert len(repo.list_suggestions(status="pending")) == 1
    assert len(repo.list_suggestions(status="rejected")) == 1
    assert len(repo.list_suggestions()) == 2


def test_same_value_on_two_items_is_allowed_by_design(repo):
    """SPEC-v1 §2.3：刻意沒有全域 UNIQUE，撞號要看得見讓人判斷，
    而不是讓寫入直接失敗。"""
    first = repo.create_item()
    second = repo.create_item()
    repo.add_identifier(first.id, "6LWMF1234567")
    duplicate = repo.add_identifier(second.id, "6LWMF1234567")
    assert duplicate.item_id == second.id
    assert repo.find_identifier_conflicts("6LWMF1234567") != []


def test_failing_accept_rolls_back_suggestion_state(repo):
    """接受失敗時，suggestions 的狀態也不能變 —— 資料與事件同生共死，
    而且不能連帶影響先前已成功的接受。"""
    item = repo.create_item()
    first = repo.add_suggestion(item.id, "identifier:serial", "6LWMF1234567")
    second = repo.add_suggestion(item.id, "identifier:serial", "6LWMF1234567")
    repo.accept_suggestion(first.id)

    with pytest.raises(ConflictError):
        repo.accept_suggestion(second.id)

    assert repo.get_suggestion(first.id).status == "accepted"
    assert repo.get_suggestion(second.id).status == "pending"
    assert repo.get_suggestion(second.id).decided_at is None
    assert len(repo.list_identifiers(item_id=item.id)) == 1
    assert [event.type for event in repo.list_events("suggestion", second.id)] == [
        "suggestion.created"
    ]
