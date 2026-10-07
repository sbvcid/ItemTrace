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
                      provider=None, base_url=None, timeout=None):
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
