"""Phase 8A：suggestions 的 HTTP 邊界。

8C 的外部 AI client 會直接打這四個端點，所以這裡驗的是「從外面看起來」
語意是不是成立，而不只是 Repository 層：

    POST /api/items/{id}/suggestions
    GET  /api/items/{id}/suggestions
    POST /api/suggestions/{id}/accept
    POST /api/suggestions/{id}/reject

重點：外部工具（Vision model、OCR、任何東西）**沒有**任何直接寫主表的管道。
它能做的只有寫 pending suggestion。
"""

from __future__ import annotations

import pytest

FIELD_TARGETS = ["name", "brand", "model", "category", "condition", "notes"]


@pytest.fixture()
def stocked(client):
    """一件有照片的商品。"""
    from tests.conftest import make_jpeg

    item = client.post("/api/items", json={"name": "待建檔"}).json()
    observation = client.post(f"/api/items/{item['id']}/observations",
                              json={"kind": "intake"}).json()
    photo = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[("files", ("IMG_4824.jpg", make_jpeg(exif="2026:10:02 14:33:55"),
                          "image/jpeg"))],
    ).json()["archived"][0]
    return {"item": item, "photo": photo, "observation": observation}


def submit(client, stocked, field, value, **extra):
    payload = {"field": field, "value": value, **extra}
    return client.post(f"/api/items/{stocked['item']['id']}/suggestions", json=payload)


def main_table(client, item_id):
    """主表狀態的快照，用來比對「有沒有被動到」。"""
    detail = client.get(f"/api/items/{item_id}").json()
    return {
        "item": tuple(detail["item"][k] for k in
                      ("name", "brand", "model", "category",
                       "condition", "notes", "quantity", "status")),
        "identifiers": [
            (i["kind"], i["value"]) for i in detail["identifiers"]
        ],
    }


# ----------------------------------------------------------------------
# 建立 → pending
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_external_client_can_submit_every_field(client, stocked, field):
    response = submit(client, stocked, field, f"{field}-的值")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["field"] == field
    assert body["decided_at"] is None


def test_submitting_a_suggestion_changes_nothing_in_the_main_table(client, stocked):
    before = main_table(client, stocked["item"]["id"])
    for field, value in [("brand", "ASUS"), ("model", "RTX 5070 Ti"),
                         ("condition", "外觀良好"), ("notes", "盒裝齊全")]:
        submit(client, stocked, field, value, confidence=0.9)
    assert main_table(client, stocked["item"]["id"]) == before


def test_suggestion_records_who_produced_it(client, stocked):
    """ItemTrace 不在乎 AI 是誰，但必須記下來。"""
    body = submit(client, stocked, "brand", "ASUS", confidence=0.94,
                  source="external", model_name="vision-x").json()
    assert body["source"] == "external"
    assert body["model_name"] == "vision-x"
    assert body["confidence"] == 0.94


def test_source_photo_id_is_carried_through(client, stocked):
    body = submit(client, stocked, "brand", "ASUS",
                  source_photo_id=stocked["photo"]["id"]).json()
    assert body["source_photo_id"] == stocked["photo"]["id"]


def test_source_photo_from_another_item_is_rejected(client, stocked):
    other = client.post("/api/items", json={"name": "別的"}).json()
    response = submit(client, stocked, "brand", "ASUS", source_photo_id="PHOTO-X")
    assert response.status_code in (400, 404)
    assert other["id"] != stocked["item"]["id"]


def test_quantity_cannot_be_suggested(client, stocked):
    """數量是事實，不是 AI 的判斷。"""
    response = submit(client, stocked, "quantity", "99")
    assert response.status_code == 400
    assert "quantity" in response.json()["detail"]


def test_missing_item_is_404(client):
    response = client.post("/api/items/ITM-9999/suggestions",
                           json={"field": "brand", "value": "ASUS"})
    assert response.status_code == 404


