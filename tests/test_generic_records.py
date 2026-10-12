"""通用照片紀錄第一版：非商品照片的草稿 → 保存 → 檢索流程。

以 mock provider 執行（不呼叫真實 AI），涵蓋：
- 晨光／街景照片產生通用標題、描述與動態屬性，不被硬套商品欄位
- 動態屬性的檢視／修改／保存／重新載入（對應 capture.js 審閱流程的
  create → accept → PATCH attributes 順序）
- 保存後搜尋命中標題、描述與動態屬性；未確認的建議不進搜尋
- AI 輸出失敗時照片仍可保存，且不會留下半套正式資料

這裡只驗證後端契約；瀏覽器端的實際操作以人工／Playwright 驗收。
"""

from __future__ import annotations

from tests.test_capture_ui import install_ai, upload_staged


def save_draft(client, staged, draft):
    """模擬 capture.js「存起來」的請求順序（intake → create → accept）。

    回傳建立的 item_id。與 test_deferred_save_flow_end_to_end 相同的
    真實 HTTP 路徑，只是聚焦通用欄位。
    """
    done = client.post(
        "/api/inbox/intake", json={"files": staged, "kind": "intake"}
    ).json()
    item_id = done["item_id"]
    photo_id_by_orig_name = {p["orig_name"]: p["id"] for p in done["archived"]}

    created_ids = []
    for suggestion in draft["suggestions"]:
        index = suggestion["source_photo_index"]
        response = client.post(
            f"/api/items/{item_id}/suggestions",
            json={
                "field": suggestion["field"],
                "value": suggestion["value"],
                "confidence": suggestion["confidence"],
                "source": "external",
                "model_name": draft["model"],
                "source_photo_id": (
                    photo_id_by_orig_name.get(staged[index].split("/")[-1])
                    if index is not None else None
                ),
                "actor": "external",
            },
        )
        assert response.status_code == 201, response.text
        created_ids.append(response.json()["id"])

    for suggestion_id in created_ids:
        assert client.post(
            f"/api/suggestions/{suggestion_id}/accept"
        ).status_code == 200
    return item_id


# ----------------------------------------------------------------------
# 1＆5. 晨光紀錄：草稿直通 → 保存 → 搜尋
# ----------------------------------------------------------------------


