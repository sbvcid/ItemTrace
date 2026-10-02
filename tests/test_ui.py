"""Phase 6A 的網頁與 API 的整合測試。

沒有瀏覽器可用（不起 headless browser，避免為純 HTML/CSS/JS 引入測試
相依），所以這裡驗的是「頁面有沒有正確提供」與「前端呼叫的端點與參數
跟後端契約是否一致」：

  * 頁面與靜態資源能不能拿到
  * 前端 JS 裡出現的 /api/* 端點真的存在於 OpenAPI 契約（防漂移）
  * 前端送出的查詢參數真的能篩到資料
  * 列表／詳細頁需要���欄位真的有回來
  * 前端沒有任何刪除原始照片的操作
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

def _new_item(client, **body):
    response = client.post("/api/items", json=body)
    assert response.status_code == 201, response.text
    return response.json()


#: 前端可能呼叫的 API 端點樣式（動態拼湊的字串片段也算）
API_CALL = re.compile(r"[\"'`](/api/[A-Za-z0-9_\-/{}]*)")


def ui_source(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


@pytest.fixture()
def stocked(client):
    """一件有照片、識別碼、觀測、待確認建議的商品，另加一件無照片的。"""
    photos = client.post("/api/items", json={"name": "ROG STRIX B650E-F",
                                             "brand": "華碩", "category": "主機板"}).json()
    plain = client.post("/api/items", json={"name": "還沒建檔"}).json()

    observation = client.post(f"/api/items/{photos['id']}/observations",
                              json={"kind": "intake", "note": "出貨前拍攝"}).json()
    from tests.conftest import make_jpeg

    uploaded = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[("files", ("IMG_4821.jpg", make_jpeg(exif="2026:10:02 14:30:22"),
                          "image/jpeg"))],
    ).json()["archived"][0]

    client.post(f"/api/items/{photos['id']}/identifiers",
                json={"value": "BX-807 06_1234", "confidence": 0.9,
                      "source_photo_id": uploaded["id"]})
    client.post(f"/api/items/{photos['id']}/suggestions",
                json={"field": "brand", "value": "華碩", "confidence": 0.9,
                      "source_photo_id": uploaded["id"]})
    return {"item": photos, "plain": plain, "photo": uploaded,
            "observation": observation}


# ----------------------------------------------------------------------
# 頁面與靜態資源
# ----------------------------------------------------------------------


def test_root_redirects_to_items(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/items"


def test_items_page_loads(client):
    response = client.get("/items")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/static/app.css" in response.text
    assert "/static/list.js" in response.text


def test_item_detail_page_loads_for_any_id(client, stocked):
    """頁面殼子不驗證 id —— 真正的 404 由前端打 API 時才出現。"""
    assert client.get(f"/items/{stocked['item']['id']}").status_code == 200
    assert client.get("/items/ITM-9999").status_code == 200


def test_detail_page_loads_the_assets_it_needs(client):
    body = client.get("/items/ITM-0001").text
    assert "/static/item.js" in body
    assert "/static/api.js" in body
    assert "/static/app.css" in body


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/static/app.css", "text/css"),
        ("/static/api.js", "javascript"),
        ("/static/list.js", "javascript"),
        ("/static/item.js", "javascript"),
    ],
)
def test_static_assets_are_served(client, path, kind):
    response = client.get(path)
    assert response.status_code == 200
    assert kind in response.headers["content-type"]


def test_static_does_not_serve_arbitrary_files(client, stocked):
    """靜態目錄只能拿到 ui/ 底下的東西。"""
    assert client.get("/static/../catalog.db").status_code in (403, 404)
    assert client.get("/static/../shop/api.py").status_code in (403, 404)


# ----------------------------------------------------------------------
# UI 路由不進 API 契約
# ----------------------------------------------------------------------


def test_ui_pages_are_not_in_the_openapi_contract(client):
    """UI 是頁面不是 API，/docs 應該只顯示真正的資料端點。"""
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/items", "/items/{item_id}", "/static/{path}", "/files/{path}",
                 "/"):
        assert path not in paths
    assert "/api/items" in paths


# ----------------------------------------------------------------------
# 前端呼叫的端點必須真的存在（防契約漂移）
# ----------------------------------------------------------------------


def test_frontend_only_calls_endpoints_that_exist(client):
    """前端呼叫的端點必須在 OpenAPI 契約裡 —— 這是防契約漂移的主要測試。"""
    spec = client.get("/openapi.json").json()["paths"]
    seen: set[str] = set()
    for name in ("api.js", "list.js", "item.js"):
        for call in API_CALL.findall(ui_source(name)):
            call = call.split("?")[0]
            if "{" in call:
                continue  # 動態拼湊，出現佔位符就當是識別碼不是路由
            seen.add(call)
    # 這三個就是這個階段會用到的全部端點；尾斜線代表後面接識別碼
    # （例如 "/api/items/" + id），用起始比對確認契約上有那條路由。
    plain = {path for path in seen if not path.endswith("/")}
    assert plain <= set(spec), f"前端呼叫了契約外的端點：{plain - set(spec)}"
    for prefix in (path for path in seen if path.endswith("/")):
        assert any(p.startswith(prefix) for p in spec), f"契約上沒有 {prefix}*"
    assert plain == {"/api/items", "/api/stats", "/api/identifiers/lookup"}


def test_frontend_sends_the_search_and_filter_params_the_api_accepts(client):
    """前端送 q / status / category / limit / offset，後端都收。"""
    response = client.get(
        "/api/items?q=華碩&status=active&category=主機板&limit=30&offset=0"
    )
    assert response.status_code == 200


def test_detail_page_uses_the_existing_patch_endpoint(client):
    assert '"PATCH"' in ui_source("item.js")
    assert "/api/items/" in ui_source("item.js")
    assert "PUT" not in ui_source("item.js")


# ----------------------------------------------------------------------
# 列表頁需要什麼就有什麼
# ----------------------------------------------------------------------


def test_list_response_carries_what_the_list_page_renders(client, stocked):
    rows = client.get("/api/items").json()
    assert len(rows) == 2
    by_id = {row["id"]: row for row in rows}

    rich = by_id[stocked["item"]["id"]]
    assert rich["name"] == "ROG STRIX B650E-F"
    assert rich["brand"] == "華碩"
    assert rich["category"] == "主機板"
    assert rich["status"] == "active"
    assert rich["photo_count"] == 1
    assert rich["thumbnail"] == stocked["photo"]["filename"]

    empty = by_id[stocked["plain"]["id"]]
    assert empty["photo_count"] == 0
    assert empty["thumbnail"] is None


def test_list_thumbnail_is_servable(client, stocked):
    rows = client.get("/api/items").json()
    thumbnail = next(r for r in rows if r["thumbnail"])["thumbnail"]
    response = client.get(f"/files/{thumbnail}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_list_search_returns_two_chinese_characters(client, stocked):
    """列表頁預設就是這個搜尋框；兩字中文必須找得到。"""
    found = client.get("/api/items?q=主機").json()
    assert [row["id"] for row in found] == [stocked["item"]["id"]]


def test_list_search_by_serial_tail(client, stocked):
    found = client.get("/api/items?q=807061234").json()
    assert [row["id"] for row in found] == [stocked["item"]["id"]]


def test_list_filters_combine_with_search(client, stocked):
    assert client.get("/api/items?q=華碩&category=主機板").json()
    assert client.get("/api/items?q=華碩&category=顯示卡").json() == []


def test_list_pagination_window(client, stocked):
    first = client.get("/api/items?limit=1&offset=0").json()
    second = client.get("/api/items?limit=1&offset=1").json()
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]


def test_category_options_come_from_stats(client, stocked):
    """分類下拉選單的資料來源，不硬寫在前端。"""
    categories = client.get("/api/stats?limit=1").json()["categories"]
    assert set(categories) == {"主機板"}


def test_status_options_are_the_three_frozen_values(client):
    """前端把三個狀態寫在 list.js，所以後端也要收這三個值。"""
    for status in ("active", "archived", "void"):
        assert client.get(f"/api/items?status={status}").status_code == 200


# ----------------------------------------------------------------------
# 詳細頁需要什麼就有什麼
# ----------------------------------------------------------------------


def test_detail_response_carries_everything_the_page_renders(client, stocked):
    detail = client.get(f"/api/items/{stocked['item']['id']}").json()

    assert detail["item"]["id"] == stocked["item"]["id"]
    assert detail["item"]["created_at"] and detail["item"]["updated_at"]

    assert [p["orig_name"] for p in detail["photos"]] == ["IMG_4821.jpg"]
    assert detail["photos"][0]["observation_id"] == stocked["observation"]["id"]

    assert detail["identifiers"][0]["kind"] == "serial"
    assert detail["identifiers"][0]["value"] == "BX-807 06_1234"
    assert detail["identifiers"][0]["source_photo_id"] == stocked["photo"]["id"]

    assert [o["kind"] for o in detail["observations"]] == ["intake"]
    assert detail["suggestion_counts"] == {"pending": 1}


def test_detail_page_can_load_history(client, stocked):
    events = client.get(f"/api/items/{stocked['item']['id']}/events").json()
    types = [event["type"] for event in events]
    assert "item.created" in types
    assert "photo.created" in types
    assert "observation.created" in types
    assert "identifier.created" in types


def test_collision_warning_uses_the_existing_lookup_endpoint(client):
    """撞號提示不另外開 API，用既有 lookup 再前端比對。"""
    first = client.post("/api/items", json={"name": "甲"}).json()
    second = client.post("/api/items", json={"name": "乙"}).json()
    client.post(f"/api/items/{first['id']}/identifiers", json={"value": "BX807061234"})
    response = client.post(
        f"/api/items/{second['id']}/identifiers",
        json={"value": "BX-807 06_1234", "allow_collision": True},
    )
    assert response.status_code == 201

    matches = client.get("/api/identifiers/lookup?value=BX807061234").json()["matches"]
    others = {m["item_id"] for m in matches if m["normalized"] == "BX807061234"}
    assert others == {first["id"], second["id"]}


# ----------------------------------------------------------------------
# 欄位編輯
# ----------------------------------------------------------------------


def test_form_fields_match_the_patchable_item_fields(client):
    """編輯表單的欄位必須是 PATCH 允許的欄位。"""
    item = _new_item(client)
    body = "".join(ui_source("item.js").split('FIELDS = [')[1].split("];")[0])
    fields = re.findall(r'"(\w+)"', body)

    assert fields
    for name in fields:
        value = 2 if name == "quantity" else "測試值"
        response = client.patch(f"/api/items/{item['id']}", json={name: value})
        assert response.status_code == 200, f"{name} 不能 PATCH"


def test_patch_updates_and_is_visible_immediately(client):
    item = _new_item(client, brand="舊")
    patched = client.patch(f"/api/items/{item['id']}",
                           json={"brand": "新", "notes": "順手改一下"})
    assert patched.json()["brand"] == "新"
    assert patched.json()["notes"] == "順手改一下"

    refetched = client.get(f"/api/items/{item['id']}").json()["item"]
    assert refetched["brand"] == "新"


def test_patch_records_an_event(client):
    item = _new_item(client, brand="舊")
    client.patch(f"/api/items/{item['id']}", json={"brand": "新"})
    events = client.get(f"/api/items/{item['id']}/events").json()
    change = next(e for e in events if e["type"] == "field.changed")
    assert (change["prev_value"], change["next_value"]) == ("舊", "新")


def test_patch_rejects_bad_values(client):
    item = _new_item(client)
    assert client.patch(f"/api/items/{item['id']}",
                        json={"quantity": 0}).status_code == 400
    assert client.patch(f"/api/items/{item['id']}",
                        json={"status": "draft"}).status_code == 400


# ----------------------------------------------------------------------
# 原始照片：可看不可刪
# ----------------------------------------------------------------------


def test_frontend_never_deletes_a_photo(client):
    """UI 不得提供刪除照片的操作。"""
    for name in ("api.js", "list.js", "item.js"):
        source = ui_source(name)
        assert "DELETE" not in source, f"{name} 有 DELETE 呼叫"
        assert "delete_photo" not in source


def test_frontend_has_no_delete_controls_at_all(client):
    joined = "".join(ui_source(n) for n in ("index.html", "item.html", "api.js",
                                            "list.js", "item.js"))
    assert "刪除" not in joined
    assert "永久刪除" not in joined


def test_original_photo_delete_is_refused_by_the_api(client, stocked):
    response = client.delete(f"/api/photos/{stocked['photo']['id']}")
    assert response.status_code == 400
    assert client.get(f"/api/items/{stocked['item']['id']}").json()["photos"]


def test_photos_are_only_opened_for_viewing(client, stocked):
    """原始照片只能點開看，不能在頁面上做任何異動。"""
    source = ui_source("item.js")
    assert "window.open(photoUrl(" in source
    assert "add_photo" not in source
    assert "patch_photo" not in source


# ----------------------------------------------------------------------
# 沒有塞進這個階段不該有的東西
# ----------------------------------------------------------------------


def test_ui_has_no_inbox_or_suggestion_actions(client):
    """Phase 6A 範圍：只做商品列表與詳細頁。"""
    joined = "".join(ui_source(n) for n in ("index.html", "item.html", "list.js",
                                            "item.js"))
    for forbidden in ("/api/inbox", "/api/suggestions", "/accept", "/reject",
                      "/api/events/", "/void"):
        assert forbidden not in joined, f"不該出現 {forbidden}"


def test_ui_has_no_build_step_or_framework():
    """原生 HTML/CSS/JS：不引入框架、不需要 npm build。"""
    files = sorted(p.name for p in UI_DIR.iterdir())
    assert files == ["api.js", "app.css", "index.html", "item.html",
                     "item.js", "list.js"]
    for path in UI_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "import " not in text
        assert "require(" not in text
        assert "node_modules" not in text


def test_ui_scripts_declare_their_tags(client):
    for name in ("api.js", "list.js", "item.js"):
        assert ui_source(name).lstrip().startswith("/*")


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 做語法檢查")
def test_javascript_actually_parses():
    """pyflakes 只看 Python；JS 語法錯誤只有 parse 得出來才知道。

    有 node 就順便檢查，沒有就跳過 —— 不為了這個測試去加相依。
    """
    for path in sorted(UI_DIR.glob("*.js")):
        result = subprocess.run(
            ["node", "--check", str(path)], capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{path.name} 語法錯誤：{result.stderr}"