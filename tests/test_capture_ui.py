"""連續拍照批次建檔後端流程測試。

四步端到端流程：
前後清單 + 上傳 + intake → 建立 Item + Observation(kind=intake) → 照片歸檔
"""

from __future__ import annotations

import json


from tests.conftest import make_jpeg


def upload_batch(client, names, *, start_minute=30):
    """模擬整批上傳：multipart 欄位名 files。"""
    files = [
        ("files", (name, make_jpeg(exif=f"2026:10:02 14:{start_minute:02d}:00"),
                   "image/jpeg"))
        for name in names
    ]
    response = client.post("/api/inbox/photos", files=files)
    assert response.status_code == 201, response.text


def inbox_relatives(client):
    return [e["relative"] for e in client.get("/api/inbox").json()["entries"]]


# ----------------------------------------------------------------------
# 後端流程：用真正的 HTTP 走一遍
# ----------------------------------------------------------------------


def test_the_four_step_flow_creates_one_item_with_the_whole_batch(client, config):
    """前後差集流程，端到端驗證。"""
    before = set(inbox_relatives(client))
    assert before == set()

    upload_batch(client, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg",
                          "IMG_4.jpg", "IMG_5.jpg"])

    after = inbox_relatives(client)
    fresh = [relative for relative in after if relative not in before]
    assert len(fresh) == 5

    response = client.post("/api/inbox/intake",
                           json={"files": fresh, "kind": "intake"})
    assert response.status_code == 201, response.text
    done = response.json()

    assert done["item_id"] == "ITM-0001"
    assert done["observation_id"].startswith("OBS-")
    assert len(done["archived"]) == 5

    detail = client.get("/api/items/ITM-0001").json()
    assert len(detail["photos"]) == 5
    assert [o["kind"] for o in detail["observations"]] == ["intake"]
    # 欄位留空，等 AI 建議被接受
    assert detail["item"]["name"] == ""

    # 照片正確保存：files/<item>/original/，inbox 已清空
    folder = config.files_dir / "ITM-0001" / "original"
    assert len(list(folder.iterdir())) == 5
    assert client.get("/api/inbox").json() == {"entries": [], "count": 0}
    for photo in detail["photos"]:
        assert photo["filename"].startswith("files/ITM-0001/original/")
        assert config.resolve(photo["filename"]).exists()


def test_same_filename_collisions_are_all_caught_by_the_diff(client, config):
    """手機常常拍出同名檔案：後端加流水號，差集要全部抓到。"""
    before = set(inbox_relatives(client))
    upload_batch(client, ["IMG_1.jpg", "IMG_1.jpg"])

    after = inbox_relatives(client)
    fresh = [relative for relative in after if relative not in before]
    assert len(fresh) == 2
    assert "inbox/IMG_1.jpg" in fresh
    assert "inbox/IMG_1-2.jpg" in fresh

    done = client.post("/api/inbox/intake",
                       json={"files": fresh, "kind": "intake"}).json()
    assert len(done["archived"]) == 2
    assert len(list((config.files_dir / "ITM-0001" / "original").iterdir())) == 2


def test_upload_only_creates_no_item(client):
    """只上傳（還沒按建檔，或建檔前取消）：沒有 Item、沒有照片列。"""
    upload_batch(client, ["A.jpg", "B.jpg"])
    assert client.get("/api/items").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0


def test_intake_failure_leaves_the_batch_in_the_inbox(client):
    """intake 失敗：照片留在 inbox，使用者回去用既有流程收。"""
    upload_batch(client, ["A.jpg"])
    relatives = inbox_relatives(client)
    response = client.post("/api/inbox/intake",
                           json={"files": relatives, "kind": "return"})
    assert response.status_code == 400
    assert client.get("/api/items").json() == []
    assert inbox_relatives(client) == relatives


def test_the_batch_is_analyzable_by_the_existing_ai_endpoint(
        client, config, monkeypatch):
    """整批照片走既有的 POST /api/items/{id}/ai/analyze：
    結果是 pending 建議，商品欄位不動；接受才寫入。"""
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    upload_batch(client, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"])
    fresh = inbox_relatives(client)
    done = client.post("/api/inbox/intake",
                       json={"files": fresh, "kind": "intake"}).json()
    item_id = done["item_id"]
    assert len(done["archived"]) == 3

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-0000000000",
                                  model="test/model:free"),
    )

    def fake_provider(api_key, model, data_urls, *,
                      provider=None, base_url=None, timeout=None, context=""):
        fake_provider.seen = {"data_urls": len(data_urls),
                               "provider": provider}
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({"suggestions": [
                        {"field": "brand", "value": "ASUS",
                         "confidence": 0.9, "source_photo_index": 0},
                        {"field": "model", "value": "RTX4060",
                         "confidence": 0.8, "source_photo_index": 1},
                    ]}),
                },
            }],
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_provider)

    response = client.post(f"/api/items/{item_id}/ai/analyze")
    assert response.status_code == 201, response.text
    suggestions = response.json()
    assert [s["field"] for s in suggestions] == ["brand", "model"]
    assert all(s["status"] == "pending" for s in suggestions)
    # 三張照片都送進去了
    assert fake_provider.seen["data_urls"] == 3

    # AI 永不直接改商品
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == ""

    # 接受一筆 → 欄位才寫入
    accept = client.post(
        f"/api/suggestions/{suggestions[0]['id']}/accept")
    assert accept.status_code == 200, accept.text
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == "ASUS"