def test_listing_suggestions_can_filter_by_status(client, stocked):
    first = submit(client, stocked, "brand", "ASUS").json()
    second = submit(client, stocked, "model", "RTX 5070 Ti").json()
    client.post(f"/api/suggestions/{second['id']}/reject")

    pending = client.get(f"/api/items/{stocked['item']['id']}/suggestions"
                         "?status=pending").json()
    rejected = client.get(f"/api/items/{stocked['item']['id']}/suggestions"
                          "?status=rejected").json()
    assert [s["id"] for s in pending] == [first["id"]]
    assert [s["id"] for s in rejected] == [second["id"]]


# ----------------------------------------------------------------------
# reject → 主表不變
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_reject_leaves_the_main_table_alone(client, stocked, field):
    suggestion = submit(client, stocked, field, f"{field}-的值").json()
    before = main_table(client, stocked["item"]["id"])

    response = client.post(f"/api/suggestions/{suggestion['id']}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert main_table(client, stocked["item"]["id"]) == before


def test_reject_leaves_a_trace(client, stocked):
    suggestion = submit(client, stocked, "brand", "ASUS").json()
    client.post(f"/api/suggestions/{suggestion['id']}/reject")

    events = client.get(f"/api/items/{stocked['item']['id']}/events").json()
    assert any(e["type"] == "suggestion.rejected" for e in events)
    assert not any(e["type"] == "field.changed" for e in events)


# ----------------------------------------------------------------------
# accept → 主表才變
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELD_TARGETS)
def test_accept_writes_the_field(client, stocked, field):
    suggestion = submit(client, stocked, field, f"{field}-的值").json()
    response = client.post(f"/api/suggestions/{suggestion['id']}/accept")
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert client.get(f"/api/items/{stocked['item']['id']}").json()["item"][field] == (
        f"{field}-的值"
    )


def test_accept_writes_only_that_field(client, stocked):
    """AI 一次提很多建議，人只接受一個 → 只有那個欄位變。"""
    for field, value in [("brand", "ASUS"), ("model", "RTX 5070 Ti"),
                         ("condition", "外觀良好"), ("notes", "盒裝齊全")]:
        submit(client, stocked, field, value)

    brand = next(s for s in client.get(
        f"/api/items/{stocked['item']['id']}/suggestions").json() if s["field"] == "brand")
    client.post(f"/api/suggestions/{brand['id']}/accept")

    item = client.get(f"/api/items/{stocked['item']['id']}").json()["item"]
    assert item["brand"] == "ASUS"
    assert item["model"] == "" and item["condition"] == "" and item["notes"] == ""


def test_accept_records_field_changed(client, stocked):
    suggestion = submit(client, stocked, "brand", "ASUS").json()
    client.post(f"/api/suggestions/{suggestion['id']}/accept")

    events = client.get(f"/api/items/{stocked['item']['id']}/events").json()
    change = next(e for e in events
                  if e["type"] == "field.changed" and e["field"] == "brand")
    assert (change["prev_value"], change["next_value"]) == ("", "ASUS")


# ----------------------------------------------------------------------
# identifier 類
# ----------------------------------------------------------------------


def test_accept_identifier_suggestion_creates_an_identifier(client, stocked):
    suggestion = submit(client, stocked, "identifier:serial", "BX-807 06_1234",
                        confidence=0.77, model_name="vision-x",
                        source_photo_id=stocked["photo"]["id"]).json()
    before = main_table(client, stocked["item"]["id"])

    client.post(f"/api/suggestions/{suggestion['id']}/accept")

    after = main_table(client, stocked["item"]["id"])
    assert before["item"] == after["item"]          # items 不動
    assert len(after["identifiers"]) == 1
    identifier = after["identifiers"][0]
    assert identifier == ("serial", "BX-807 06_1234")

    detail = client.get(f"/api/items/{stocked['item']['id']}").json()
    stored = detail["identifiers"][0]
    assert stored["source"] == "accepted_suggestion"
    assert stored["source_photo_id"] == stocked["photo"]["id"]
    assert stored["confidence"] == 0.77


def test_reject_identifier_suggestion_creates_nothing(client, stocked):
    suggestion = submit(client, stocked, "identifier:serial", "XXXX-123456").json()
    client.post(f"/api/suggestions/{suggestion['id']}/reject")
    assert client.get(f"/api/items/{stocked['item']['id']}/identifiers").json() == []


