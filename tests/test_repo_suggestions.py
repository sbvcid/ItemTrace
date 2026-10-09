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
    # notes 原本在這裡（Phase 2 依 SPEC-v1 §2.2 的註解）是不可建議的欄位，
    # Phase 8A 起開放 —— 外部 Vision 常從照片推斷外觀描述，放進 notes 合理。
    for field in ("price", "identifier:uuid", "quantity", "status"):
        with pytest.raises(ValidationError):
            repo.add_suggestion(item.id, field, "x")


def test_notes_is_suggestable_since_phase8a(repo, item):
    suggestion = repo.add_suggestion(item.id, "notes", "外觀良好，有輕微刮痕")
    repo.accept_suggestion(suggestion.id)
    assert repo.get_item(item.id).notes == "外觀良好，有輕微刮痕"


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


# ----------------------------------------------------------------------
# Phase 2A：修訂語意（replace_pending_suggestions）
# ----------------------------------------------------------------------


def test_replace_pending_suggestions_supersedes_only_pending(repo, item):
    """新一輪分析是最新詮釋：只有 pending 被 superseded；
    accepted / rejected 是歷史，不受影響；主表仍然沒被碰過。"""
    stale = repo.add_suggestion(item.id, "brand", "ASUS")
    kept = repo.add_suggestion(item.id, "model", "B650E-F")
    repo.accept_suggestion(kept.id)
    rejected = repo.add_suggestion(item.id, "condition", "有刮痕")
    repo.reject_suggestion(rejected.id)

    created, superseded = repo.replace_pending_suggestions(
        item.id,
        [{"field": "brand", "value": "acer",
          "confidence": 0.9, "source_photo_id": None}],
        model_name="test/model",
    )

    assert superseded == 1
    assert len(created) == 1
    assert created[0].status == "pending"
    assert created[0].value == "acer"
    assert created[0].model_name == "test/model"

    assert repo.get_suggestion(stale.id).status == "superseded"
    assert repo.get_suggestion(stale.id).decided_at is not None
    assert repo.get_suggestion(kept.id).status == "accepted"
    assert repo.get_suggestion(rejected.id).status == "rejected"

    pending = repo.list_suggestions(item_id=item.id, status="pending")
    assert [row.value for row in pending] == ["acer"]
    assert repo.get_item(item.id).brand == ""

    assert [event.type for event in repo.list_events("suggestion", stale.id)] == [
        "suggestion.superseded",  # 事件最新在前
        "suggestion.created",
    ]


def test_replace_pending_suggestions_is_atomic(repo, item):
    """新一輪只要有任一筆不合法，supersede 與已寫入的新建議全部回滾，
    不留半套結果、舊 pending 原封不動。"""
    stale = repo.add_suggestion(item.id, "brand", "ASUS")

    with pytest.raises(ValidationError):
        repo.replace_pending_suggestions(
            item.id,
            [
                {"field": "brand", "value": "acer",
                 "confidence": 0.9, "source_photo_id": None},
                {"field": "status", "value": "void"},  # 不在白名單
            ],
            model_name="test/model",
        )

    assert repo.get_suggestion(stale.id).status == "pending"
    assert repo.get_suggestion(stale.id).decided_at is None
    assert [row.id for row in repo.list_suggestions(item_id=item.id)] == [stale.id]
    assert [event.type for event in repo.list_events("suggestion", stale.id)] == [
        "suggestion.created"
    ]


def test_superseded_is_terminal(repo, item):
    """superseded 不會復活：不能再被接受、拒絕或修改。
    （空的新一輪也要 supersede 舊 pending —— 最新詮釋就是「沒有建議」。）"""
    stale = repo.add_suggestion(item.id, "brand", "ASUS")
    created, superseded = repo.replace_pending_suggestions(
        item.id, [], model_name="test/model"
    )

    assert created == []
    assert superseded == 1
    assert repo.get_suggestion(stale.id).status == "superseded"

    with pytest.raises(ValidationError):
        repo.accept_suggestion(stale.id)
    with pytest.raises(ValidationError):
        repo.reject_suggestion(stale.id)
    with pytest.raises(ValidationError):
        repo.update_suggestion(stale.id, {"value": "acer"})
    assert repo.get_item(item.id).brand == ""


# ----------------------------------------------------------------------
# Phase 2B：attribute:<key> 提案（通用屬性的最小契約）
# ----------------------------------------------------------------------


def test_attribute_suggestion_key_is_validated(repo, item):
    """key 形狀由軟體強制：小寫開頭、英數與底線、長度 1~40。"""
    ok = repo.add_suggestion(item.id, "attribute:vendor", "光華商場")
    assert ok.status == "pending"
    assert ok.attribute_key == "vendor"

    for bad in (
        "attribute:",                      # 空 key
        "attribute:Bad-Key",               # 大寫與 dash
        "attribute:1abc",                  # 數字開頭
        "attribute:中文",                   # 非 ASCII
        "attribute:" + "x" * 41,           # 超過長度上限
    ):
        with pytest.raises(ValidationError):
            repo.add_suggestion(item.id, bad, "x")


def test_accept_attribute_suggestion_merges_single_key(repo, item):
    """接受屬性建議是單鍵合併：既有鍵（含使用者自己填的）全部保留。"""
    repo.update_item(item.id, {"attributes": {"warranty": "兩年"}})
    suggestion = repo.add_suggestion(
        item.id, "attribute:vendor", "光華商場", confidence=0.8
    )
    accepted = repo.accept_suggestion(suggestion.id)

    assert accepted.status == "accepted"
    attributes = repo.get_item(item.id).attributes
    assert attributes == {"warranty": "兩年", "vendor": "光華商場"}

    # 事件語義：attributes 的 field.changed 帶前後完整快照
    change = next(
        event for event in repo.list_events("item", item.id)
        if event.type == "field.changed" and event.field == "attributes"
    )
    assert change.prev_value == {"warranty": "兩年"}
    assert change.next_value == {"warranty": "兩年", "vendor": "光華商場"}

    # accepted 建議是來源紀錄：保留 confidence 與來源資訊
    stored = repo.get_suggestion(suggestion.id)
    assert stored.confidence == 0.8
    assert stored.status == "accepted"


def test_accept_attribute_suggestion_does_not_touch_fixed_fields(repo, item):
    """屬性提案只寫 attributes；固定欄位（name 等）不受影響。"""
    suggestion = repo.add_suggestion(item.id, "attribute:color", "霧面黑")
    repo.accept_suggestion(suggestion.id)

    after = repo.get_item(item.id)
    assert after.attributes == {"color": "霧面黑"}
    assert after.name == "主機板"          # fixture 的原始名稱
    assert after.brand == ""