def test_single_photo_flow_still_works(client):
    """原本一張一張拍的流程（選照片 → 分組 → 建檔）不受影響。"""
    files = [("files", ("only.jpg",
                        make_jpeg(exif="2026:10:02 14:30:00"),
                        "image/jpeg"))]
    assert client.post("/api/inbox/photos", files=files).status_code == 201

    groups = client.post("/api/inbox/group?gap_minutes=30").json()
    assert len(groups) == 1
    chosen = [e["relative"] for e in groups[0]["entries"]]

    done = client.post("/api/inbox/intake",
                       json={"files": chosen, "kind": "intake"}).json()
    assert done["item_id"] == "ITM-0001"
    assert len(done["archived"]) == 1
    detail = client.get("/api/items/ITM-0001").json()
    assert len(detail["photos"]) == 1


# ----------------------------------------------------------------------
# 確認儲存才建檔：草稿分析（不建紀錄）＋ 暫存清理 ＋ 存檔時 intake
#
# capture.js 的新流程：上傳 → POST /api/inbox/analyze（草稿，未持久化）
# → 審閱 → 「存起來」才 intake ＋ 建議 ＋ 接受；取消只清 inbox 暫存檔。
# ----------------------------------------------------------------------


def upload_staged(client, names, *, start_minute=30):
    """上傳並回傳 (staged relatives, 全部 inbox relatives)。"""
    files = [
        ("files", (name, make_jpeg(exif=f"2026:10:02 14:{start_minute:02d}:00"),
                   "image/jpeg"))
        for name in names
    ]
    response = client.post("/api/inbox/photos", files=files)
    assert response.status_code == 201, response.text
    body = response.json()
    return body["staged"], [e["relative"] for e in body["entries"]]


def fake_vision(suggestions, store=None):
    def fake(api_key, model, data_urls, *,
             provider=None, base_url=None, timeout=None, context=""):
        if store is not None:
            store["data_urls"] = len(data_urls)
            store["model"] = model
        return {
            "choices": [{
                "message": {"content": json.dumps({"suggestions": suggestions})}
            }],
        }
    return fake


def install_ai(monkeypatch, suggestions, store=None, model="test/model:free"):
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-0000000000", model=model),
    )
    monkeypatch.setattr(ai_client, "call_ai_provider",
                        fake_vision(suggestions, store))


def test_upload_response_reports_which_files_it_staged(client):
    """staged 是這次上傳實際落盤的檔案 —— 取消清理靠它只清自己的暫存。"""
    before = set(inbox_relatives(client))
    staged, entries = upload_staged(client, ["A.jpg", "B.jpg"])
    assert sorted(staged) == sorted(set(entries) - before)
    assert all(relative.startswith("inbox/") for relative in staged)


def test_draft_analysis_creates_nothing(client, config, monkeypatch):
    """草稿分析：AI 結果直接回傳，不建立 Item／photos／suggestions。"""
    seen = {}
    install_ai(monkeypatch, [
        {"field": "name", "value": "SONY A7M4", "confidence": 0.95,
         "source_photo_index": 0},
        {"field": "identifier:serial", "value": "3829104", "confidence": 0.99,
         "source_photo_index": 1},
    ], store=seen)

    staged, _entries = upload_staged(client, ["front.jpg", "label.jpg"])
    response = client.post("/api/inbox/analyze", json={"files": staged})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["model"] == "test/model:free"
    assert [(s["field"], s["value"]) for s in draft["suggestions"]] == [
        ("name", "SONY A7M4"), ("identifier:serial", "3829104")]
    assert draft["suggestions"][1]["source_photo_index"] == 1
    # 草稿沒有 DB 身分（id／status 是正式建議的欄位）
    assert all("id" not in s and "status" not in s for s in draft["suggestions"])
    assert seen["data_urls"] == 2

    # 什麼都沒建立：沒有 Item、沒有照片、暫存檔原封不動
    assert client.get("/api/items").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0
    assert sorted(inbox_relatives(client)) == sorted(staged)