# ----------------------------------------------------------------------
# 決定之後不可逆
# ----------------------------------------------------------------------


def test_cannot_accept_twice(client, stocked):
    suggestion = submit(client, stocked, "brand", "ASUS").json()
    assert client.post(f"/api/suggestions/{suggestion['id']}/accept").status_code == 200
    assert client.post(f"/api/suggestions/{suggestion['id']}/accept").status_code == 400


def test_cannot_flip_a_decision(client, stocked):
    accepted = submit(client, stocked, "brand", "ASUS").json()
    client.post(f"/api/suggestions/{accepted['id']}/accept")
    assert client.post(f"/api/suggestions/{accepted['id']}/reject").status_code == 400

    rejected = submit(client, stocked, "model", "RTX 5070 Ti").json()
    client.post(f"/api/suggestions/{rejected['id']}/reject")
    assert client.post(f"/api/suggestions/{rejected['id']}/accept").status_code == 400


def test_deciding_missing_suggestion_is_404(client):
    assert client.post("/api/suggestions/NOPE/accept").status_code == 404
    assert client.post("/api/suggestions/NOPE/reject").status_code == 404


# ----------------------------------------------------------------------
# 完整主線：外部 AI → pending → 人工確認 → 事件
# ----------------------------------------------------------------------


def test_full_external_to_human_chain(client, stocked):
    """8C 外部 client 產生的東西，實際走一遍。"""
    item_id = stocked["item"]["id"]
    photo_id = stocked["photo"]["id"]

    proposals = [
        ("brand", "ASUS", 0.94),
        ("model", "RTX 5070 Ti", 0.88),
        ("condition", "外觀良好", 0.81),
        ("identifier:serial", "XXXX-123456", 0.62),
    ]
    ids = {}
    for field, value, confidence in proposals:
        response = submit(client, stocked, field, value, confidence=confidence,
                          model_name="vision-x", source_photo_id=photo_id)
        assert response.status_code == 201
        ids[field] = response.json()["id"]

    # AI 交完貨：主表乾淨，5 筆 pending（其實 4 筆）
    item = client.get(f"/api/items/{item_id}").json()["item"]
    assert item["brand"] == "" and item["model"] == ""
    assert client.get(f"/api/items/{item_id}/identifiers").json() == []
    assert client.get(
        f"/api/items/{item_id}/suggestions?status=pending").json().__len__() == 4

    # 人接受兩個、拒絕一個、一個留著還沒決定
    client.post(f"/api/suggestions/{ids['brand']}/accept")
    client.post(f"/api/suggestions/{ids['identifier:serial']}/accept")
    client.post(f"/api/suggestions/{ids['model']}/reject")

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == "ASUS"
    assert detail["item"]["model"] == ""
    assert detail["item"]["condition"] == ""       # 還沒決定
    assert len(detail["identifiers"]) == 1
    assert detail["suggestion_counts"] == {"accepted": 2, "pending": 1, "rejected": 1}

    events = [e["type"] for e in client.get(f"/api/items/{item_id}/events").json()]
    assert events.count("field.changed") == 1
    assert events.count("identifier.created") == 1
    assert events.count("suggestion.accepted") == 2
    assert events.count("suggestion.rejected") == 1


def test_detail_page_data_supports_the_suggestion_ui(client, stocked):
    """8B 要用的欄位現在就必須在 detail 回應裡，不後來才補。"""
    suggestion = submit(client, stocked, "brand", "ASUS", confidence=0.94,
                        model_name="vision-x",
                        source_photo_id=stocked["photo"]["id"]).json()

    detail = client.get(f"/api/items/{stocked['item']['id']}").json()
    row = next(s for s in detail["suggestions"] if s["id"] == suggestion["id"])
    for key in ("id", "field", "value", "confidence", "status",
                "source_photo_id", "model_name", "created_at"):
        assert key in row, f"detail 少了 {key}"
    assert detail["suggestion_counts"]["pending"] == 1
    # 來源照片要能從 detail 的 photos 對回來
    assert row["source_photo_id"] in {p["id"] for p in detail["photos"]}