def test_morning_light_record_flows_from_draft_to_search(client, monkeypatch):
    install_ai(monkeypatch, [
        {"field": "name", "value": "清晨的陽光",
         "confidence": 0.9, "source_photo_index": 0},
        {"field": "attribute:description",
         "value": "陽光從窗邊斜射進來，在木桌上留下長長的影子。",
         "confidence": 0.85, "source_photo_index": 0},
        {"field": "attribute:time_of_day", "value": "清晨",
         "confidence": 0.8, "source_photo_index": 0},
    ])

    staged, _entries = upload_staged(client, ["morning.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()

    # 草稿完整直通 —— attribute:* 不會被吞掉；此時仍是零正式紀錄。
    assert [(s["field"], s["value"]) for s in draft["suggestions"]] == [
        ("name", "清晨的陽光"),
        ("attribute:description", "陽光從窗邊斜射進來，在木桌上留下長長的影子。"),
        ("attribute:time_of_day", "清晨"),
    ]
    assert client.get("/api/items").json() == []

    item_id = save_draft(client, staged, draft)
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["name"] == "清晨的陽光"
    assert detail["item"]["brand"] == ""
    assert detail["item"]["attributes"]["description"].startswith("陽光從窗邊")
    assert detail["item"]["attributes"]["time_of_day"] == "清晨"
    assert detail["identifiers"] == []

    # 檢索：標題、描述內文、動態屬性值都找得到。
    assert [i["id"] for i in client.get("/api/items?q=清晨").json()] == [item_id]
    assert [i["id"] for i in client.get("/api/items?q=木桌").json()] == [item_id]
    assert [i["id"] for i in client.get("/api/items?q=清晨的陽光").json()] == [item_id]


# ----------------------------------------------------------------------
# 2. 街景：保留場景資訊、不硬套商品欄位
# ----------------------------------------------------------------------


def test_street_scene_keeps_scene_attributes_without_item_fields(client, monkeypatch):
    install_ai(monkeypatch, [
        {"field": "name", "value": "傍晚的街景，招牌亮起",
         "confidence": 0.88, "source_photo_index": 0},
        {"field": "attribute:description",
         "value": "暮色中的街道兩側招牌亮起，行人背影往畫面深處走。",
         "confidence": 0.85, "source_photo_index": 0},
        {"field": "attribute:weather", "value": "陰天",
         "confidence": 0.7, "source_photo_index": 0},
    ])
    staged, _entries = upload_staged(client, ["street.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()

    fields = [s["field"] for s in draft["suggestions"]]
    assert "brand" not in fields and "model" not in fields and "condition" not in fields
    assert not any(f.startswith("identifier:") for f in fields)

    item_id = save_draft(client, staged, draft)
    item = client.get(f"/api/items/{item_id}").json()["item"]
    assert item["name"] == "傍晚的街景，招牌亮起"
    assert item["brand"] == "" and item["model"] == "" and item["condition"] == ""
    assert item["attributes"]["description"].startswith("暮色中的街道")
    assert item["attributes"]["weather"] == "陰天"
    assert [i["id"] for i in client.get("/api/items?q=招牌").json()] == [item_id]


# ----------------------------------------------------------------------
# 3. 商品照片：既有辨識能力保留
# ----------------------------------------------------------------------


def test_product_photo_still_identifies_item_fields(client, monkeypatch):
    install_ai(monkeypatch, [
        {"field": "name", "value": "Makita 18V 電鑽",
         "confidence": 0.95, "source_photo_index": 0},
        {"field": "brand", "value": "Makita",
         "confidence": 0.97, "source_photo_index": 1},
        {"field": "model", "value": "DDF482",
         "confidence": 0.9, "source_photo_index": 1},
        {"field": "condition", "value": "外殼輕微使用痕跡",
         "confidence": 0.8, "source_photo_index": 0},
        {"field": "identifier:serial", "value": "1234567",
         "confidence": 0.99, "source_photo_index": 1},
    ])
    staged, _entries = upload_staged(client, ["drill.jpg", "label.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()
    item_id = save_draft(client, staged, draft)

    detail = client.get(f"/api/items/{item_id}").json()
    item = detail["item"]
    assert (item["brand"], item["model"]) == ("Makita", "DDF482")
    assert item["condition"] == "外殼輕微使用痕跡"
    assert [i["value"] for i in detail["identifiers"]] == ["1234567"]
    assert client.get("/api/items?q=1234567").json()[0]["id"] == item_id


# ----------------------------------------------------------------------
# 4. 動態屬性：修改與新增的來回
# ----------------------------------------------------------------------


def test_dynamic_attribute_edit_and_reload_round_trip(client):
    """接受後可修改、可自行新增；重新載入看得到，搜尋同步更新。

    對應 capture.js 審閱的「修改」：AI 草稿照 create → accept 落成建議
    （保留追溯），使用者的修改／新增以 PATCH attributes 合併落地。
    """
    item = client.post("/api/items", json={"name": "桌面一角"}).json()
    suggestion = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={
            "field": "attribute:description",
            "value": "桌上有一杯咖啡與筆記本。",
            "confidence": 0.8,
            "source": "external",
        },
    ).json()
    assert client.post(
        f"/api/suggestions/{suggestion['id']}/accept"
    ).status_code == 200

    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["item"]["attributes"]["description"] == "桌上有一杯咖啡與筆記本。"

    merged = dict(detail["item"]["attributes"])
    merged["description"] = "桌上有一杯黑咖啡、一本攤開的筆記本。"
    merged["time_of_day"] = "午後"  # 使用者自行新增
    patch = client.patch(
        f"/api/items/{item['id']}",
        json={"attributes": merged, "actor": "user"},
    )
    assert patch.status_code == 200

    reloaded = client.get(f"/api/items/{item['id']}").json()["item"]
    assert reloaded["attributes"]["description"] == "桌上有一杯黑咖啡、一本攤開的筆記本。"
    assert reloaded["attributes"]["time_of_day"] == "午後"

    # 搜尋同步：新值命中；舊的 accepted 建議值仍經由建議索引找得到
    #（「新詮釋取代舊值後，舊詞彙還在」的既有設計）。
    assert client.get("/api/items?q=黑咖啡").json()[0]["id"] == item["id"]
    assert client.get("/api/items?q=咖啡與筆記本").json()[0]["id"] == item["id"]


# ----------------------------------------------------------------------
# 6. 未確認的 AI 建議不污染正式資料；AI 失敗仍可保存
# ----------------------------------------------------------------------


def test_unconfirmed_suggestions_never_leak_into_search(client):
    """pending／rejected 的猜測不得變成可搜尋的事實，也不寫入 attributes。"""
    item = client.post("/api/items", json={"name": "未確認測試"}).json()
    pending = client.post(
        f"/api/items/{item['id']}/suggestions",
        json={
            "field": "attribute:description",
            "value": "UNCONFIRMED-GUESS-42",
            "confidence": 0.9,
            "source": "external",
        },
    ).json()

    assert client.get("/api/items?q=UNCONFIRMED-GUESS-42").json() == []
    assert client.get(f"/api/items/{item['id']}").json()["item"]["attributes"] == {}

    assert client.post(f"/api/suggestions/{pending['id']}/reject").status_code == 200
    assert client.get("/api/items?q=UNCONFIRMED-GUESS-42").json() == []
    assert client.get(f"/api/items/{item['id']}").json()["item"]["attributes"] == {}


def test_invalid_ai_output_leaves_no_partial_data(client, monkeypatch):
    """模型輸出不合格（欄位不在白名單）→ 草稿 400、零正式資料；
    照片仍可走手動流程保存。"""
    install_ai(monkeypatch, [
        {"field": "flavor", "value": "檸檬", "confidence": 0.9,
         "source_photo_index": 0},
    ])
    staged, _entries = upload_staged(client, ["x.jpg"])
    response = client.post("/api/inbox/analyze", json={"files": staged})
    assert response.status_code == 400
    assert client.get("/api/items").json() == []

    # 手動流程不受影響：照片照常存檔，且沒有任何 AI 猜測混入。
    done = client.post(
        "/api/inbox/intake", json={"files": staged, "kind": "intake"}
    ).json()
    detail = client.get(f"/api/items/{done['item_id']}").json()
    assert detail["item"]["attributes"] == {}
    assert detail["suggestions"] == []
    assert len(detail["photos"]) == 1


# ----------------------------------------------------------------------
# AI prompt：通用化，且既有保護條款不被移除
# ----------------------------------------------------------------------


def test_prompt_covers_generic_scenes_and_keeps_protection_policy():
    from shop.ai_client import PROMPT

    # 通用場景與範例
    assert "清晨的陽光" in PROMPT
    assert "街景" in PROMPT
    assert "非商品照片" in PROMPT
    # 不得憑空補入地點、人物身分、時間
    assert "憑空補入" in PROMPT
    assert "人物身分" in PROMPT
    # 非商品照片不得硬套商品欄位
    assert "不要輸出品牌" in PROMPT
    # 既有拒絕／撤回政策原樣保留（不可因通用化被移除）
    assert "可以再次提出" in PROMPT
    assert "不會自動套用被拒絕或撤回過的值" in PROMPT


# ----------------------------------------------------------------------
# 保存一致性：以使用者最後確認的內容為準。
# AI 原值只留在建議紀錄裡（reject／accept 的歷史與來源追溯），
# 使用者的修改一律經 PATCH／addIdentifier 落地，不冒充 AI 判讀。
# 這些測試對應 capture.js 存檔流程實際使用的 API 順序。
# ----------------------------------------------------------------------


def _new_item(client):
    staged, _entries = upload_staged(client, ["save.jpg"])
    done = client.post(
        "/api/inbox/intake", json={"files": staged, "kind": "intake"}
    ).json()
    return done["item_id"]


def _create_suggestion(client, item_id, field, value, *, confidence=0.9):
    response = client.post(
        f"/api/items/{item_id}/suggestions",
        json={
            "field": field,
            "value": value,
            "confidence": confidence,
            "source": "external",
            "model_name": "test/model:free",
            "actor": "external",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_cleared_field_keeps_raw_ai_value_only_in_rejected_suggestion(client):
    """使用者清空欄位：原始 AI 建議不得仍被接受寫入正式紀錄。"""
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(client, item_id, "brand", "SONY")

    assert client.post(
        f"/api/suggestions/{suggestion_id}/reject"
    ).status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == ""
    assert [s["status"] for s in detail["suggestions"]] == ["rejected"]
    assert detail["suggestions"][0]["value"] == "SONY"  # AI 原值保留（追溯）
    assert detail["suggestions"][0]["model_name"] == "test/model:free"
    # 未確認的猜測不進搜尋
    assert client.get("/api/items?q=SONY").json() == []


def test_edited_field_is_user_patch_and_suggestion_keeps_raw_value(client):
    """使用者修改欄位：正式值＝使用者輸入；建議維持 AI 原值（不冒充）。"""
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(client, item_id, "brand", "SONY")

    assert client.post(
        f"/api/suggestions/{suggestion_id}/reject"
    ).status_code == 200
    patch = client.patch(
        f"/api/items/{item_id}", json={"brand": "Sony", "actor": "user"}
    )
    assert patch.status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == "Sony"
    assert detail["suggestions"][0]["status"] == "rejected"
    assert detail["suggestions"][0]["value"] == "SONY"  # 沒有被改成 "Sony"
    assert [i["id"] for i in client.get("/api/items?q=Sony").json()] == [item_id]


def test_removed_attribute_is_not_saved(client):
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(
        client, item_id, "attribute:weather", "多雲"
    )

    assert client.post(
        f"/api/suggestions/{suggestion_id}/reject"
    ).status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"] == {}
    assert client.get("/api/items?q=多雲").json() == []


def test_removed_after_accept_is_actually_removed_from_record(client):
    """重試情境：已接受的屬性被使用者移除 ⇒ 真的從紀錄刪除。

    已接受的建議本身保留在歷史（追溯不破壞），但正式 attributes 不再有
    該鍵 —— 不是只停止重新套用、假裝已移除。
    """
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(
        client, item_id, "attribute:description", "舊描述"
    )
    assert client.post(
        f"/api/suggestions/{suggestion_id}/accept"
    ).status_code == 200
    assert client.get(f"/api/items/{item_id}").json()["item"]["attributes"] == {
        "description": "舊描述"
    }

    # capture.js 的移除：GET 現值 → 刪除該鍵 → PATCH 寫回（差異併回）
    current = client.get(f"/api/items/{item_id}").json()["item"]["attributes"]
    merged = dict(current)
    del merged["description"]
    assert client.patch(
        f"/api/items/{item_id}", json={"attributes": merged}
    ).status_code == 200

    assert client.get(f"/api/items/{item_id}").json()["item"]["attributes"] == {}
    statuses = [s["status"] for s in client.get(
        f"/api/items/{item_id}").json()["suggestions"]]
    assert statuses == ["accepted"]  # 建議歷史仍在


def test_replaced_attribute_keeps_final_value_only(client):
    """移除 AI 屬性後以同 key 新增自訂值：保存最終值，舊值不復活。"""
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(
        client, item_id, "attribute:weather", "多雲"
    )
    assert client.post(
        f"/api/suggestions/{suggestion_id}/reject"
    ).status_code == 200
    # 已拒絕的建議不得被重新接受（待確認保護；後端回 400）
    assert client.post(
        f"/api/suggestions/{suggestion_id}/accept"
    ).status_code == 400

    assert client.patch(
        f"/api/items/{item_id}", json={"attributes": {"weather": "晴朗"}}
    ).status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"] == {"weather": "晴朗"}
    assert [i["id"] for i in client.get("/api/items?q=晴朗").json()] == [item_id]


def test_cleared_identifiers_are_not_saved(client):
    item_id = _new_item(client)
    serial = _create_suggestion(client, item_id, "identifier:serial", "SN-1")
    imei = _create_suggestion(
        client, item_id, "identifier:imei", "123456789012345"
    )
    assert client.post(f"/api/suggestions/{serial}/reject").status_code == 200
    assert client.post(f"/api/suggestions/{imei}/reject").status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["identifiers"] == []


def test_edited_identifier_is_saved_as_user_value_only(client):
    item_id = _new_item(client)
    barcode = _create_suggestion(
        client, item_id, "identifier:barcode", "4901234567894"
    )
    assert client.post(f"/api/suggestions/{barcode}/reject").status_code == 200
    added = client.post(
        f"/api/items/{item_id}/identifiers",
        json={"kind": "barcode", "value": "4901234567895"},
    )
    assert added.status_code == 201

    detail = client.get(f"/api/items/{item_id}").json()
    assert [(i["kind"], i["value"]) for i in detail["identifiers"]] == [
        ("barcode", "4901234567895")
    ]
    # 建議保留 AI 原值，不會被改成使用者修正後的值
    assert detail["suggestions"][0]["value"] == "4901234567894"


def test_removed_after_accept_identifier_is_really_deleted(client):
    item_id = _new_item(client)
    serial = _create_suggestion(client, item_id, "identifier:serial", "SN-7")
    assert client.post(f"/api/suggestions/{serial}/accept").status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert len(detail["identifiers"]) == 1

    deleted = client.delete(
        f"/api/identifiers/{detail['identifiers'][0]['id']}"
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/items/{item_id}").json()["identifiers"] == []


# ----------------------------------------------------------------------
# 重複描述候選（來自不同照片、值不同）：每一筆都看得見，必須明確選擇。
#
# 修正前 capture.js 只顯示第一筆描述、其餘描述列被排除在編輯 UI 之外，
# 但存檔驗證又檢查重複的 attribute key —— 使用者被阻止存檔卻無法在
# 介面上找到並移除多餘的列（死結）。以下模擬修正後 capture.js 的存檔
# 順序：所有 description 建議先落成正式建議（保留 AI 原值／model／
# confidence／來源照片）；選取的一筆原值未改 → accept；被移除／未選取
# ／修改的 → reject（使用者修改走 PATCH，不冒充 AI 判讀）。
# ----------------------------------------------------------------------

TWO_DESCRIPTIONS = [
    {"field": "name", "value": "早餐桌", "confidence": 0.9,
     "source_photo_index": 0},
    {"field": "attribute:description", "value": "桌上有一杯熱咖啡。",
     "confidence": 0.8, "source_photo_index": 0},
    {"field": "attribute:description", "value": "窗外正在下雨。",
     "confidence": 0.7, "source_photo_index": 1},
]


def two_description_draft(client, monkeypatch):
    """兩筆來自不同照片、值不同的 attribute:description 草稿。"""
    install_ai(monkeypatch, TWO_DESCRIPTIONS)
    staged, _entries = upload_staged(client, ["coffee.jpg", "window.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()
    return staged, draft


def create_draft_suggestions(client, staged, draft):
    """intake ＋ 草稿全部落成正式建議（與 capture.js 相同的追溯欄位）。"""
    done = client.post(
        "/api/inbox/intake", json={"files": staged, "kind": "intake"}
    ).json()
    item_id = done["item_id"]
    photo_id_by_orig_name = {p["orig_name"]: p["id"] for p in done["archived"]}
    created = []
    for suggestion in draft["suggestions"]:
        index = suggestion["source_photo_index"]
        response = client.post(
            f"/api/items/{item_id}/suggestions",
            json={
                "field": suggestion["field"],
                "value": suggestion["value"],
                "confidence": suggestion["confidence"],
                "source": "external",
                "model_name": draft["model"],
                "source_photo_id": (
                    photo_id_by_orig_name.get(staged[index].split("/")[-1])
                    if index is not None else None
                ),
                "actor": "external",
            },
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["id"])
    return item_id, created


def test_two_description_candidates_remove_one_and_edit_the_other(
        client, monkeypatch):
    """核心情境：辨識兩筆候選（來自不同照片）→ 移除一筆 → 修改留下的
    一筆 → 保存；詳情頁與搜尋呈現最終值，AI 原值與來源追溯完整保留。"""
    staged, draft = two_description_draft(client, monkeypatch)
    descriptions = [s for s in draft["suggestions"]
                    if s["field"] == "attribute:description"]
    assert [s["value"] for s in descriptions] == [
        "桌上有一杯熱咖啡。", "窗外正在下雨。"]
    assert [s["source_photo_index"] for s in descriptions] == [0, 1]
    # 草稿階段仍是零正式紀錄
    assert client.get("/api/items").json() == []

    item_id, created = create_draft_suggestions(client, staged, draft)

    # 使用者辨識後移除「窗外正在下雨。」那一筆（未採用），並修改留下的
    # 描述（使用者內容走 PATCH；建議維持 AI 原值，不冒充判讀）。
    assert client.post(
        f"/api/suggestions/{created[2]}/reject").status_code == 200
    assert client.post(
        f"/api/suggestions/{created[1]}/reject").status_code == 200
    final_value = "雨中的咖啡桌。"
    current = client.get(f"/api/items/{item_id}").json()["item"]["attributes"]
    merged = {**current, "description": final_value}
    assert client.patch(
        f"/api/items/{item_id}", json={"attributes": merged, "actor": "user"}
    ).status_code == 200
    assert client.patch(
        f"/api/items/{item_id}", json={"name": "早餐桌", "actor": "user"}
    ).status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"]["description"] == final_value

    # 兩筆建議都保留 AI 原值、model、信心與各自的來源照片；使用者修改
    # 後的最終值沒有被寫回任何建議
    by_value = {s["value"]: s for s in detail["suggestions"]}
    coffee = by_value["桌上有一杯熱咖啡。"]
    rain = by_value["窗外正在下雨。"]
    assert {coffee["status"], rain["status"]} == {"rejected"}
    assert final_value not in by_value
    assert coffee["confidence"] == 0.8 and rain["confidence"] == 0.7
    assert coffee["model_name"] == "test/model:free"
    assert rain["model_name"] == "test/model:free"
    photos = {p["orig_name"]: p["id"] for p in detail["photos"]}
    assert coffee["source_photo_id"] == photos["coffee.jpg"]
    assert rain["source_photo_id"] == photos["window.jpg"]
    assert coffee["source_photo_id"] != rain["source_photo_id"]

    # 詳情頁與搜尋呈現最終值；被移除的候選不進搜尋
    assert [i["id"] for i in client.get("/api/items?q=咖啡桌").json()] == [item_id]
    assert client.get("/api/items?q=熱咖啡").json() == []
    assert client.get("/api/items?q=正在下雨").json() == []


def test_two_description_candidates_keep_one_unchanged(client, monkeypatch):
    """選取的一筆原值未改 → accept（AI 值落地，來源追溯成立）；
    未選取的一筆未採用；搜尋只命中保存的值。"""
    staged, draft = two_description_draft(client, monkeypatch)
    item_id, created = create_draft_suggestions(client, staged, draft)

    assert client.post(
        f"/api/suggestions/{created[1]}/reject").status_code == 200   # 熱咖啡
    assert client.post(
        f"/api/suggestions/{created[2]}/accept").status_code == 200   # 窗外正在下雨
    assert client.patch(
        f"/api/items/{item_id}", json={"name": "早餐桌", "actor": "user"}
    ).status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"]["description"] == "窗外正在下雨。"
    accepted = [s for s in detail["suggestions"]
                if s["field"] == "attribute:description"
                and s["status"] == "accepted"]
    rejected = [s for s in detail["suggestions"]
                if s["field"] == "attribute:description"
                and s["status"] == "rejected"]
    assert [s["value"] for s in accepted] == ["窗外正在下雨。"]
    assert [s["value"] for s in rejected] == ["桌上有一杯熱咖啡。"]  # AI 原值
    assert accepted[0]["confidence"] == 0.7
    assert accepted[0]["model_name"] == "test/model:free"
    photos = {p["orig_name"]: p["id"] for p in detail["photos"]}
    assert accepted[0]["source_photo_id"] == photos["window.jpg"]

    assert [i["id"] for i in client.get("/api/items?q=正在下雨").json()] == [item_id]
    assert client.get("/api/items?q=熱咖啡").json() == []


def test_all_description_candidates_removed_saves_without_description(
        client, monkeypatch):
    """描述全部移除：兩筆都未採用、正式紀錄沒有 description、沒有值進搜尋；
    紀錄本身照常保存（照片與標題都在）。"""
    staged, draft = two_description_draft(client, monkeypatch)
    item_id, created = create_draft_suggestions(client, staged, draft)

    for index in (1, 2):
        assert client.post(
            f"/api/suggestions/{created[index]}/reject"
        ).status_code == 200
    assert client.patch(
        f"/api/items/{item_id}", json={"name": "早餐桌", "actor": "user"}
    ).status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert "description" not in detail["item"]["attributes"]
    assert detail["item"]["attributes"] == {}
    assert all(
        s["status"] == "rejected"
        for s in detail["suggestions"]
        if s["field"] == "attribute:description"
    )
    assert [s["value"] for s in detail["suggestions"]
            if s["field"] == "attribute:description"] == [
        "桌上有一杯熱咖啡。", "窗外正在下雨。"]
    assert client.get("/api/items?q=熱咖啡").json() == []
    assert client.get("/api/items?q=正在下雨").json() == []
    assert detail["item"]["name"] == "早餐桌"
    assert len(detail["photos"]) == 2
    assert [i["id"] for i in client.get("/api/items?q=早餐桌").json()] == [item_id]


def test_single_description_candidate_flows_without_choice(client, monkeypatch):
    """一般只有一筆描述：不需要選擇，accept 後直接呈現與可搜尋。"""
    install_ai(monkeypatch, [
        {"field": "name", "value": "桌面一角", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "attribute:description", "value": "桌上有一杯咖啡與筆記本。",
         "confidence": 0.8, "source_photo_index": 0},
    ])
    staged, _entries = upload_staged(client, ["desk.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()
    item_id, created = create_draft_suggestions(client, staged, draft)

    for suggestion_id in created:
        assert client.post(
            f"/api/suggestions/{suggestion_id}/accept").status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"]["description"] == "桌上有一杯咖啡與筆記本。"
    assert [i["id"] for i in client.get("/api/items?q=筆記本").json()] == [item_id]


def test_description_reverted_to_original_after_reject_lands_via_patch(client):
    """重試情境：選取的描述先前被改過（建議已 rejected），重試前又改回
    原值 —— accept 已不可能；修正後 capture.js 以 PATCH 讓最終值落地，
    不得停留在先前寫入的修改值。"""
    item_id = _new_item(client)
    suggestion_id = _create_suggestion(
        client, item_id, "attribute:description", "原本的描述")

    # 第一次嘗試：修改 → reject ＋ PATCH 修改值
    assert client.post(
        f"/api/suggestions/{suggestion_id}/reject").status_code == 200
    assert client.patch(
        f"/api/items/{item_id}",
        json={"attributes": {"description": "修改後的描述"}},
    ).status_code == 200
    assert client.get(f"/api/items/{item_id}").json()[
        "item"]["attributes"]["description"] == "修改後的描述"

    # 重試：改回原值 → PATCH 落地（對應 capture.js「已拒絕 → 走 PATCH」）
    current = client.get(f"/api/items/{item_id}").json()["item"]["attributes"]
    merged = {**current, "description": "原本的描述"}
    assert client.patch(
        f"/api/items/{item_id}", json={"attributes": merged}
    ).status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"]["description"] == "原本的描述"
    assert detail["suggestions"][0]["status"] == "rejected"
    assert detail["suggestions"][0]["value"] == "原本的描述"  # AI 原值不受影響
    assert [i["id"] for i in client.get("/api/items?q=原本的描述").json()] == [
        item_id
    ]


def test_switching_choice_after_partial_save_overwrites_cleanly(
        client, monkeypatch):
    """部分保存後改選另一筆：先前已接受的描述被新選取的覆蓋（同一
    attribute key 單鍵合併），兩筆建議歷史都保留 —— 這是修正後
    capture.js 重試流程依賴的後端語意；前端另有 value-aware 清除，
    不會在清理舊值時誤刪剛選取的新描述。"""
    staged, draft = two_description_draft(client, monkeypatch)
    item_id, created = create_draft_suggestions(client, staged, draft)

    # 第一次嘗試：選 A 並接受（部分失敗前的成功步驟）→ 描述＝A
    assert client.post(
        f"/api/suggestions/{created[1]}/accept").status_code == 200
    assert client.get(f"/api/items/{item_id}").json()[
        "item"]["attributes"]["description"] == "桌上有一杯熱咖啡。"

    # 重試前改選 B（A 已是歷史，不可回退）：B accept 覆蓋為最終值
    assert client.post(
        f"/api/suggestions/{created[2]}/accept").status_code == 200

    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["attributes"]["description"] == "窗外正在下雨。"
    descriptions = [s for s in detail["suggestions"]
                    if s["field"] == "attribute:description"]
    assert sorted(s["status"] for s in descriptions) == ["accepted", "accepted"]
    # 舊的 accepted 建議值仍經建議索引可搜尋（既有設計：舊詮釋的詞彙還在）
    assert [i["id"] for i in client.get("/api/items?q=熱咖啡").json()] == [item_id]
    assert [i["id"] for i in client.get("/api/items?q=正在下雨").json()] == [item_id]