def test_draft_analysis_selection_keeps_submission_order(client, monkeypatch):
    """>8 張觸發「最早 2＋最新 6」選擇；source_photo_index 對應送出順序。

    10 張照片（14:00~14:09）捨去中段 index 2、3；AI 看到的第 4 張
    （選擇順序 index 3）是送出順序的 index 5 —— 草稿必須回送出順序，
    前端才能對回使用者拍攝的那一張。
    """
    seen = {}
    install_ai(monkeypatch, [
        {"field": "identifier:serial", "value": "SN-42", "confidence": 0.9,
         "source_photo_index": 3},
    ], store=seen)

    names = [f"IMG_{i}.jpg" for i in range(10)]
    files = [
        ("files", (name, make_jpeg(exif=f"2026:10:02 14:{i:02d}:00"),
                   "image/jpeg"))
        for i, name in enumerate(names)
    ]
    staged = client.post("/api/inbox/photos", files=files).json()["staged"]
    assert len(staged) == 10

    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()
    assert seen["data_urls"] == 8
    assert draft["suggestions"][0]["source_photo_index"] == 5


def test_draft_analysis_rejects_paths_outside_inbox(client):
    """路徑逃逸與不存在的檔案都要擋（與 intake 同一條 containment 規則）。"""
    assert client.post(
        "/api/inbox/analyze",
        json={"files": ["files/ITM-0001/original/x.jpg"]},
    ).status_code == 400
    assert client.post(
        "/api/inbox/analyze",
        json={"files": ["inbox/../catalog.db"]},
    ).status_code == 400
    assert client.post(
        "/api/inbox/analyze",
        json={"files": ["inbox/nope.jpg"]},
    ).status_code == 404


def test_draft_analysis_failure_does_not_block_save(client, config, monkeypatch):
    """AI 失敗（沒有 key／provider 錯誤）回 400，但使用者照樣可以
    intake ＋ 手動填寫 ＋ 存檔 —— 辨識不完整不得阻止儲存。"""
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-0000000000",
                                 model="test/model:free"),
    )

    def broken_provider(*args, **kwargs):
        raise ai_client.AnalyzerError("provider unreachable")

    monkeypatch.setattr(ai_client, "call_ai_provider", broken_provider)

    staged, _entries = upload_staged(client, ["only.jpg"])
    response = client.post("/api/inbox/analyze", json={"files": staged})
    assert response.status_code == 400
    assert client.get("/api/items").json() == []

    # 手動流程照常：intake → 編輯欄位 → 存檔成功
    done = client.post("/api/inbox/intake",
                       json={"files": staged, "kind": "intake"}).json()
    item_id = done["item_id"]
    patch = client.patch(f"/api/items/{item_id}",
                         json={"name": "手動命名", "actor": "user"})
    assert patch.status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["name"] == "手動命名"
    assert len(detail["photos"]) == 1
    assert config.resolve(detail["photos"][0]["filename"]).exists()


def test_discard_removes_only_requested_staged_files(client, config):
    """取消清理：只刪指定的暫存檔、可重複（冪等）、擋路徑逃逸。"""
    staged, _entries = upload_staged(client, ["A.jpg", "B.jpg"])
    a_relative = [r for r in staged if r.endswith("A.jpg")][0]
    b_relative = [r for r in staged if r.endswith("B.jpg")][0]

    first = client.post("/api/inbox/discard", json={"files": [a_relative]})
    assert first.status_code == 200, first.text
    assert first.json() == {"discarded": [a_relative], "count": 1}
    assert inbox_relatives(client) == [b_relative]
    assert not (config.data_root / a_relative).exists()

    # 冪等：再清一次已不在的檔案不算錯誤
    again = client.post("/api/inbox/discard", json={"files": [a_relative]})
    assert again.status_code == 200
    assert again.json() == {"discarded": [], "count": 0}

    # intake 過的正式照片與 inbox 之外的檔案不可清
    assert client.post(
        "/api/inbox/discard",
        json={"files": ["files/ITM-0001/original/A.jpg"]},
    ).status_code == 400
    assert client.post(
        "/api/inbox/discard",
        json={"files": ["inbox/../config.json"]},
    ).status_code == 400

    final = client.post("/api/inbox/discard", json={"files": [b_relative]})
    assert final.json()["count"] == 1
    assert client.get("/api/inbox").json()["count"] == 0


