"""HTTP API 契約（SPEC-v1 §5）：正常流程與錯誤對應。

路由不做資料存取，全部走 Repository 與 shop.inbox，所以這裡驗到的
交易與 rollback 行為和 CLI、單元測試是同一套。
"""

from __future__ import annotations

import threading
import time

import pytest

from tests.conftest import make_jpeg


def jpeg(name: str = "a.jpg", **kwargs) -> tuple:
    """multipart 上傳需要的 (field, (檔名, 位元組, content-type))。"""
    return ("files", (name, make_jpeg(**kwargs), "image/jpeg"))


def upload(name: str = "a.jpg", data: bytes = b"x", content_type: str = "image/jpeg"):
    return ("files", (name, data, content_type))


def create_item(client, **body) -> dict:
    response = client.post("/api/items", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_observation(client, item_id: str, **body) -> dict:
    response = client.post(f"/api/items/{item_id}/observations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ----------------------------------------------------------------------
# system
# ----------------------------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": "2"}


def test_health_does_not_leak_the_data_root(client, config):
    assert str(config.data_root) not in client.get("/api/health").text


def test_stats_starts_empty(client):
    body = client.get("/api/stats").json()
    assert body["counts"]["items"] == 0
    assert body["recent"] == []


def test_stats_counts_and_recent_events(client):
    item = create_item(client, name="主機板")
    body = client.get("/api/stats").json()
    assert body["counts"]["items"] == 1
    assert [event["type"] for event in body["recent"]] == ["item.created"]
    assert body["recent"][0]["entity_id"] == item["id"]


def test_openapi_is_available(client):
    """SPEC §5：自動產生 OpenAPI，未來的手機 App 依它。"""
    spec = client.get("/openapi.json").json()
    assert "/api/items" in spec["paths"]
    assert "/api/items/{item_id}" in spec["paths"]
    assert "/api/observations/{observation_id}/photos" in spec["paths"]
    assert "/files/{path}" not in spec["paths"]  # 靜態檔案刻意不進契約


def test_docs_page_is_served(client):
    assert client.get("/docs").status_code == 200


# ----------------------------------------------------------------------
# items
# ----------------------------------------------------------------------


def test_create_item_returns_full_row(client):
    item = create_item(
        client, name="ROG STRIX B650E-F", brand="ASUS", attributes={"記憶體": "64GB"}
    )
    assert item["id"] == "ITM-0001"
    assert item["status"] == "active"
    assert item["quantity"] == 1
    assert item["attributes"] == {"記憶體": "64GB"}
    assert item["created_at"]


def test_create_item_rejects_zero_quantity(client):
    assert client.post("/api/items", json={"quantity": 0}).status_code == 400


def test_create_item_rejects_malformed_body(client):
    response = client.post("/api/items", json={"quantity": "很多"})
    assert response.status_code == 400


def test_get_item_detail_lists_children(client):
    item = create_item(client, name="主機板")
    observation = create_observation(client, item["id"], note="出貨前")
    client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "6LWMF1234567"}
    )
    client.post(
        f"/api/items/{item['id']}/suggestions", json={"field": "brand", "value": "ASUS"}
    )

    body = client.get(f"/api/items/{item['id']}").json()
    assert body["item"]["id"] == item["id"]
    assert [obs["id"] for obs in body["observations"]] == [observation["id"]]
    assert body["identifiers"][0]["value"] == "6LWMF1234567"
    assert body["suggestion_counts"] == {"pending": 1}
    assert body["photos"] == []


def test_get_missing_item_is_404(client):
    response = client.get("/api/items/ITM-9999")
    assert response.status_code == 404
    assert "ITM-9999" in response.json()["detail"]


def test_patch_item_updates_and_records_event(client):
    item = create_item(client, brand="ASUS")
    response = client.patch(f"/api/items/{item['id']}", json={"brand": "acer"})
    assert response.status_code == 200
    assert response.json()["brand"] == "acer"

    events = client.get(f"/api/items/{item['id']}/events").json()
    change = next(e for e in events if e["type"] == "field.changed")
    assert (change["field"], change["prev_value"], change["next_value"]) == (
        "brand", "ASUS", "acer",
    )


