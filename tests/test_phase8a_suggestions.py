"""Phase 8A：Suggestions 語義驗收。

API 在階段 4 就存在了，這裡不是重做 API，而是把整條語義釘死：

    建立 suggestion → status=pending
                    → 主表完全不變
                    → reject → 主表完全不變，且事件留痕
                    → accept → 主表才變，且事件留痕

核心不變量是「推論與事實分離」（SPEC-v1 §1）：AI / 外部 Vision 只能寫
suggestions，items / identifiers 要有人按下 accept 才會動。

逐欄位驗收：brand / model / category / condition / notes / identifier，
以及 source_photo_id 從建立到接受一路保真。
"""

from __future__ import annotations

import pytest

#: 可以被 AI 建議、直接寫入 items 的欄位（SPEC-v1 §2.2 field 註解）
FIELD_TARGETS = ["name", "brand", "model", "category", "condition", "notes"]

#: 不該被 AI 決定的欄位：數量是事實，不是判斷
NOT_SUGGESTABLE = ["quantity", "status", "id", "created_at", "attributes"]


@pytest.fixture()
def item(repo):
    """一件有照片的商品，供 source_photo_id 驗收用。"""
    created = repo.create_item(name="待建檔", category="顯示卡")
    observation = repo.add_observation(created.id, kind="intake")
    photo = repo.add_photo(
        created.id,
        f"files/{created.id}/original/20261002-143355_IMG_4824.jpg",
        orig_name="IMG_4824.jpg",
        sha256="b" * 64,
        bytes=4096,
        observation_id=observation.id,
    )
    return {"item": created, "photo": photo, "observation": observation}


def snapshot(repo, item_id):
    """把主表相關的狀態一次拍下來，之後逐項比對。"""
    row = repo.get_item(item_id)
    return {
        "item": (row.name, row.brand, row.model, row.category,
                 row.condition, row.notes, row.quantity, row.status),
        "identifiers": [
            (i.kind, i.value, i.source, i.source_photo_id)
            for i in repo.list_identifiers(item_id=item_id)
        ],
    }


# ----------------------------------------------------------------------
# 1. 建立 → pending，主表完全不變
# ----------------------------------------------------------------------


def test_creating_a_suggestion_leaves_the_item_untouched(repo, item):
    before = snapshot(repo, item["item"].id)
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS", confidence=0.94)

    assert suggestion.status == "pending"
    assert suggestion.decided_at is None
    assert snapshot(repo, item["item"].id) == before
    assert repo.get_item(item["item"].id).brand == ""


