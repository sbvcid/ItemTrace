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

import json
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


def test_root_is_the_inbox_page(client):
    """Phase 7 起 / 是 inbox，商品列表在 /items。"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/static/inbox.js" in response.text


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
        ("/static/inbox.js", "javascript"),
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
    for name in ("api.js", "list.js", "item.js", "inbox.js"):
        for call in API_CALL.findall(ui_source(name)):
            call = call.split("?")[0]
            if "{" in call:
                continue  # 動態拼湊，出現佔位符就當是識別碼不是路由
            seen.add(call)
    plain = {path for path in seen if not path.endswith("/")}
    assert plain <= set(spec), f"前端呼叫了契約外的端點：{plain - set(spec)}"
    for prefix in (path for path in seen if path.endswith("/")):
        assert any(p.startswith(prefix) for p in spec), f"契約上沒有 {prefix}*"


def test_frontend_touches_only_the_endpoints_it_needs(client):
    """這個階段的前端只該用到這些端點 —— 超出就是範圍蔓延。"""
    spec = client.get("/openapi.json").json()["paths"]
    seen: set[str] = set()
    for name in ("api.js", "list.js", "item.js", "inbox.js"):
        for call in API_CALL.findall(ui_source(name)):
            if "{" in call:
                continue
            seen.add(call.split("?")[0].rstrip("/"))
    assert seen <= {
        "/api/items", "/api/stats", "/api/identifiers/lookup",
        "/api/inbox", "/api/inbox/group", "/api/inbox/photos",
        "/api/inbox/intake", "/api/suggestions",
    }, f"前端用到了範圍外的端點：{seen}"
    assert "/api/items" in spec and "/api/inbox/intake" in spec


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
    for name in ("api.js", "list.js", "item.js", "inbox.js"):
        source = ui_source(name)
        assert "DELETE" not in source, f"{name} 有 DELETE 呼叫"
        assert "delete_photo" not in source


def test_frontend_has_no_delete_controls_at_all(client):
    joined = "".join(ui_source(n) for n in UI_DIR.iterdir() if n.suffix in (".js", ".html"))
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


def test_ui_has_no_suggestion_or_revert_actions(client):
    """Phase 6A/7 都沒有 suggestion 自動處理與 revert UI。"""
    joined = "".join(ui_source(n) for n in UI_DIR.iterdir() if n.suffix in (".js", ".html"))
    for forbidden in ("/accept", "/reject", "/api/events/", "/revert", "/void"):
        assert forbidden not in joined, f"不該出現 {forbidden}"


def test_ui_has_no_build_step_or_framework():
    """原生 HTML/CSS/JS：不引入框架、不需要 npm build。"""
    files = sorted(p.name for p in UI_DIR.iterdir())
    assert files == [
        "api.js", "app.css", "inbox.html", "inbox.js",
        "item.html", "item.js", "items.html", "list.js",
    ]
    for path in UI_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "import " not in text
        assert "require(" not in text
        assert "node_modules" not in text


def test_ui_scripts_declare_their_tags(client):
    for name in ("api.js", "list.js", "item.js", "inbox.js"):
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


# ----------------------------------------------------------------------
# 商品詳細頁的行為測試
#
# renderEvents() 曾經把字串當成 el() 的第三引數（children 必須是 Array），
# 丟出「(children || []).forEach is not a function」。因為 start() 整段被
# try/catch 包住，例外被轉成「找不到這件商品」——真正的原因完全看不到。
#
# 這組用 node 的 vm 跑真正的 ui/item.js，看它有沒有例外、事件有沒有渲染。
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def item_view():
    """跑一次 tests/item_dom_harness.js，回傳每個情境的結果。"""
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能做行為測試")
    script = Path(__file__).resolve().parent / "item_dom_harness.js"
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


def _normal(item_view):
    return item_view["一般情形"]


def test_item_page_renders_without_errors(item_view):
    """一般 event（含 prev_value、actor/entity_type 兩者都有值）要能渲染。"""
    row = _normal(item_view)
    assert row["error"] is None, row["error"]
    assert row["shownErrors"] == [], f"頁面報錯：{row['shownErrors']}"


#: 這些情境是「刻意」產生錯誤訊息的（Phase 8B 的決定／重載失敗路徑），
#: 不在「渲染錯誤不得顯示成找不到這件商品」的管轄範圍內。
INTENTIONALLY_FAILING = {
    "detail 抓不到",
    "accept 回 409",
    "accept 回 500",
    "接受成功但重載失敗",
    "拒絕成功但重載失敗",
    "接受成功但歷史載入失敗",
    "拒絕成功但歷史載入失敗",
    "欄位儲存成功但歷史載入失敗",
}


def test_render_events_does_not_show_item_not_found(item_view):
    """renderEvents 出錯不該讓整頁變成「找不到這件商品」。

    這正是那個 bug 的症狀：例外被 start() 的 catch 吃掉，顯示成 notFound。
    """
    for label, row in item_view.items():
        if label in INTENTIONALLY_FAILING:
            continue
        assert row["notFoundShown"] is False, f"{label} 顯示成找不到這件商品"
        assert row["shownErrors"] == [], f"{label}：{row['shownErrors']}"


def test_render_events_draws_one_row_per_event(item_view):
    """4 筆一般 event（含 prev_value 有值與 actor 為空兩種分支）→ 4 列。"""
    row = _normal(item_view)
    assert row["eventRows"] == 4
    assert "GET /api/items/ITM-0001/events" in row["calls"]


def test_render_events_handles_a_single_event(item_view):
    assert item_view["一筆 events"]["eventRows"] == 1


def test_render_events_handles_no_events(item_view):
    row = item_view["沒有 events"]
    assert row["error"] is None
    assert row["shownErrors"] == []
    assert row["eventRows"] == 0


def test_identifier_cell_renders_with_and_without_source_photo(item_view):
    """有來源照片與沒有來源照片兩個分支都要過（都是同類型的 el() 誤用）。"""
    with_source = _normal(item_view)
    without_source = item_view["identifier 沒有來源照片"]
    for row in (with_source, without_source):
        assert row["error"] is None
        assert row["shownErrors"] == [], row["shownErrors"]
        assert row["detailShown"] is True


def test_identifiers_table_renders_when_there_are_identifiers(item_view):
    row = _normal(item_view)
    assert row["calls"][0] == "GET /api/items/ITM-0001"
    assert row["detailShown"] is True


def test_page_without_photos_still_renders(item_view):
    row = item_view["沒有照片"]
    assert row["shownErrors"] == []
    assert row["wallCells"] == 0
    assert row["detailShown"] is True


def test_page_without_identifiers_still_renders(item_view):
    row = item_view["沒有 identifiers"]
    assert row["shownErrors"] == []
    assert row["detailShown"] is True


def test_missing_item_still_shows_not_found(item_view):
    """真的抓不到商品時才該顯示「找不到」，不能把這個訊息當成萬用的錯誤出口。"""
    row = item_view["detail 抓不到"]
    assert row["notFoundShown"] is True
    assert row["shownErrors"], "抓不到商品應該要留下錯誤訊息"


#: 會產生 Array 的運算式；這些當作第三引數是安全的。
ARRAY_PRODUCING = re.compile(
    r"(?:\.\s*(?:concat|map|filter|slice|flat|flatMap|sort|reverse|split|toSorted)\s*\()"
    r"|^[A-Za-z_$][\w$]*\s*$"
)


def test_no_el_call_passes_a_bare_string_or_element_as_children():
    """el(tag, attrs, children) 的第三引數必須是 Array。

    這是第二道防護，抓的是「第三引數明擺著不是陣列」的情況
    （裸字串、單一 Element）。它**抓不到**三元運算子尾巴不是陣列的情況 ——
    例如 `[x].filter(Boolean).join(" · ")` 看起來以 `[` 開頭卻回傳字串，
    那是 renderEvents 那個 bug，交给上面的行為測試擋。

    只靠字串比對很容易漏掉「換個變數名就失效」的情況，所以這裡做結構
    檢查：找出所有 el() 呼叫（跳過 el 自己的宣告），平衡括號切出第三引數。
    """
    offenders = []
    for path in sorted(UI_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\bel\(", text):
            prefix = text[:match.start()].rstrip()
            if prefix.endswith("function"):
                continue  # el 的宣告本身，不是呼叫
            end = _balanced_end(text, match.end())
            if end is None:
                continue
            args = _split_args(text[match.end():end])
            if len(args) < 3:
                continue
            third = args[2].strip()
            if third.startswith("[") or third in ("", "null", "undefined"):
                continue
            if third.startswith("/*") or third.startswith("//"):
                continue  # 註解接著才是陣列
            if ARRAY_PRODUCING.search(third):
                continue
            offenders.append(
                f"{path.name}:{text[:match.start()].count(chr(10)) + 1}: {third[:60]}"
            )
    assert offenders == [], "el() 第三引數必須是 Array：" + "; ".join(offenders)


def _balanced_end(text: str, start: int) -> int | None:
    """回傳對應右括號的位置（跳過字串與樣板字串，避免括號被字面值騙到）。"""
    depth = 1
    i = start
    quote = None
    while i < len(text) and depth:
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _split_args(call: str) -> list[str]:
    args, depth, current, quote = [], 0, "", None
    for char in call:
        if quote:
            current += char
            if char == quote:
                quote = None
            continue
        if char in "\"'`":
            quote = char
            current += char
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            args.append(current)
            current = ""
        else:
            current += char
    args.append(current)
    return args