def test_patch_item_with_no_fields_is_a_noop(client):
    item = create_item(client, brand="ASUS")
    before = client.get(f"/api/items/{item['id']}").json()["item"]
    assert client.patch(f"/api/items/{item['id']}", json={}).status_code == 200
    assert client.get(f"/api/items/{item['id']}").json()["item"] == before


def test_patch_item_rejects_draft_status(client):
    """draft 不是合法 status —— 「未確認」由 suggestions 表达。"""
    item = create_item(client)
    response = client.patch(f"/api/items/{item['id']}", json={"status": "draft"})
    assert response.status_code == 400
    assert "draft" in response.json()["detail"]


def test_patch_missing_item_is_404(client):
    assert client.patch("/api/items/ITM-9999", json={"brand": "x"}).status_code == 404


def test_void_item_keeps_the_data(client):
    item = create_item(client, name="主機板")
    response = client.post(f"/api/items/{item['id']}/void")
    assert response.status_code == 200
    assert response.json()["status"] == "void"
    assert client.get(f"/api/items/{item['id']}").json()["item"]["name"] == "主機板"
    assert client.get("/api/items?status=void").json()[0]["id"] == item["id"]


def test_void_missing_item_is_404(client):
    assert client.post("/api/items/ITM-9999/void").status_code == 404


def test_list_items_filters_and_paginates(client):
    for index in range(5):
        create_item(client, name=f"item{index}", category="主機板" if index < 2 else "顯卡")
    assert len(client.get("/api/items").json()) == 5
    assert len(client.get("/api/items?category=主機板").json()) == 2
    assert [item["id"] for item in client.get("/api/items?limit=2").json()] == [
        "ITM-0001", "ITM-0002",
    ]
    assert [item["id"] for item in client.get("/api/items?limit=2&offset=2").json()] == [
        "ITM-0003", "ITM-0004",
    ]


def test_list_items_rejects_bad_paging(client):
    assert client.get("/api/items?limit=0").status_code == 400
    assert client.get("/api/items?offset=-1").status_code == 400


def test_search_by_partial_serial(client):
    """§7.1：手輸序號後半段要找得到。"""
    first = create_item(client, name="主機板 A")
    second = create_item(client, name="主機板 B")
    client.post(
        f"/api/items/{first['id']}/identifiers", json={"value": "BX-807 06_1234"}
    )
    client.post(
        f"/api/items/{second['id']}/identifiers", json={"value": "6LWMF1234567"}
    )

    found = client.get("/api/items?q=807061234").json()
    assert [item["id"] for item in found] == [first["id"]]

    found = client.get("/api/items?q=6lwmf").json()
    assert [item["id"] for item in found] == [second["id"]]


def test_search_by_text_fields(client):
    """§7.2：LIKE，不用 FTS5（實測 FTS5 查不到兩字中文）。"""
    create_item(client, name="主機板", brand="華碩")
    create_item(client, name="顯示卡", attributes={"規格": "RTX 4070"})
    assert len(client.get("/api/items?q=主機").json()) == 1  # 兩字也要找得到
    assert len(client.get("/api/items?q=華碩").json()) == 1
    assert len(client.get("/api/items?q=4070").json()) == 1


def test_search_combines_with_filters(client):
    create_item(client, name="主機板", category="主機板")
    create_item(client, name="主機板", category="顯示卡")
    found = client.get("/api/items?q=主機板&category=顯示卡").json()
    assert [item["category"] for item in found] == ["顯示卡"]


def test_search_with_no_match(client):
    create_item(client, name="主機板")
    assert client.get("/api/items?q=顯卡").json() == []


# ----------------------------------------------------------------------
# observations & photos
# ----------------------------------------------------------------------


def test_create_and_list_observations(client):
    item = create_item(client)
    first = create_observation(client, item["id"], captured_at="2026-10-02T14:30:00")
    create_observation(client, item["id"], kind="recheck",
                        captured_at="2026-10-20T11:00:00")

    assert first["kind"] == "intake"
    body = client.get(f"/api/items/{item['id']}/observations").json()
    assert [obs["kind"] for obs in body] == ["intake", "recheck"]


