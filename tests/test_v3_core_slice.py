"""ItemTrace V3 Core Experience Vertical Slice 驗收測試。

驗證核心產品目標：
  拍照 → AI 幫忙理解/整理 → 使用者幾乎不用輸入 → 存下來 → 之後找得到

涵蓋情境：
1. Web SPA 靜態檔案與客戶端路由回退服務 (Zero-Build ESM)
2. Scenario A：第一次使用 ItemTrace，拍一件東西 → AI 整理 → 1-tap 存起來 → 找得到
3. Scenario B：同一個人再拍第二件東西，不重設分類與結構
4. Scenario C：拍生活隨拍/寵物/風景照片，不被強迫建立 3C 規格欄位，照片安全留存
5. Phase 1B-A：首頁最新紀錄置頂、保存後回首頁、修改不亂序、搜尋不受影響
6. Phase 2A：capture 部分失敗語意（靜態接線檢查；非瀏覽器端對端測試）
7. Phase 2B：證據累積——補照片到既有紀錄、情境式重新理解、更新後仍可搜尋
8. Phase 2C-B：證據選擇、可回復的自動套用、衝突升級（含紀錄回放）
9. Phase 2C-D：過期 undo 防護與修訂顯示（含靜態檢查）
10. Phase 2 修正回歸：序號來源照片對應（photos.id 契約）與
    編輯／儲存／取消操作語意
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

    # 4. 驗證 Cache-Control 標頭存在以加速瀏覽器重複顯示；
    #    SR-2（F7）：照片是私人資料，語義是 private（不進共享快取）。
    cache_control = res_direct.headers.get("cache-control", "")
    assert "private" in cache_control
    assert "max-age" in cache_control


# ----------------------------------------------------------------------
# Phase 1B-A：首頁基本流程（最新置頂、保存後回首頁、搜尋不受影響）
# ----------------------------------------------------------------------


def test_phase1b_home_lists_newest_first(client):
    """首頁預設順序：建立時間由新到舊。"""
    for name in ("第一件", "第二件", "第三件"):
        assert client.post("/api/items", json={"name": name}).status_code == 201

    listed = client.get("/api/items").json()
    assert [item["id"] for item in listed] == ["ITM-0003", "ITM-0002", "ITM-0001"]


def test_phase1b_patching_old_item_keeps_creation_order(client):
    """修改舊紀錄後，它不會跳到最前面（排序看 created_at 而非 updated_at）。"""
    for name in ("第一件", "第二件", "第三件"):
        client.post("/api/items", json={"name": name})

    res = client.patch("/api/items/ITM-0001", json={"name": "第一件（改名）"})
    assert res.status_code == 200

    listed = client.get("/api/items").json()
    assert [item["id"] for item in listed] == ["ITM-0003", "ITM-0002", "ITM-0001"]
    assert listed[-1]["name"] == "第一件（改名）"


def test_phase1b_saved_capture_lands_first_on_home(client, config, monkeypatch):
    """保存成功後回首頁：剛剛存下的紀錄出現在第一筆，帶著縮圖與照片數。"""
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="gemini-2.5-flash"),
    )

    def fake_vision_ai(api_key, model, data_urls, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({"suggestions": [
                        {"field": "name", "value": "牧田 18V 震動電鑽",
                         "confidence": 0.95, "source_photo_index": 0},
                    ]})
                }
            }]
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_vision_ai)

    def capture_and_save(filename):
        """走與前端 Capture 相同的一條龍：上傳 → intake → AI → 接受建議。"""
        files = [("files", (filename, make_jpeg(exif="2026:10:07 15:00:00"),
                            "image/jpeg"))]
        upload = client.post("/api/inbox/photos", files=files).json()
        intake = client.post("/api/inbox/intake", json={
            "files": [upload["entries"][0]["relative"]], "kind": "intake",
        }).json()
        item_id = intake["item_id"]
        for s in client.post(f"/api/items/{item_id}/ai/analyze").json():
            assert client.post(f"/api/suggestions/{s['id']}/accept").status_code == 200
        return item_id

    first_id = capture_and_save("first.jpg")
    second_id = capture_and_save("second.jpg")

    home = client.get("/api/items").json()
    assert home[0]["id"] == second_id          # 最新保存的在第一個位置
    assert home[1]["id"] == first_id
    assert home[0]["name"] == "牧田 18V 震動電鑽"
    assert home[0]["thumbnail"] is not None
    assert home[0]["photo_count"] == 1


def test_phase1b_search_results_stay_correct(client):
    """首頁排序調整不影響搜尋正確性：命中的紀錄正確、仍由新到舊。"""
    client.post("/api/items", json={"name": "RTX 4070 顯示卡", "brand": "ASUS"})
    client.post("/api/items", json={"name": "RTX 4070 Ti 顯示卡", "brand": "MSI"})
    client.post("/api/items", json={"name": "機械鍵盤", "brand": "Logitech"})

    found = client.get("/api/items?q=4070").json()
    assert [item["id"] for item in found] == ["ITM-0002", "ITM-0001"]
    assert all("4070" in item["name"] for item in found)

    assert client.get("/api/items?q=不存在的字串").json() == []


def test_phase1b_frontend_wiring_static_checks(client):
    """Phase 1B-A 前端接線的靜態原始碼檢查。

    注意：這是對服務出的 JavaScript/CSS 文字做字串檢查，
    不是瀏覽器端對端測試。實際的點擊、導覽與視覺呈現未在此驗證。
    """
    # Capture：保存成功後回首頁並帶上 fresh 參照；不再直達詳細頁。
    capture_js = client.get("/views/capture.js").text
    assert "router.navigate(`/?fresh=${currentItemId}`)" in capture_js
    assert "/i/${currentItemId}" not in capture_js

    # Home：讀取 fresh 參照、最新卡片放大、剛存入的卡片高亮。
    home_js = client.get("/views/home.js").text
    assert "URLSearchParams(window.location.search).get('fresh')" in home_js
    assert "record-card-featured" in home_js
    assert "record-card-fresh" in home_js
    assert "record-fresh-badge" in home_js

    # CSS 與 i18n：呈現樣式與文字標籤（非只靠顏色）皆存在。
    css = client.get("/app.css").text
    assert ".record-card-featured" in css
    assert ".record-card-fresh" in css
    assert "@keyframes fresh-record-glow" in css

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("freshBadge", "latestBadge"):
        assert key in zh
        assert key in en


def test_phase2a_capture_partial_failure_static_checks(client):
    """Phase 2A 前端接線靜態檢查（非瀏覽器端對端測試）：

    accept 失敗不再被靜默吞掉；已套用的操作會被記住，
    讓重試不會重複套用；部分失敗有專屬訊息而非假裝全部成功。
    保存一致性（後續強化）：被拒絕的建議與需要真刪除的識別碼
    都有追蹤狀態，重試時不會把使用者移除的值留下或復活。
    """
    capture_js = client.get("/views/capture.js").text
    assert "appliedSuggestionIds" in capture_js
    assert "rejectedSuggestionIds" in capture_js
    assert "identifierDeletes" in capture_js
    assert "savePartial" in capture_js
    assert "failures.push" in capture_js

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    assert "savePartial" in zh
    assert "savePartial" in en


# ----------------------------------------------------------------------
# Phase 2B：證據累積與情境式重新理解（驗收情境）
# ----------------------------------------------------------------------


def test_phase2b_evidence_accumulation_scenario(client, config, monkeypatch):
    """陌生對象 → 幾天後補收據 → 同一筆紀錄被重新理解（完整驗收情境）。

    1. 拍下不認識的東西並存起來（AI 不認識 → 使用者手動命名）
    2. 補上收據照片（加在同一筆紀錄，不是新紀錄）
    3. AI 用「既有資訊 + 新證據」重新理解
    4. 使用者確認後同一筆紀錄更新（id / created_at / 原照片都不變，
       使用者備註不被覆蓋）
    5. 新的描述與屬性可被搜尋（沿用既有 LIKE 搜尋）
    """
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="test/model:free"),
    )

    calls = []

    def fake_vision(api_key, model, data_urls, *, provider=None, base_url=None,
                    timeout=None, context=""):
        calls.append({"photos": len(data_urls), "context": context})
        if len(calls) == 1:
            content = json.dumps({"suggestions": []})
        else:
            content = json.dumps({"suggestions": [
                {"field": "name", "value": "牧田 18V 震動電鑽",
                 "confidence": 0.9, "source_photo_index": 1},
                {"field": "attribute:vendor", "value": "光華商場",
                 "confidence": 0.8, "source_photo_index": 1},
                {"field": "attribute:description", "value": "附購買收據的 18V 電鑽",
                 "confidence": 0.75, "source_photo_index": 1},
            ]})
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_vision)

    # 1. 拍下陌生的東西並存在一筆紀錄裡
    files = [("files", ("unknown.jpg", make_jpeg(exif="2026:10:01 10:00:00"),
                        "image/jpeg"))]
    upload = client.post("/api/inbox/photos", files=files).json()
    intake = client.post("/api/inbox/intake", json={
        "files": [upload["entries"][0]["relative"]], "kind": "intake",
    }).json()
    item_id = intake["item_id"]
    assert client.post(f"/api/items/{item_id}/ai/analyze").status_code == 201
    client.patch(f"/api/items/{item_id}", json={
        "name": "不明金屬零件", "notes": "五金行買的，忘了名字",
    })
    before = client.get(f"/api/items/{item_id}").json()["item"]

    # 2. 幾天後拿到收據，加到同一筆紀錄
    observation = client.post(
        f"/api/items/{item_id}/observations", json={"kind": "recheck"}
    ).json()
    uploaded = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[("files", ("receipt.jpg", make_jpeg(exif="2026:10:05 12:00:00"),
                          "image/jpeg"))],
    )
    assert uploaded.status_code == 201
    assert len(uploaded.json()["archived"]) == 1
    assert len(client.get("/api/items").json()) == 1     # 沒有多出一筆紀錄

    # 3. 情境式重新理解：新證據與既有資訊一起送
    suggestions = client.post(f"/api/items/{item_id}/ai/analyze").json()
    assert calls[-1]["photos"] == 2
    assert "不明金屬零件" in calls[-1]["context"]
    assert "五金行買的，忘了名字" in calls[-1]["context"]

    # 4. 使用者確認前主表不變；確認後同一筆紀錄更新
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["name"] == "不明金屬零件"
    for suggestion in suggestions:
        assert client.post(
            f"/api/suggestions/{suggestion['id']}/accept"
        ).status_code == 200

    after = client.get(f"/api/items/{item_id}").json()
    assert after["item"]["id"] == before["id"]
    assert after["item"]["created_at"] == before["created_at"]
    assert after["item"]["name"] == "牧田 18V 震動電鑽"
    assert after["item"]["attributes"]["vendor"] == "光華商場"
    assert after["item"]["notes"] == "五金行買的，忘了名字"   # 使用者備註未被覆蓋
    assert len(after["photos"]) == 2                         # 全部照片都在

    # 5. 更新後仍找得到：新名稱、屬性值、描述都進既有 LIKE 搜尋
    assert [i["id"] for i in client.get("/api/items?q=牧田").json()] == [item_id]
    assert [i["id"] for i in client.get("/api/items?q=光華商場").json()] == [item_id]
    assert [i["id"] for i in client.get("/api/items?q=收據").json()] == [item_id]


def test_phase2b_detail_evidence_wiring_static_checks(client):
    """Phase 2B 前端接線靜態檢查（非瀏覽器端對端測試）：

    detail 頁能加照片、觸發情境式重新分析、呈現待確認建議；
    失敗時有明確的重試訊息；屬性有呈現區塊。
    """
    detail_js = client.get("/views/record-detail.js").text
    assert "createObservation" in detail_js
    assert "uploadObservationPhotos" in detail_js
    assert "performAnalysis" in detail_js
    assert "analysisFailed" in detail_js
    assert "acceptSuggestion" in detail_js
    assert "rejectSuggestion" in detail_js
    assert "attributesTitle" in detail_js

    api_js = client.get("/core/api.js").text
    assert "uploadObservationPhotos" in api_js
    assert "rejectSuggestion" in api_js

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("addPhoto", "reanalyze", "analysisFailed", "analysisRetry",
                "pendingTitle", "applyAll", "attributesTitle"):
        assert key in zh
        assert key in en


def test_phase2c_b_detail_autonomy_static_checks(client):
    """Phase 2C-B 前端接線靜態檢查（非瀏覽器端對端測試）：

    detail 頁以 auto=1 觸發分析、顯示「已自動更新＋復原」、
    衝突列有標示與來源照片編號；api.js 有 undo 與 auto 參數。
    """
    detail_js = client.get("/views/record-detail.js").text
    assert "api.analyzeItem(itemId, { auto: true })" in detail_js
    assert "analysisApplied" in detail_js
    assert "undoSuggestion" in detail_js
    assert "external_conflict" in detail_js
    assert "conflictNote" in detail_js

    api_js = client.get("/core/api.js").text
    assert "?auto=1" in api_js
    assert "undoSuggestion" in api_js

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("analysisApplied", "undo", "undoDone", "undoFailed",
                "conflictNote"):
        assert key in zh
        assert key in en


def test_phase2c_d_undo_guard_and_revisions_static_checks(client):
    """Phase 2C-D 前端接線靜態檢查（非瀏覽器端對端測試）：

    詳情頁在自動更新 banner 顯示修訂前後值；過期復原逐項說明。
    """
    detail_js = client.get("/views/record-detail.js").text
    assert "buildRevisionDetails" in detail_js
    assert "revisionChanged" in detail_js
    assert "revisionFilled" in detail_js
    assert "undoStale" in detail_js

    api_js = client.get("/core/api.js").text
    assert "listEvents" in api_js

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("revisionChanged", "revisionFilled", "undoStale"):
        assert key in zh
        assert key in en


# ----------------------------------------------------------------------
# Phase 2 修正回歸：序號來源照片對應 與 編輯／儲存／取消語意
# ----------------------------------------------------------------------


def test_serial_source_photo_id_maps_to_real_photo_content(
        client, monkeypatch):
    """回歸（序號來源照片對應）：source_photo_id 是 photos.id 外鍵。

    資料契約（shop/schema.sql）：suggestions.source_photo_id
    REFERENCES photos(id) —— 是真實照片 ID，不是任何合成格式。
    本測試鎖住前端序號查閱視窗依賴的整條對應鏈：
      AI 宣稱序號讀自第 N 張 → suggestion.source_photo_id == 該張照片 ID
      → 該 ID 的照片檔案經 HTTP 直出的內容 == 那張照片的原始位元。
    多張照片時，不同欄位的來源 ID 必須指向不同照片、不同內容；
    不得一律落在第一張。
    """
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    front_bytes = make_jpeg(exif="2026:10:07 15:00:00")
    label_bytes = make_jpeg(exif="2026:10:07 15:00:05")
    assert front_bytes != label_bytes, "兩張照片必須可以位元層級分辨"

    # 拍兩張照片：第 0 張外觀照、第 1 張標籤（序號）照
    upload = client.post("/api/inbox/photos", files=[
        ("files", ("front.jpg", front_bytes, "image/jpeg")),
        ("files", ("label.jpg", label_bytes, "image/jpeg")),
    ])
    assert upload.status_code == 201
    relatives = [e["relative"] for e in upload.json()["entries"]]
    done = client.post(
        "/api/inbox/intake", json={"files": relatives, "kind": "intake"}
    ).json()
    item_id = done["item_id"]
    assert len(done["archived"]) == 2

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-key", model="gemini-2.5-flash"),
    )

    def fake_vision_ai(api_key, model, data_urls, **kwargs):
        # 名稱讀自第 0 張；序號讀自第 1 張（標籤照）。
        return {"choices": [{"message": {"content": json.dumps({
            "suggestions": [
                {"field": "name", "value": "Sony WH-1000XM5",
                 "confidence": 0.95, "source_photo_index": 0},
                {"field": "identifier:serial", "value": "5023910",
                 "confidence": 0.99, "source_photo_index": 1},
            ],
        })}}]}

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_vision_ai)

    suggestions = client.post(f"/api/items/{item_id}/ai/analyze").json()
    by_field = {s["field"]: s for s in suggestions}
    serial_source = by_field["identifier:serial"]["source_photo_id"]
    name_source = by_field["name"]["source_photo_id"]

    detail = client.get(f"/api/items/{item_id}").json()
    photos = detail["photos"]
    assert len(photos) == 2
    photo_by_id = {p["id"]: p for p in photos}

    # 來源必須是這批照片的真實 ID，且兩個欄位指向不同照片
    assert serial_source in photo_by_id
    assert name_source in photo_by_id
    assert serial_source != name_source

    # 序號來源照片直出的內容必須就是第 1 張（標籤照）的原始位元 ——
    # 前端按 ID 查到的 URL 顯示的正是真正的來源照片。
    served_serial = client.get(f"/{photo_by_id[serial_source]['filename']}")
    assert served_serial.status_code == 200
    assert served_serial.content == label_bytes

    # 對照組：名稱欄位的來源照片就是另一張（外觀照）
    served_name = client.get(f"/{photo_by_id[name_source]['filename']}")
    assert served_name.content == front_bytes


def test_capture_serial_inspect_uses_backend_photo_id_mapping(client):
    """回歸（序號來源照片對應）前端接線靜態檢查（非瀏覽器端對端測試）：

    審閱階段的序號查閱以草稿的 source_photo_index 對應本機拍攝順序
    （photoUrlById：index → blob URL），查不到才退回第一張；
    存檔時以 intake 回傳的 archived（orig_name → photos.id）把來源
    照片寫進正式建議。不得再自行解析合成 ID 格式。
    """
    capture_js = client.get("/views/capture.js").text

    # 審閱：草稿索引 → 本機 blob URL 的對應
    assert "photoUrlById" in capture_js
    assert "photoUrlById = new Map(capturedFiles.map((c, i) => [i, c.url]))" in capture_js

    # 序號查閱：以草稿索引（識別碼列自己的 sourcePhotoIndex）查對應；
    # 退回第一張只是 fallback
    assert "photoUrlById.get(row.sourcePhotoIndex)" in capture_js
    assert "capturedFiles[0]?.url" in capture_js

    # 存檔：以 intake 的 archived（PhotoOut：id + orig_name）建立正式來源對應
    assert "intakeRes.archived" in capture_js
    assert "archivedIdByOrigName" in capture_js

    # 舊的錯誤假設（合成格式 "observation:...:photo:N" 解析）必須消失
    assert "observation:" not in capture_js
    assert "match(/photo:" not in capture_js


def test_capture_deferred_save_wiring_static_checks(client):
    """回歸（確認儲存才建檔）前端接線靜態檢查（非瀏覽器端對端測試）：

    capture 審閱階段只做草稿分析（POST /api/inbox/analyze，不建紀錄）；
    正式 intake 只出現在「存起來」處理器，重試不重複 intake；
    AI 草稿在存檔時落成正式建議（POST /api/items/{id}/suggestions）；
    取消清理暫存（POST /api/inbox/discard），已建檔後放棄走 void + purge。
    """
    capture_js = client.get("/views/capture.js").text
    api_js = client.get("/core/api.js").text

    # 審閱階段：草稿分析；不得再對「還不存在的紀錄」呼叫 analyze
    assert "api.analyzeDraft(" in capture_js
    assert "api.analyzeItem(" not in capture_js
    assert capture_js.index("api.analyzeDraft(") < capture_js.index(
        "btnSaveConfirm.addEventListener")

    # 「存起來」處理器才出現正式建檔與建議套用，且 intake 只跑一次
    save_marker = capture_js.index("btnSaveConfirm.addEventListener")
    assert capture_js.index("api.intake(") > save_marker
    assert "if (!currentItemId) {" in capture_js
    assert "api.createSuggestion(" in capture_js
    assert "api.acceptSuggestion(" in capture_js
    assert capture_js.index("api.createSuggestion(") > save_marker

    # 取消：清暫存；已建檔後放棄走 void + purge（限本次建立的紀錄）
    cancel_marker = capture_js.index("btnCancelDraft.addEventListener")
    assert "discardStagedFiles()" in capture_js
    assert "api.voidItem(" in capture_js
    assert "api.purgeItem(" in capture_js
    assert capture_js.index("api.purgeItem(") > cancel_marker

    # 離開頁面也清掉未消化的暫存（最後一次呼叫在 destroy 內）
    destroy_marker = capture_js.index("destroy() {")
    assert capture_js.rindex("discardStagedFiles()") > destroy_marker

    # api.js 具備三個新方法
    assert "api/inbox/analyze" in api_js
    assert "api/inbox/discard" in api_js
    assert "/suggestions" in api_js

    # 雙語鍵齊全
    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("discardDone", "discardFailed"):
        assert key in zh
        assert key in en


def test_record_detail_edit_save_cancel_semantics(client):
    """回歸（編輯介面操作語意）前端接線靜態檢查（非瀏覽器端對端測試）：

    詳情頁編輯介面必須明確區分進入編輯、儲存、取消：
    - 工具列按鈕只負責進入編輯；不得顯示「確認」卻只關閉表單
    - 表單有明確的儲存與取消按鈕；取消不送任何請求
    - 儲存成功：離開編輯模式並重新載入最新資料
    - 儲存失敗或沒有變更：表單留在編輯模式，使用者輸入保留可直接重試
    """
    detail_js = client.get("/views/record-detail.js").text

    # 工具列不再出現「確認」；進入編輯時工具列按鈕藏起來，由表單接手
    assert "app.confirm" not in detail_js
    assert "isEditMode = !isEditMode" not in detail_js
    assert "editToggleBtn.style.display = 'none'" in detail_js

    # 表單自己的儲存與取消按鈕
    assert 'id="btn-save-edits"' in detail_js
    assert 'id="btn-cancel-edits"' in detail_js

    save_body = _js_function_body(detail_js, "async function saveEdits")
    cancel_body = _js_function_body(detail_js, "function cancelEdits")

    # 取消：不送任何請求（無任何 api.* 呼叫），直接離開編輯模式
    assert "api." not in cancel_body
    assert "exitEditMode()" in cancel_body

    # 儲存：PATCH 成功後先離開編輯模式、再重新載入最新資料
    patch_at = save_body.index("await api.patchItem")
    exit_at = save_body.index("exitEditMode()")
    reload_at = save_body.index("await loadDetail()")
    assert patch_at < exit_at < reload_at

    # 儲存失敗（catch）：不得關閉表單 —— 使用者輸入保留，可直接重試
    catch_start = save_body.index("} catch (err) {")
    catch_body = save_body[catch_start:save_body.index("} finally {", catch_start)]
    assert "exitEditMode" not in catch_body
    assert "hidden" not in catch_body

    # 沒有變更：留在編輯模式（不得趁機關閉表單）
    no_changes_at = save_body.index("noChanges")
    assert no_changes_at < patch_at

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("modify:", "modifyTitle:", "saveDone:", "saveError:", "noChanges:",
                "save:", "cancel:"):
        assert key in zh
        assert key in en


# ----------------------------------------------------------------------
# Phase 3：垃圾桶與永久刪除（驗收情境 + 前端接線靜態檢查）
# ----------------------------------------------------------------------


def test_phase3_trash_flow_end_to_end(client, config):
    """完整走一遍：移至垃圾桶 → 首頁/搜尋消失 → 垃圾桶可見（帶縮圖）→
    還原回原狀態 → 再移入 → 永久刪除（紀錄與照片檔案都真的消失）。"""
    upload = client.post("/api/inbox/photos", files=[
        ("files", ("trash.jpg", make_jpeg(exif="2026:10:11 09:00:00"), "image/jpeg")),
    ]).json()
    intake = client.post("/api/inbox/intake", json={
        "files": [upload["entries"][0]["relative"]], "kind": "intake",
    }).json()
    item_id = intake["item_id"]
    photo_path = config.resolve(intake["archived"][0]["filename"])
    client.patch(f"/api/items/{item_id}", json={"name": "不要了的東西"})

    # 1. 移至垃圾桶：首頁與一般搜尋看不到，垃圾桶看得到（含縮圖）
    assert client.post(f"/api/items/{item_id}/void").status_code == 200
    assert client.get("/api/items").json() == []
    assert client.get("/api/items?q=不要了").json() == []
    trash = client.get("/api/items?status=void").json()
    assert trash[0]["id"] == item_id
    assert trash[0]["thumbnail"] is not None

    # 2. 還原：重新出現在一般列表與搜尋結果
    restored = client.post(f"/api/items/{item_id}/restore")
    assert restored.json()["status"] == "active"
    assert client.get("/api/items?q=不要了").json()[0]["id"] == item_id

    # 3. 再次移入垃圾桶後永久刪除：不可逆的完整清除
    client.post(f"/api/items/{item_id}/void")
    response = client.delete(f"/api/items/{item_id}")
    assert response.status_code == 200
    assert not photo_path.exists()
    assert not (config.files_dir / item_id).exists()
    assert client.get("/api/items").json() == []
    assert client.get("/api/items?status=void").json() == []
    assert client.get(f"/api/items/{item_id}").status_code == 404


def test_phase3_trash_frontend_wiring_static_checks(client):
    """Phase 3 前端接線靜態檢查（非瀏覽器端對端測試）：

    垃圾桶頁面、詳情頁「移至垃圾桶」、首頁垃圾桶入口、路由、api.js
    與雙語 i18n 鍵都存在；永久刪除有二次確認與備份快照說明。
    """
    # 垃圾桶頁面本身可被 SPA 路由回退服務
    res_trash = client.get("/trash")
    assert res_trash.status_code == 200
    assert '<div id="app">' in res_trash.text

    trash_js = client.get("/views/trash.js").text
    assert "listTrashItems" in trash_js
    assert "restoreItem" in trash_js
    assert "purgeItem" in trash_js
    assert "window.confirm" in trash_js           # 永久刪除的二次確認

    detail_js = client.get("/views/record-detail.js").text
    assert "btn-move-trash" in detail_js
    assert "api.voidItem" in detail_js
    assert "trashConfirm" in detail_js            # 移入前的說明性確認

    home_js = client.get("/views/home.js").text
    assert 'href="/trash"' in home_js             # 首頁容易找到的入口

    app_js = client.get("/app.js").text
    assert "createTrashView" in app_js
    assert ".add('/trash', createTrashView)" in app_js

    api_js = client.get("/core/api.js").text
    for call in ("voidItem", "restoreItem", "purgeItem", "listTrashItems"):
        assert call in api_js

    css = client.get("/app.css").text
    assert ".trash-item" in css
    assert ".btn-mini-danger" in css

    zh = client.get("/i18n/zh-TW.js").text
    en = client.get("/i18n/en.js").text
    for key in ("trashConfirm", "moveToTrash", "purgeConfirm", "restore",
                "emptyTitle", "purgeDone"):
        assert key in zh
        assert key in en
    # 永久刪除的訊息必須說明「備份快照不會被自動清除」
    assert "備份快照" in zh
    assert "backup snapshot" in en


def _js_function_body(source: str, signature: str) -> str:
    """抓兩格縮排 top-level 函式的原始碼片段（到同層收尾大括號）。"""
    start = source.index(signature)
    end = source.index("\n  }\n", start)
    return source[start:end]