def test_cancel_after_upload_leaves_no_records_or_files(client, config):
    """取消流程端到端：上傳 →（草稿分析）→ 放棄 → 沒有任何正式紀錄。"""
    staged, _entries = upload_staged(client, ["A.jpg", "B.jpg"])
    # （草稿分析純讀取，這裡直接驗證清理後的狀態）
    assert client.post("/api/inbox/discard", json={"files": staged}).status_code == 200

    assert client.get("/api/items").json() == []
    assert client.get("/api/items?status=void").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0
    assert client.get("/api/inbox").json()["count"] == 0
    created = list((config.files_dir / "ITM-0001").glob("**/*")) if (
        config.files_dir / "ITM-0001").exists() else []
    assert created == []


def test_deferred_save_flow_end_to_end(client, config, monkeypatch):
    """新 capture 流程端到端（對應 capture.js 的請求順序）：

    上傳 → 草稿分析（此時零紀錄）→ 「存起來」intake → 草稿落成正式
    建議（帶 model／來源照片）→ 逐筆接受 → 手動編輯 PATCH → 序號。
    """
    seen = {}
    install_ai(monkeypatch, [
        {"field": "name", "value": "SONY A7M4", "confidence": 0.95,
         "source_photo_index": 0},
        {"field": "brand", "value": "SONY", "confidence": 0.98,
         "source_photo_index": 1},
        {"field": "identifier:serial", "value": "3829104", "confidence": 0.99,
         "source_photo_index": 1},
    ], store=seen)

    # 1. 拍照／選圖 → 上傳 → 草稿分析：此時不能有任何正式紀錄
    staged, _entries = upload_staged(client, ["front.jpg", "label.jpg"])
    draft = client.post("/api/inbox/analyze", json={"files": staged}).json()
    assert client.get("/api/items").json() == []

    # 2. 「✓ 存起來」：這一刻才 intake 建立正式紀錄
    done = client.post("/api/inbox/intake",
                       json={"files": staged, "kind": "intake"}).json()
    item_id = done["item_id"]
    assert item_id == "ITM-0001"
    assert len(done["archived"]) == 2
    # intake 後暫存已消化：inbox 清空，照片在 files/ 下
    assert client.get("/api/inbox").json()["count"] == 0

    # 3. 草稿落成正式建議（前端以 orig_name 對應 archived photos.id）
    photo_id_by_orig_name = {p["orig_name"]: p["id"] for p in done["archived"]}
    created_ids = []
    for suggestion in draft["suggestions"]:
        source_index = suggestion["source_photo_index"]
        response = client.post(
            f"/api/items/{item_id}/suggestions",
            json={
                "field": suggestion["field"],
                "value": suggestion["value"],
                "confidence": suggestion["confidence"],
                "source": "external",
                "model_name": draft["model"],
                "source_photo_id": (
                    photo_id_by_orig_name.get(staged[source_index].split("/")[-1])
                    if source_index is not None else None
                ),
                "actor": "external",
            },
        )
        assert response.status_code == 201, response.text
        created_ids.append(response.json()["id"])

    # 4. 逐筆接受（與現行存檔相同的第二層）
    for suggestion_id in created_ids:
        assert client.post(
            f"/api/suggestions/{suggestion_id}/accept").status_code == 200

    # 5. 驗證：欄位寫入、序號帶來源照片、建議留有完整追溯
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["name"] == "SONY A7M4"
    assert detail["item"]["brand"] == "SONY"
    serial = [i for i in detail["identifiers"] if i["kind"] == "serial"][0]
    assert serial["value"] == "3829104"
    assert serial["source_photo_id"] == photo_id_by_orig_name["label.jpg"]

    suggestions = detail["suggestions"]
    assert all(s["status"] == "accepted" for s in suggestions)
    assert all(s["model_name"] == "test/model:free" for s in suggestions)
    serial_suggestion = [s for s in suggestions
                         if s["field"] == "identifier:serial"][0]
    assert serial_suggestion["source_photo_id"] == photo_id_by_orig_name["label.jpg"]

    # 6. Retrieve：搜尋找得到（核心流程不受影響）
    assert [i["id"] for i in client.get("/api/items?q=3829104").json()] == [item_id]


def test_double_intake_of_same_staged_files_fails_without_duplicates(client):
    """重複點擊／重試的後端防線：staged 已被 intake 消化後，
    再送同一批會 404（檔案已歸檔），不會重複建檔。"""
    staged, _entries = upload_staged(client, ["A.jpg", "B.jpg"])
    first = client.post("/api/inbox/intake",
                        json={"files": staged, "kind": "intake"})
    assert first.status_code == 201

    second = client.post("/api/inbox/intake",
                         json={"files": staged, "kind": "intake"})
    assert second.status_code == 404
    assert len(client.get("/api/items").json()) == 1
    detail = client.get("/api/items/ITM-0001").json()
    assert len(detail["photos"]) == 2