def test_observation_kind_is_restricted(client):
    item = create_item(client)
    response = client.post(
        f"/api/items/{item['id']}/observations", json={"kind": "return"}
    )
    assert response.status_code == 400
    assert "return" in response.json()["detail"]


def test_observation_for_missing_item_is_404(client):
    assert (
        client.post("/api/items/ITM-9999/observations", json={}).status_code == 404
    )


def test_patch_observation(client):
    item = create_item(client)
    observation = create_observation(client, item["id"], note="初稿")
    response = client.patch(
        f"/api/observations/{observation['id']}", json={"note": "補拍細節"}
    )
    assert response.status_code == 200
    assert response.json()["note"] == "補拍細節"


def test_upload_photo_to_observation(client, config):
    item = create_item(client)
    observation = create_observation(client, item["id"])

    response = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[jpeg(exif="2026:10:02 14:30:22")],
    )
    assert response.status_code == 201, response.text
    archived = response.json()["archived"]
    assert len(archived) == 1
    assert archived[0]["filename"] == (
        f"files/{item['id']}/original/20261002-143022_a.jpg"
    )
    assert archived[0]["orig_name"] == "a.jpg"
    assert (archived[0]["width"], archived[0]["height"]) == (4032, 3024)
    assert config.resolve(archived[0]["filename"]).exists()


def test_upload_multiple_photos(client):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    response = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[jpeg(exif="2026:10:02 14:30:00"), jpeg(exif="2026:10:02 14:31:00")],
    )
    assert response.status_code == 201
    assert len(response.json()["archived"]) == 2
    assert len(client.get(f"/api/items/{item['id']}").json()["photos"]) == 2


def test_upload_duplicate_is_skipped_not_failed(client):
    """手機一次傳多張，其中一張重複不該讓其他張白傳。"""
    item = create_item(client)
    observation = create_observation(client, item["id"])
    url = f"/api/observations/{observation['id']}/photos"
    client.post(url, files=[jpeg(exif="2026:10:02 14:30:00")])

    response = client.post(url, files=[jpeg(exif="2026:10:02 14:30:00")])
    assert response.status_code == 201
    assert response.json()["archived"] == []
    skipped = response.json()["skipped"]
    assert len(skipped) == 1
    assert skipped[0]["existing_photo_id"]
    assert len(client.get(f"/api/items/{item['id']}").json()["photos"]) == 1


def test_upload_without_files_is_400(client):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    assert (
        client.post(f"/api/observations/{observation['id']}/photos").status_code == 400
    )


def test_upload_to_missing_observation_is_404(client):
    assert (
        client.post("/api/observations/OBS-20261002-99/photos", files=[jpeg()])
        .status_code
        == 404
    )


def test_delete_derived_photo(client):
    item = create_item(client)
    with_stub = client.post(f"/api/items/{item['id']}/observations", json={})
    observation = with_stub.json()
    uploaded = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    assert client.delete(f"/api/photos/{uploaded['id']}").status_code == 400
    client.patch(f"/api/photos/{uploaded['id']}", json={"role": "derived"})
    assert client.delete(f"/api/photos/{uploaded['id']}").status_code == 204
    assert client.get(f"/api/items/{item['id']}").json()["photos"] == []


def test_original_photo_cannot_be_deleted(client):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    photo = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    response = client.delete(f"/api/photos/{photo['id']}")
    assert response.status_code == 400
    assert "derived" in response.json()["detail"]
    assert client.get(f"/api/items/{item['id']}").json()["photos"]


def test_delete_missing_photo_is_404(client):
    assert client.delete("/api/photos/NOPE").status_code == 404


def test_patch_photo_rejects_role_change_of_missing_photo(client):
    assert client.patch("/api/photos/NOPE", json={"angle": "label"}).status_code == 404


# ----------------------------------------------------------------------
# identifiers
# ----------------------------------------------------------------------


def test_create_identifier_normalizes(client):
    item = create_item(client)
    response = client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "BX-807 06_1234"}
    )
    assert response.status_code == 201
    assert response.json()["normalized"] == "BX807061234"
    assert response.json()["kind"] == "serial"
    assert response.json()["source"] == "human"


