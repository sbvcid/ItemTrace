"""ItemTrace V3 Core Experience Vertical Slice 驗收測試。

驗證核心產品目標：
  拍照 → AI 幫忙理解/整理 → 使用者幾乎不用輸入 → 存下來 → 之後找得到

涵蓋情境：
1. Web SPA 靜態檔案與客戶端路由回退服務 (Zero-Build ESM)
2. Scenario A：第一次使用 ItemTrace，拍一件東西 → AI 整理 → 1-tap 存起來 → 找得到
3. Scenario B：同一個人再拍第二件東西，不重設分類與結構
4. Scenario C：拍生活隨拍/寵物/風景照片，不被強迫建立 3C 規格欄位，照片安全留存
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import make_jpeg


def test_web_spa_serving_and_routing(client):
    """驗證前端零建置靜態檔案與 SPA 路由回退。"""
    # 1. 首頁回傳 index.html
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert "text/html" in res_home.headers["content-type"]
    assert '<div id="app">' in res_home.text
    assert '<script type="module" src="/app.js">' in res_home.text

    # 2. 靜態資源直出
    res_css = client.get("/app.css")
    assert res_css.status_code == 200
    assert "--color-brand" in res_css.text

    res_js = client.get("/app.js")
    assert res_js.status_code == 200

    res_api_js = client.get("/core/api.js")
    assert res_api_js.status_code == 200
    assert "uploadInboxPhotos" in res_api_js.text

    # i18n 字典與模組直出
    res_i18n_index = client.get("/i18n/index.js")
    assert res_i18n_index.status_code == 200
    assert "initI18n" in res_i18n_index.text

    res_i18n_zh = client.get("/i18n/zh-TW.js")
    assert res_i18n_zh.status_code == 200

    res_i18n_en = client.get("/i18n/en.js")
    assert res_i18n_en.status_code == 200

    # 3. 前端客戶端路由 SPA fallback
    res_capture = client.get("/capture")
    assert res_capture.status_code == 200
    assert '<div id="app">' in res_capture.text

    res_detail = client.get("/i/ITM-0001")
    assert res_detail.status_code == 200
    assert '<div id="app">' in res_detail.text

    # 4. API 不存在的路徑維持 404 JSON，不可被 SPA fallback 攔截
    res_api_404 = client.get("/api/not_exist_endpoint")
    assert res_api_404.status_code == 404
    assert res_api_404.headers["content-type"] == "application/json"


def test_scenario_a_primary_loop(client, config, monkeypatch):
    """Scenario A: 第一次使用 ItemTrace：

    拍照 → AI 自動整理 → 看見 vs 推測 → 一鍵存起來 → 找得到
    """
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    # 1. 拍兩張照片（外觀與標籤）
    files = [
        ("files", ("front.jpg", make_jpeg(exif="2026:10:07 15:00:00"), "image/jpeg")),
        ("files", ("label.jpg", make_jpeg(exif="2026:10:07 15:00:05"), "image/jpeg")),
    ]
    res_upload = client.post("/api/inbox/photos", files=files)
    assert res_upload.status_code == 201
    inbox_files = [e["relative"] for e in res_upload.json()["entries"]]
    assert len(inbox_files) == 2

    # 2. 完成拍照，Intake 入庫
    res_intake = client.post("/api/inbox/intake", json={"files": inbox_files, "kind": "intake"})
    assert res_intake.status_code == 201
    done = res_intake.json()
    item_id = done["item_id"]
    assert item_id == "ITM-0001"
    assert len(done["archived"]) == 2

    # 原始照片不可覆寫且存在磁碟
    for arc in done["archived"]:
        photo_path = config.resolve(arc["filename"])
        assert photo_path.exists()

    # 3. 模擬 AI Vision 模型分析
    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="gemini-2.5-flash"),
    )

    def fake_vision_ai(api_key, model, data_urls, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "suggestions": [
                            {"field": "name", "value": "Sony WH-1000XM5 耳機", "confidence": 0.95, "source_photo_index": 0},
                            {"field": "brand", "value": "Sony", "confidence": 0.98, "source_photo_index": 1},
                            {"field": "model", "value": "WH-1000XM5", "confidence": 0.95, "source_photo_index": 1},
                            {"field": "category", "value": "耳機", "confidence": 0.90, "source_photo_index": 0},
                            {"field": "condition", "value": "黑色，耳罩完好", "confidence": 0.75, "source_photo_index": 0},
                            {"field": "identifier:serial", "value": "5023910", "confidence": 0.99, "source_photo_index": 1},
                        ]
                    })
                }
            }]
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_vision_ai)

    res_ai = client.post(f"/api/items/{item_id}/ai/analyze")
    assert res_ai.status_code == 201
    suggestions = res_ai.json()
    assert len(suggestions) == 6

    # 4. 超低摩擦主管確認：「✓ 存起來」
    for s in suggestions:
        res_accept = client.post(f"/api/suggestions/{s['id']}/accept")
        assert res_accept.status_code == 200

    # 5. 驗證資料已寫入 Item 與 Identifiers
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["name"] == "Sony WH-1000XM5 耳機"
    assert detail["item"]["brand"] == "Sony"
    assert detail["item"]["model"] == "WH-1000XM5"
    assert detail["item"]["category"] == "耳機"
    assert detail["item"]["condition"] == "黑色，耳罩完好"

    serials = [i["value"] for i in detail["identifiers"] if i["kind"] == "serial"]
    assert "5023910" in serials

    # 6. Retrieve 驗證：名稱、品牌、型號、半截序號皆能秒級找回
    # 搜尋「Sony」
    res_search_brand = client.get("/api/items?q=Sony").json()
    assert len(res_search_brand) == 1
    assert res_search_brand[0]["id"] == item_id

    # 搜尋「1000XM5」
    res_search_model = client.get("/api/items?q=1000XM5").json()
    assert len(res_search_model) == 1
    assert res_search_model[0]["id"] == item_id

    # 搜尋半截序號「23910」
    res_search_serial = client.get("/api/items?q=23910").json()
    assert len(res_search_serial) == 1
    assert res_search_serial[0]["id"] == item_id


def test_scenario_b_second_item_capture(client, config, monkeypatch):
    """Scenario B: 同一個人先拍第一件，再拍第二件東西，不需預先建立結構或選資料夾。"""
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="gemini-2.5-flash"),
    )

    def fake_vision_tool(api_key, model, data_urls, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "suggestions": [
                            {"field": "name", "value": "牧田 18V 震動電鑽", "confidence": 0.95, "source_photo_index": 0},
                            {"field": "brand", "value": "Makita", "confidence": 0.95, "source_photo_index": 0},
                            {"field": "model", "value": "DHP484Z", "confidence": 0.90, "source_photo_index": 0},
                            {"field": "category", "value": "工具", "confidence": 0.90, "source_photo_index": 0},
                        ]
                    })
                }
            }]
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_vision_tool)

    # 1. 拍第一件物品
    f1 = [("files", ("item1.jpg", make_jpeg(exif="2026:10:07 15:00:00"), "image/jpeg"))]
    u1 = client.post("/api/inbox/photos", files=f1).json()
    i1 = client.post("/api/inbox/intake", json={"files": [u1["entries"][0]["relative"]]}).json()
    client.patch(f"/api/items/{i1['item_id']}", json={"name": "第一件物品"})

    # 2. 隨手拍第二件（電鑽）
    f2 = [("files", ("drill.jpg", make_jpeg(exif="2026:10:07 15:10:00"), "image/jpeg"))]
    upload_res = client.post("/api/inbox/photos", files=f2).json()
    intake_res = client.post("/api/inbox/intake", json={"files": [upload_res["entries"][0]["relative"]]}).json()
    second_id = intake_res["item_id"]

    # AI 整理
    suggestions = client.post(f"/api/items/{second_id}/ai/analyze").json()
    for s in suggestions:
        client.post(f"/api/suggestions/{s['id']}/accept")

    # 驗證列表同時包含新舊兩件物品
    all_items = client.get("/api/items").json()
    assert len(all_items) == 2
    found_drill = [i for i in all_items if i["id"] == second_id][0]
    assert found_drill["name"] == "牧田 18V 震動電鑽"
    assert found_drill["brand"] == "Makita"


def test_scenario_c_non_item_photo_handling(client, config, monkeypatch):
    """Scenario C: 拍寵物/生活隨拍/風景照片：

    不被強迫填寫 3C 規格欄位；AI 無建議時照片依舊安全保存，使用者可自訂名稱存下。
    """
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="gemini-2.5-flash"),
    )

    # AI 沒有辨識出任何特定硬體欄位（回傳空陣列）
    monkeypatch.setattr(
        ai_client, "call_ai_provider",
        lambda *a, **k: {
            "choices": [{
                "message": {"content": json.dumps({"suggestions": []})}
            }]
        }
    )

    # 使用者拍了一隻貓
    files = [("files", ("cat.jpg", make_jpeg(exif="2026:10:07 15:20:00"), "image/jpeg"))]
    upload_res = client.post("/api/inbox/photos", files=files).json()
    intake_res = client.post("/api/inbox/intake", json={"files": [upload_res["entries"][0]["relative"]]}).json()
    cat_id = intake_res["item_id"]

    # AI 跑完回傳 0 筆建議
    suggestions = client.post(f"/api/items/{cat_id}/ai/analyze").json()
    assert len(suggestions) == 0

    # 使用者點擊「存起來」（手動指定標題或留空）
    client.patch(f"/api/items/{cat_id}", json={"name": "可愛橘貓", "category": "生活隨拍"})

    # 驗證紀錄已保存，且品牌/型號皆為空，完全不報錯
    detail = client.get(f"/api/items/{cat_id}").json()
    assert detail["item"]["name"] == "可愛橘貓"
    assert detail["item"]["brand"] == ""
    assert detail["item"]["model"] == ""
    assert len(detail["photos"]) == 1

    # 搜尋「橘貓」可以找回
    search_res = client.get("/api/items?q=橘貓").json()
    assert len(search_res) == 1
    assert search_res[0]["id"] == cat_id


def test_photo_serving_and_byte_preservation(client, config):
    """P0 驗收測試：相片上傳、歸檔、URL 解析與原始位元保存。

    驗證：
    1. 上傳原檔 byte-for-byte 保存，無損無壓縮
    2. API 回傳之 photo.filename 與 item.thumbnail 可成功被 GET 存取
    3. 前端標準路徑 /files/ITM-xxxx/... 與相容路徑 /files/files/... 皆回傳 200
    4. 回傳之 Content-Type 為正確的 image/jpeg
    5. 回傳之 body 與原始檔案完全一致（byte-for-byte）
    """
    raw_data = make_jpeg(exif="2026:10:07 16:30:00")
    files = [("files", ("test_sample.jpg", raw_data, "image/jpeg"))]

    # 上傳至 Inbox
    upload_res = client.post("/api/inbox/photos", files=files).json()
    inbox_relative = upload_res["entries"][0]["relative"]

    # 驗證 inbox 檔案可直接透過 /files/inbox/... 預覽
    inbox_view = client.get(f"/files/{inbox_relative}")
    assert inbox_view.status_code == 200
    assert inbox_view.content == raw_data
    assert inbox_view.headers["content-type"].startswith("image/jpeg")

    # 執行 Intake 歸檔
    intake_res = client.post("/api/inbox/intake", json={"files": [inbox_relative]}).json()
    item_id = intake_res["item_id"]
    photo_filename = intake_res["archived"][0]["filename"]

    # 取得商品詳細資訊與縮圖
    detail = client.get(f"/api/items/{item_id}").json()
    assert len(detail["photos"]) == 1
    photo = detail["photos"][0]
    assert photo["filename"] == photo_filename

    item_summary = client.get("/api/items").json()[0]
    assert item_summary["thumbnail"] == photo_filename

    # 1. 前端常用直覺路徑: /{photo.filename} -> /files/ITM-xxxx/original/...
    res_direct = client.get(f"/{photo['filename']}")
    assert res_direct.status_code == 200
    assert res_direct.headers["content-type"].startswith("image/jpeg")
    assert res_direct.content == raw_data, "照片內容必須與原始上傳 byte-for-byte 完全一致！"

    # 2. 縮圖路徑: /{thumbnail}
    res_thumb = client.get(f"/{item_summary['thumbnail']}")
    assert res_thumb.status_code == 200
    assert res_thumb.content == raw_data

    # 3. 舊式相容路徑: /files/{photo.filename} -> /files/files/ITM-xxxx/...
    res_legacy = client.get(f"/files/{photo['filename']}")
    assert res_legacy.status_code == 200
    assert res_legacy.content == raw_data

    # 4. 驗證 Cache-Control 標頭存在以加速瀏覽器重複顯示
    assert "public" in res_direct.headers.get("cache-control", "")