def test_creating_a_suggestion_writes_no_field_changed_event(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")

    # suggestion.created 記在 suggestion 這個 entity 上，不在 item 上
    item_events = repo.list_events("item", item["item"].id)
    assert not [e for e in item_events if e.type == "field.changed"]

    created = repo.list_events("suggestion", suggestion.id)
    assert [e.type for e in created] == ["suggestion.created"]
    assert created[0].payload["value"] == "ASUS"
    assert created[0].actor == "external"


def test_creating_a_suggestion_creates_no_identifier(repo, item):
    repo.add_suggestion(item["item"].id, "identifier:serial", "BX-807 06_1234")
    assert repo.list_identifiers(item_id=item["item"].id) == []


# ----------------------------------------------------------------------
# 2. 逐欄位：accept 才寫入主表
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_accept_writes_exactly_that_field(repo, item, field):
    """接受一個欄位建議 → 只有那個欄位變動，其他欄位不動。"""
    item_id = item["item"].id
    suggestion = repo.add_suggestion(
        item_id, field, f"{field}-的值", confidence=0.9,
        source_photo_id=item["photo"].id,
    )

    before = snapshot(repo, item_id)
    repo.accept_suggestion(suggestion.id)
    after = snapshot(repo, item_id)

    changed = [
        index for index, (old, new) in enumerate(zip(before["item"], after["item"]))
        if old != new
    ]
    # name/brand/model/category/condition/notes 在 items 裡的欄位順序
    column_index = {
        "name": 0, "brand": 1, "model": 2, "category": 3,
        "condition": 4, "notes": 5,
    }
    assert changed == [column_index[field]], f"只有 {field} 該變動"


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_reject_leaves_the_item_untouched(repo, item, field):
    item_id = item["item"].id
    suggestion = repo.add_suggestion(item_id, field, f"{field}-的值")
    before = snapshot(repo, item_id)

    rejected = repo.reject_suggestion(suggestion.id)

    assert rejected.status == "rejected"
    assert snapshot(repo, item_id) == before


@pytest.mark.parametrize("field", NOT_SUGGESTABLE)
def test_facts_are_not_suggestable(repo, item, field):
    """quantity / status / id 這類是事實，AI 不該有權建議。"""
    with pytest.raises(Exception) as excinfo:
        repo.add_suggestion(item["item"].id, field, "whatever")
    assert field in str(excinfo.value)


# ----------------------------------------------------------------------
# 3. identifier 類建議：接受後另建 identifiers，不寫 items
# ----------------------------------------------------------------------


def test_accept_identifier_creates_an_identifier_not_an_item_field(repo, item):
    item_id = item["item"].id
    suggestion = repo.add_suggestion(
        item_id, "identifier:serial", "BX-807 06_1234", confidence=0.77,
        source="external", model_name="vision-x",
        source_photo_id=item["photo"].id,
    )

    before = snapshot(repo, item_id)
    repo.accept_suggestion(suggestion.id)
    after = snapshot(repo, item_id)

    # items 完全沒變
    assert before["item"] == after["item"]
    # identifiers 多了一筆
    assert len(after["identifiers"]) == len(before["identifiers"]) + 1
    identifier = repo.list_identifiers(item_id=item_id)[0]
    assert identifier.value == "BX-807 06_1234"
    assert identifier.normalized == "BX807061234"
    assert identifier.kind == "serial"


@pytest.mark.parametrize("kind", ["serial", "imei", "barcode", "custom"])
def test_identifier_suggestion_keeps_its_kind(repo, item, kind):
    suggestion = repo.add_suggestion(
        item["item"].id, f"identifier:{kind}", "VALUE-123",
    )
    repo.accept_suggestion(suggestion.id)
    assert repo.list_identifiers(item_id=item["item"].id)[0].kind == kind


def test_unknown_identifier_kind_is_refused(repo, item):
    with pytest.raises(Exception) as excinfo:
        repo.add_suggestion(item["item"].id, "identifier:uuid", "X")
    assert "uuid" in str(excinfo.value)


# ----------------------------------------------------------------------
# 4. source_photo_id 保真
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_source_photo_survives_creation_and_acceptance(repo, item, field):
    item_id = item["item"].id
    suggestion = repo.add_suggestion(
        item_id, field, "值", confidence=0.8, source_photo_id=item["photo"].id
    )
    assert suggestion.source_photo_id == item["photo"].id

    accepted = repo.accept_suggestion(suggestion.id)
    assert accepted.source_photo_id == item["photo"].id


def test_accepted_identifier_records_the_source_photo(repo, item):
    """序號旁要能追到是哪一張照片看出来的 —— 這是 §1「一切有來源」。"""
    item_id = item["item"].id
    suggestion = repo.add_suggestion(
        item_id, "identifier:serial", "6LWMF1234567", confidence=0.77,
        source="external", model_name="vision-x",
        source_photo_id=item["photo"].id,
    )
    repo.accept_suggestion(suggestion.id)

    identifier = repo.list_identifiers(item_id=item_id)[0]
    assert identifier.source_photo_id == item["photo"].id
    # 認得這個來源照片確實屬於這件商品
    assert repo.get_photo(identifier.source_photo_id).item_id == item_id


def test_source_photo_from_another_item_is_refused(repo, item):
    other = repo.create_item()
    other_photo = repo.add_photo(other.id, f"files/{other.id}/original/x.jpg")
    with pytest.raises(Exception) as excinfo:
        repo.add_suggestion(
            item["item"].id, "brand", "ASUS", source_photo_id=other_photo.id
        )
    assert other.id in str(excinfo.value)


def test_suggestion_without_source_photo_is_allowed(repo, item):
    """沒有來源照片是允許的 —— 只是少了可追溯性。"""
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    assert suggestion.source_photo_id is None
    repo.accept_suggestion(suggestion.id)
    assert repo.get_item(item["item"].id).brand == "ASUS"


# ----------------------------------------------------------------------
# 5. accept / reject 都留痕
# ----------------------------------------------------------------------


def test_accept_records_field_changed_with_before_and_after(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)

    change = next(
        e for e in repo.list_events("item", item["item"].id)
        if e.type == "field.changed" and e.field == "brand"
    )
    assert (change.prev_value, change.next_value) == ("", "ASUS")
    assert change.actor == "user"


def test_accept_records_the_suggestion_decision(repo, item):
    suggestion = repo.add_suggestion(
        item["item"].id, "brand", "ASUS", confidence=0.94, model_name="vision-x"
    )
    repo.accept_suggestion(suggestion.id)

    event = repo.list_events("suggestion", suggestion.id)[0]
    assert event.type == "suggestion.accepted"
    assert event.actor == "user"
    assert event.field == "brand"
    # suggestion.accepted 記的是「這筆建議本來是什麼」——接受不改建議的值，
    # 所以 prev == next。商品欄位原本的值在旁邊那筆 field.changed 裡。
    assert (event.prev_value, event.next_value) == ("ASUS", "ASUS")
    assert event.payload["confidence"] == 0.94
    assert event.payload["model_name"] == "vision-x"


def test_item_previous_value_lives_in_the_field_changed_event(repo, item):
    """要回答「這欄位原本是什麼」得看 field.changed，不是 suggestion.accepted。"""
    repo.update_item(item["item"].id, {"brand": "舊的"})
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)

    change = next(
        e for e in repo.list_events("item", item["item"].id)
        if e.type == "field.changed" and e.field == "brand"
    )
    assert (change.prev_value, change.next_value) == ("舊的", "ASUS")