def test_identifier_keeps_source_photo(client, config):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    photo = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    response = client.post(
        f"/api/items/{item['id']}/identifiers",
        json={"value": "6LWMF1234567", "confidence": 0.8, "source_photo_id": photo["id"]},
    )
    assert response.status_code == 201
    assert response.json()["source_photo_id"] == photo["id"]


def test_identifier_rejects_photo_from_another_item(client):
    first = create_item(client)
    second = create_item(client)
    observation = create_observation(client, first["id"])
    photo = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    response = client.post(
        f"/api/items/{second['id']}/identifiers",
        json={"value": "6LWMF1234567", "source_photo_id": photo["id"]},
    )
    assert response.status_code == 400


def test_identifier_blank_value_is_400(client):
    item = create_item(client)
    assert (
        client.post(f"/api/items/{item['id']}/identifiers", json={"value": "  "})
        .status_code
        == 400
    )


def test_duplicate_identifier_on_same_item_is_409(client):
    item = create_item(client)
    client.post(f"/api/items/{item['id']}/identifiers", json={"value": "6LWMF1234567"})
    response = client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "6LWMF1234567"}
    )
    assert response.status_code == 409


def test_identifier_collision_across_items_is_409_with_existing_items(client):
    """§5：撞號回 409 + 既有 item 清單。"""
    first = create_item(client, name="第一件")
    second = create_item(client, name="第二件")
    client.post(
        f"/api/items/{first['id']}/identifiers", json={"value": "6LWMF1234567"}
    )

    response = client.post(
        f"/api/items/{second['id']}/identifiers", json={"value": "6lwmf 1234567"}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert first["id"] in detail
    assert "6LWMF1234567" in detail
    # 沒有寫進去
    assert client.get(f"/api/items/{second['id']}/identifiers").json() == []


def test_identifier_collision_can_be_forced(client):
    """確認是誤判後要能寫進去，否則 §2.3 的目的達不到。"""
    first = create_item(client)
    second = create_item(client)
    client.post(f"/api/items/{first['id']}/identifiers", json={"value": "6LWMF1234567"})

    response = client.post(
        f"/api/items/{second['id']}/identifiers",
        json={"value": "6LWMF1234567", "allow_collision": True},
    )
    assert response.status_code == 201
    assert client.get(f"/api/items/{second['id']}/identifiers").json()[0]["value"] == (
        "6LWMF1234567"
    )


def test_identifier_for_missing_item_is_404(client):
    assert (
        client.post("/api/items/ITM-9999/identifiers", json={"value": "X"}).status_code
        == 404
    )


def test_list_and_patch_identifier(client):
    item = create_item(client)
    created = client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "BX-807 06"}
    ).json()

    assert len(client.get(f"/api/items/{item['id']}/identifiers").json()) == 1
    patched = client.patch(
        f"/api/identifiers/{created['id']}", json={"value": "BX-80706X"}
    )
    assert patched.status_code == 200
    assert patched.json()["normalized"] == "BX80706X"


def test_patch_identifier_rejects_bad_kind(client):
    item = create_item(client)
    created = client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "X1"}
    ).json()
    assert (
        client.patch(f"/api/identifiers/{created['id']}", json={"kind": "uuid"})
        .status_code
        == 400
    )


def test_delete_identifier_keeps_event(client):
    item = create_item(client)
    created = client.post(
        f"/api/items/{item['id']}/identifiers", json={"value": "6LWMF1234567"}
    ).json()

    assert client.delete(f"/api/identifiers/{created['id']}").status_code == 204
    assert client.get(f"/api/items/{item['id']}/identifiers").json() == []
    events = client.get(f"/api/items/{item['id']}/events").json()
    assert any(e["type"] == "identifier.deleted" for e in events)


def test_delete_missing_identifier_is_404(client):
    assert client.delete("/api/identifiers/NOPE").status_code == 404


def test_lookup_identifier_by_partial_value(client):
    first = create_item(client, name="第一件")
    create_item(client, name="第二件")
    client.post(
        f"/api/items/{first['id']}/identifiers", json={"value": "BX-807 06_1234"}
    )

    body = client.get("/api/identifiers/lookup?value=807061234").json()
    assert body["normalized"] == "807061234"
    assert [match["item_id"] for match in body["matches"]] == [first["id"]]


def test_lookup_is_case_insensitive(client):
    item = create_item(client)
    client.post(f"/api/items/{item['id']}/identifiers", json={"value": "6LWMF1234567"})
    body = client.get("/api/identifiers/lookup?value=6lwmf").json()
    assert len(body["matches"]) == 1


def test_lookup_with_no_match(client):
    body = client.get("/api/identifiers/lookup?value=nothing").json()
    assert body["matches"] == []


def test_lookup_requires_value(client):
    assert client.get("/api/identifiers/lookup").status_code == 400


# ----------------------------------------------------------------------
# suggestions
# ----------------------------------------------------------------------


def test_suggestion_does_not_touch_item(client):
    item = create_item(client, name="主機板")
    response = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "brand", "value": "ASUS", "confidence": 0.9,
              "model_name": "claude-opus-4"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert client.get(f"/api/items/{item['id']}").json()["item"]["brand"] == ""


def test_suggestion_field_is_restricted(client):
    item = create_item(client)
    response = client.post(
        f"/api/items/{item['id']}/suggestions", json={"field": "price", "value": "1"}
    )
    assert response.status_code == 400


def test_accept_suggestion_writes_item_and_events(client):
    item = create_item(client, name="主機板")
    suggestion = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "brand", "value": "ASUS"},
    ).json()

    response = client.post(f"/api/suggestions/{suggestion['id']}/accept")
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["decided_at"]
    assert client.get(f"/api/items/{item['id']}").json()["item"]["brand"] == "ASUS"

    events = client.get(f"/api/items/{item['id']}/events").json()
    assert any(e["type"] == "suggestion.accepted" for e in events)
    assert any(
        e["type"] == "field.changed" and e["field"] == "brand" for e in events
    )


def test_accept_identifier_suggestion_creates_identifier(client):
    item = create_item(client, name="主機板")
    observation = create_observation(client, item["id"])
    photo = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    suggestion = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={
            "field": "identifier:serial",
            "value": "BX-807 06_1234",
            "confidence": 0.77,
            "source_photo_id": photo["id"],
        },
    ).json()
    assert client.post(f"/api/suggestions/{suggestion['id']}/accept").status_code == 200

    identifiers = client.get(f"/api/items/{item['id']}/identifiers").json()
    assert len(identifiers) == 1
    assert identifiers[0]["source"] == "accepted_suggestion"
    assert identifiers[0]["source_photo_id"] == photo["id"]
    assert identifiers[0]["confidence"] == 0.77


def test_reject_suggestion_keeps_it(client):
    item = create_item(client)
    suggestion = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "brand", "value": "ASUS"},
    ).json()

    response = client.post(f"/api/suggestions/{suggestion['id']}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert client.get(f"/api/items/{item['id']}").json()["item"]["brand"] == ""

    pending = client.get(f"/api/items/{item['id']}/suggestions?status=rejected").json()
    assert [row["id"] for row in pending] == [suggestion["id"]]

    events = client.get(f"/api/items/{item['id']}/events").json()
    assert any(e["type"] == "suggestion.rejected" for e in events)


def test_accept_twice_is_rejected(client):
    item = create_item(client)
    suggestion = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "brand", "value": "ASUS"},
    ).json()
    client.post(f"/api/suggestions/{suggestion['id']}/accept")
    assert (
        client.post(f"/api/suggestions/{suggestion['id']}/accept").status_code == 400
    )
    assert (
        client.post(f"/api/suggestions/{suggestion['id']}/reject").status_code == 400
    )


def test_accept_missing_suggestion_is_404(client):
    assert client.post("/api/suggestions/NOPE/accept").status_code == 404
    assert client.post("/api/suggestions/NOPE/reject").status_code == 404