def test_reject_records_the_suggestion_decision(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.reject_suggestion(suggestion.id)

    event = repo.list_events("suggestion", suggestion.id)[0]
    assert event.type == "suggestion.rejected"
    assert event.next_value == "ASUS"
    assert event.actor == "user"


def test_reject_records_no_field_changed(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.reject_suggestion(suggestion.id)
    events = repo.list_events("item", item["item"].id)
    assert not [e for e in events if e.type == "field.changed"]


def test_rejected_suggestion_is_kept_forever(repo, item):
    """推論與事實分離：拒絕的建議也要留著（§1）。"""
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.reject_suggestion(suggestion.id)

    stored = repo.get_suggestion(suggestion.id)
    assert stored.status == "rejected"
    assert stored.value == "ASUS"
    assert stored.decided_at is not None
    assert [s.id for s in repo.list_suggestions(item_id=item["item"].id)] == [
        suggestion.id
    ]


def test_accepting_identifier_records_identifier_created(repo, item):
    suggestion = repo.add_suggestion(
        item["item"].id, "identifier:serial", "BX807061234")
    repo.accept_suggestion(suggestion.id)

    identifiers = repo.list_identifiers(item_id=item["item"].id)
    created = repo.list_events("identifier", identifiers[0].id)
    assert created[0].type == "identifier.created"
    assert created[0].payload["value"] == "BX807061234"


# ----------------------------------------------------------------------
# 6. 決定之後不可逆
# ----------------------------------------------------------------------


def test_accepted_suggestion_cannot_be_accepted_again(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    with pytest.raises(Exception) as excinfo:
        repo.accept_suggestion(suggestion.id)
    assert "accepted" in str(excinfo.value)


def test_accepted_suggestion_cannot_be_rejected_afterwards(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.accept_suggestion(suggestion.id)
    with pytest.raises(Exception):
        repo.reject_suggestion(suggestion.id)


def test_rejected_suggestion_cannot_be_accepted_afterwards(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.reject_suggestion(suggestion.id)
    with pytest.raises(Exception):
        repo.accept_suggestion(suggestion.id)


def test_decided_suggestion_cannot_be_edited(repo, item):
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS")
    repo.reject_suggestion(suggestion.id)
    with pytest.raises(Exception):
        repo.update_suggestion(suggestion.id, {"value": "改成別的"})
    assert repo.get_suggestion(suggestion.id).value == "ASUS"


def test_pending_suggestion_can_be_edited(repo, item):
    """決定之前還能修正 —— 那是人，不是 AI。"""
    suggestion = repo.add_suggestion(item["item"].id, "brand", "ASUS", confidence=0.3)
    updated = repo.update_suggestion(
        suggestion.id, {"value": "acer", "confidence": 0.8})
    assert (updated.value, updated.confidence) == ("acer", 0.8)
    assert updated.status == "pending"


# ----------------------------------------------------------------------
# 7. 完整的外部 AI 提交 → 人工確認 → 事件鏈
# ----------------------------------------------------------------------


def test_external_producer_to_human_accept_end_to_end(repo, item):
    """8C 的外部 client 會走這條路徑；先把它釘死。

    模擬：外部 Vision 送出 brand / model / condition / serial 四筆建議 →
    人接受 brand、接受 serial、拒絕 model → 主表反映「人接受的」。
    """
    item_id = item["item"].id
    photo_id = item["photo"].id

    proposals = [
        ("brand", "ASUS", 0.94),
        ("model", "RTX 5070 Ti", 0.88),
        ("condition", "外觀良好", 0.81),
        ("identifier:serial", "XXXX-123456", 0.62),
    ]
    suggestions = {
        field: repo.add_suggestion(
            item_id, field, value, confidence=confidence,
            source="external", model_name="vision-x", source_photo_id=photo_id,
        )
        for field, value, confidence in proposals
    }

    # AI 交完貨，主表還沒動
    assert repo.get_item(item_id).brand == ""
    assert repo.get_item(item_id).model == ""
    assert repo.list_identifiers(item_id=item_id) == []

    repo.accept_suggestion(suggestions["brand"].id)
    repo.accept_suggestion(suggestions["identifier:serial"].id)
    repo.reject_suggestion(suggestions["model"].id)

    item_row = repo.get_item(item_id)
    assert item_row.brand == "ASUS"          # 接受 → 進主表
    assert item_row.model == ""              # 拒絕 → 沒進
    assert item_row.condition == ""          # 沒決定 → 沒進
    assert len(repo.list_identifiers(item_id=item_id)) == 1  # 序號另建

    counts = {s.status for s in repo.list_suggestions(item_id=item_id)}
    assert counts == {"accepted", "rejected", "pending"}

    events = [e.type for e in repo.item_history(item_id)]
    assert events.count("field.changed") == 1        # 只有 brand
    assert events.count("suggestion.accepted") == 2   # brand + serial
    assert events.count("suggestion.rejected") == 1   # model
    assert events.count("identifier.created") == 1


def test_item_trustworthy_means_no_ai_writes_without_a_human(repo, item):
    """沒有任何 accept，就不該有任何主表變動。"""
    item_id = item["item"].id
    before = snapshot(repo, item_id)

    for field, value, _ in [
        ("brand", "ASUS", 0.99),
        ("model", "RTX 5070 Ti", 0.99),
        ("condition", "全新", 0.99),
        ("notes", "盒裝齊全", 0.99),
        ("identifier:serial", "XXXX-123456", 0.99),
    ]:
        repo.add_suggestion(item_id, field, value, confidence=0.99,
                            source="external", model_name="vision-x")

    assert snapshot(repo, item_id) == before
    assert len(repo.list_suggestions(item_id=item_id, status="pending")) == 5