def test_accept_conflicting_identifier_rolls_back(client):
    """接受失敗時建議狀態不能變 —— 交易行為與 CLI 一致。"""
    item = create_item(client)
    first = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "identifier:serial", "value": "6LWMF1234567"},
    ).json()
    second = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={"field": "identifier:serial", "value": "6LWMF1234567"},
    ).json()
    assert client.post(f"/api/suggestions/{first['id']}/accept").status_code == 200

    assert client.post(f"/api/suggestions/{second['id']}/accept").status_code == 409
    body = client.get(f"/api/items/{item['id']}").json()
    assert body["suggestion_counts"] == {"accepted": 1, "pending": 1}
    assert len(body["identifiers"]) == 1


# ----------------------------------------------------------------------
# events
# ----------------------------------------------------------------------


def test_item_history_is_newest_first(client):
    item = create_item(client, brand="ASUS")
    client.patch(f"/api/items/{item['id']}", json={"brand": "acer"})
    events = client.get(f"/api/items/{item['id']}/events").json()
    assert [event["type"] for event in events] == ["field.changed", "item.created"]


def test_revert_event_restores_previous_value(client):
    item = create_item(client, brand="ASUS")
    client.patch(f"/api/items/{item['id']}", json={"brand": "acer"})
    change = next(
        event
        for event in client.get(f"/api/items/{item['id']}/events").json()
        if event["type"] == "field.changed"
    )

    response = client.post(f"/api/events/{change['id']}/revert")
    assert response.status_code == 200
    assert response.json()["brand"] == "ASUS"
    assert client.get(f"/api/items/{item['id']}").json()["item"]["brand"] == "ASUS"


def test_revert_creation_event_is_400(client):
    item = create_item(client)
    created = next(
        event
        for event in client.get(f"/api/items/{item['id']}/events").json()
        if event["type"] == "item.created"
    )
    assert client.post(f"/api/events/{created['id']}/revert").status_code == 400


def test_revert_missing_event_is_404(client):
    assert client.post("/api/events/NOPE/revert").status_code == 404


# ----------------------------------------------------------------------
# inbox
# ----------------------------------------------------------------------


def test_inbox_starts_empty(client):
    body = client.get("/api/inbox").json()
    assert body == {"entries": [], "count": 0}


def test_upload_to_inbox_then_list(client, config):
    response = client.post(
        "/api/inbox/photos", files=[jpeg(exif="2026:10:02 14:30:22")]
    )
    assert response.status_code == 201
    assert response.json()["count"] == 1
    assert (config.inbox_dir / "a.jpg").exists()

    body = client.get("/api/inbox").json()
    assert body["entries"][0]["relative"] == "inbox/a.jpg"
    assert body["entries"][0]["captured_at"] == "2026-10-02T14:30:22"
    assert body["entries"][0]["captured_from"] == "exif"


def test_inbox_upload_never_overwrites(client, config):
    client.post("/api/inbox/photos", files=[jpeg(exif="2026:10:02 14:30:22")])
    client.post("/api/inbox/photos", files=[upload(data=b"different")])
    assert sorted(p.name for p in config.inbox_dir.iterdir()) == ["a-2.jpg", "a.jpg"]


def test_inbox_upload_without_files_is_400(client):
    assert client.post("/api/inbox/photos").status_code == 400


def test_inbox_upload_sanitizes_declared_filename(client, config):
    """檔名來自 multipart header，所以必然可能有非法字元。"""
    client.post("/api/inbox/photos", files=[upload("a/b:c*d?.jpg")])
    written = [path.name for path in config.inbox_dir.iterdir()]
    assert written == ["a_b_c_d_.jpg"]


def test_group_inbox_by_capture_time(client):
    for stamp in ["2026:10:02 14:30:00", "2026:10:02 14:31:00", "2026:10:02 18:00:00"]:
        client.post("/api/inbox/photos", files=[jpeg(exif=stamp)])

    groups = client.post("/api/inbox/group?gap_minutes=30").json()
    assert [len(group["entries"]) for group in groups] == [2, 1]
    assert groups[0]["captured_at"] == "2026-10-02T14:30:00"
    assert groups[0]["index"] == 0


def test_group_inbox_respects_gap_parameter(client):
    for stamp in ["2026:10:02 14:30:00", "2026:10:02 15:30:00"]:
        client.post("/api/inbox/photos", files=[jpeg(exif=stamp)])
    assert len(client.post("/api/inbox/group?gap_minutes=30").json()) == 2
    assert len(client.post("/api/inbox/group?gap_minutes=120").json()) == 1


def test_group_inbox_with_empty_inbox(client):
    assert client.post("/api/inbox/group").json() == []


# ----------------------------------------------------------------------
# 靜態檔案與安全
# ----------------------------------------------------------------------


def test_serve_archived_photo(client):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    photo = client.post(
        f"/api/observations/{observation['id']}/photos", files=[jpeg()]
    ).json()["archived"][0]

    response = client.get(f"/files/{photo['filename']}")
    assert response.status_code == 200
    assert response.content == make_jpeg()
    assert response.headers["content-type"].startswith("image/jpeg")


def test_serve_missing_file_is_404(client):
    assert client.get("/files/files/ITM-0001/original/nope.jpg").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        # 這三種 httpx 原樣送出，所以會真的走到 _serve_file 的防護。
        # （"/files/../x" 不能拿來測：httpx 會先把它正規化成 "/x"，
        #  那樣測到的是「沒有這個路由」，不是防護。）
        "/files/..%2Fcatalog.db",
        "/files/%2e%2e%2fcatalog.db",
        "/files/%2e%2e/catalog.db",
    ],
)
def test_static_files_blocks_encoded_path_traversal(client, path, config):
    """防護確實生效：回的是 _serve_file 的訊息，不是路由沒找到。"""
    assert config.database.exists()
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["detail"].startswith("找不到檔案：")


def test_static_files_rejects_literal_dotdot_over_raw_socket(config):
    """用原始 socket 送 literal `..`，繞過所有 client 端的 URL 正規化。

    httpx 會把 /files/../catalog.db 收斂成 /catalog.db，那樣根本到不了
    /files/{path}。要證明「server 本身擋得住」，就不能讓 client 幫忙。
    """
    import socket

    import uvicorn

    from shop.api import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(config), host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "測試用的 uvicorn 沒有起來"
        port = server.servers[0].sockets[0].getsockname()[1]

        for path in (
            "/files/../catalog.db",
            "/files/../../config.json",
            "/files/ITM-0001/../../catalog.db",
        ):
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(
                    f"GET {path} HTTP/1.1\r\nHost: localhost\r\n"
                    "Connection: close\r\n\r\n".encode()
                )
                raw = b""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
            head, _, body = raw.decode("utf-8", "replace").partition("\r\n\r\n")
            assert "404" in head.splitlines()[0], f"{path} → {head!r}"
            assert "找不到檔案" in body, f"{path} 的回應不是防護擋的：{body!r}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_static_files_does_not_expose_the_database(client, config):
    assert config.database.exists()
    assert client.get("/files/catalog.db").status_code == 404
    assert client.get("/files/config.json").status_code == 404


def test_absolute_path_is_not_resolved_under_files(client):
    assert client.get("/files/C:/Windows/win.ini").status_code == 404


def test_uploaded_filename_cannot_escape_the_data_root(client, config):
    item = create_item(client)
    observation = create_observation(client, item["id"])
    response = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[upload("a/b:c*d?.jpg")],
    )
    assert response.status_code == 201
    stored = response.json()["archived"][0]["filename"]
    assert stored.startswith(f"files/{item['id']}/original/")
    assert ".." not in stored
    assert config.resolve(stored).is_relative_to(config.files_dir)


def test_declared_filename_is_sanitized_not_obeyed(client, config):
    """multipart 宣告的檔名帶路徑穿越也不能寫到別處。"""
    item = create_item(client)
    observation = create_observation(client, item["id"])
    response = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[upload("../../escape.jpg")],
    )
    assert response.status_code == 201
    stored = response.json()["archived"][0]
    # 原始檔名照原樣記錄（「對回手機相簿」），但磁碟上的路徑被整理過
    assert stored["orig_name"] == "../../escape.jpg"
    leaf = stored["filename"].rsplit("/", 1)[-1]
    assert "/" not in leaf and "\\" not in leaf
    assert config.resolve(stored["filename"]).is_relative_to(
        config.files_dir / item["id"] / "original"
    )