"""`/api/templates` 契約測試。

測試項目：
- CRUD
- 驗證器整合（合法/不合法 template）
- Preview endpoint
- 不修改 Item
"""

from __future__ import annotations

import pytest

VALID_HTML = """<!doctype html>
<html>
<head>
<style>
.card { width: 100mm; padding: 10mm; }
.photo { width: 84mm; height: 60mm; }
</style>
</head>
<body>
<div class="card">
    <img data-bind-src="item.primary_photo" alt="">
    <h1 data-bind="item.name"></h1>
    <div data-bind="item.brand"></div>
    <div data-bind="item.model"></div>
    <div data-bind="item.category"></div>
    <div data-bind="item.quantity"></div>
    <div data-bind="item.condition"></div>
    <div data-bind="item.notes"></div>
</div>
</body>
</html>
"""

INVALID_HTML_SCRIPT = """<html><body><script>alert(1)</script></body></html>"""
INVALID_HTML_UNKNOWN_BIND = """<html><body><span data-bind="item.unknown"></span></body></html>"""
INVALID_HTML_EVENT = """<html><body><div onclick="alert(1)"></div></body></html>"""


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture()
def item(repo):
    return repo.create_item(name="Product A", brand="Brand A", model="Model A")


# ----------------------------------------------------------------------
# 1. CRUD
# ----------------------------------------------------------------------


def test_create_template(client, repo):
    resp = client.post("/api/templates", json={
        "name": "Test Template",
        "html": VALID_HTML,
        "width": 100,
        "height": 150,
        "unit": "mm",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Test Template"
    assert body["html"] == VALID_HTML
    assert body["width"] == 100
    assert body["height"] == 150
    assert body["unit"] == "mm"
    assert body["id"].startswith("TPL-")

    # DB 確認
    tpl = repo.get_template(body["id"])
    assert tpl.name == "Test Template"


def test_create_template_minimal(client, repo):
    """只給必要欄位也能建立。"""
    resp = client.post("/api/templates", json={
        "name": "Minimal",
        "html": VALID_HTML,
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Minimal"


def test_create_template_invalid_html_rejected(client):
    """驗證器擋下不合法 HTML。"""
    for invalid_html in (INVALID_HTML_SCRIPT, INVALID_HTML_UNKNOWN_BIND, INVALID_HTML_EVENT):
        resp = client.post("/api/templates", json={
            "name": "Bad",
            "html": invalid_html,
        })
        assert resp.status_code == 400, f"應拒絕: {invalid_html[:50]}"
        assert "驗證失敗" in resp.json()["detail"]


def test_get_template(client, repo):
    tpl = repo.add_template(name="Get Test", html=VALID_HTML)
    resp = client.get(f"/api/templates/{tpl.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == tpl.id
    assert resp.json()["name"] == "Get Test"


def test_get_template_404(client):
    resp = client.get("/api/templates/TPL-NOTEXIST")
    assert resp.status_code == 404


def test_list_templates(client, repo):
    repo.add_template(name="A", html=VALID_HTML)
    repo.add_template(name="B", html=VALID_HTML)
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 2
    names = [t["name"] for t in body]
    assert "A" in names and "B" in names


def test_update_template(client, repo):
    tpl = repo.add_template(name="Old", html=VALID_HTML)
    resp = client.put(f"/api/templates/{tpl.id}", json={
        "name": "New Name",
        "width": 200,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["width"] == 200
    assert body["html"] == VALID_HTML  # 未改變

    # 再次 GET 確認
    assert repo.get_template(tpl.id).name == "New Name"


def test_update_template_invalid_html_rejected(client, repo):
    tpl = repo.add_template(name="OK", html=VALID_HTML)
    resp = client.put(f"/api/templates/{tpl.id}", json={
        "html": INVALID_HTML_SCRIPT,
    })
    assert resp.status_code == 400
    # 原本內容未被覆蓋
    assert repo.get_template(tpl.id).html == VALID_HTML


def test_delete_template(client, repo):
    tpl = repo.add_template(name="ToDelete", html=VALID_HTML)
    resp = client.delete(f"/api/templates/{tpl.id}")
    assert resp.status_code == 204
    # 確認刪除
    with pytest.raises(Exception):  # NotFoundError
        repo.get_template(tpl.id)


def test_delete_template_does_not_affect_item(client, repo, item):
    tpl = repo.add_template(name="T", html=VALID_HTML)
    client.delete(f"/api/templates/{tpl.id}")
    # Item 仍存在
    assert repo.get_item(item.id).id == item.id


# ----------------------------------------------------------------------
# 2. Preview
# ----------------------------------------------------------------------


def test_preview_template(client, repo, item):
    tpl = repo.add_template(name="Preview TPL", html=VALID_HTML)
    resp = client.post(f"/api/templates/{tpl.id}/preview", json={
        "item_id": item.id,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "html" in body
    assert body["item_id"] == item.id
    assert body["item_name"] == "Product A"

    # 渲染結果包含 Item 資料
    assert "Product A" in body["html"]
    assert "Brand A" in body["html"]
    assert "data-bind" not in body["html"]


def test_preview_template_404_template(client, item):
    resp = client.post("/api/templates/TPL-NOTEXIST/preview", json={
        "item_id": item.id,
    })
    assert resp.status_code == 404


def test_preview_template_404_item(client, repo):
    tpl = repo.add_template(name="T", html=VALID_HTML)
    resp = client.post(f"/api/templates/{tpl.id}/preview", json={
        "item_id": "ITM-NOTEXIST",
    })
    assert resp.status_code == 404


def test_preview_does_not_mutate_item(client, repo, item):
    """Preview 是 read-only，不修改 Item。"""
    tpl = repo.add_template(name="T", html=VALID_HTML)
    original_name = item.name

    client.post(f"/api/templates/{tpl.id}/preview", json={"item_id": item.id})

    assert repo.get_item(item.id).name == original_name


def test_preview_with_item_without_photo(client, repo):
    """無照片 Item 也能預覽（primary_photo 為空）。"""
    item = repo.create_item(name="No Photo", brand="B", model="M")
    tpl = repo.add_template(name="T", html=VALID_HTML)
    resp = client.post(f"/api/templates/{tpl.id}/preview", json={"item_id": item.id})
    assert resp.status_code == 200
    # 沒有照片時 primary_photo 為空，src="" 或不存在
    assert "No Photo" in resp.json()["html"]


# ----------------------------------------------------------------------
# 3. Validation 邊界
# ----------------------------------------------------------------------


def test_create_missing_name_rejected(client):
    resp = client.post("/api/templates", json={"html": VALID_HTML})
    assert resp.status_code == 400  # pydantic validation


def test_create_missing_html_rejected(client):
    resp = client.post("/api/templates", json={"name": "Test"})
    assert resp.status_code == 400


def test_update_unknown_field_ignored(client, repo):
    """未知欄位被 pydantic 忽略（extra=ignore 預設）。"""
    tpl = repo.add_template(name="T", html=VALID_HTML)
    resp = client.put(f"/api/templates/{tpl.id}", json={
        "unknown_field": "xxx",
    })
    assert resp.status_code == 200  # 忽略未知欄位


# ----------------------------------------------------------------------
# 4. 與現有 API 共存
# ----------------------------------------------------------------------


def test_existing_api_still_works(client):
    """既有 /api/items 等端點不受影響。"""
    resp = client.get("/api/items")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ----------------------------------------------------------------------
# Acceptance：同一份 Template 套不同 Item（SPEC §6 / §16）
# ----------------------------------------------------------------------

#: SPEC §6 的驗收模板。Item schema 沒有 price 欄位（§4 明講不得虛構
#: 不存在的資料），所以用 category/quantity 這類真實欄位取代，
#: 其餘綁定與驗收意圖完全相同。
ACCEPTANCE_HTML = """<!doctype html>
<html>
<head>
<style>
.card {
    width: 100mm;
    padding: 10mm;
}
</style>
</head>
<body>
<div class="card">
    <img data-bind-src="item.primary_photo" alt="">
    <h1 data-bind="item.name"></h1>
    <div data-bind="item.brand"></div>
    <div data-bind="item.model"></div>
    <div data-bind="item.category"></div>
    <div data-bind="item.quantity"></div>
</div>
</body>
</html>
"""


def _snapshot(repo, item_id, template_id):
    """把「不該被 preview 改動」的東西全部拍一張相。"""
    item = repo.get_item(item_id)
    return {
        "template_html": repo.get_template(template_id).html,
        "template_updated_at": repo.get_template(template_id).updated_at,
        "item": (
            item.name, item.brand, item.model, item.category,
            item.quantity, item.condition, item.notes, item.status,
            item.attributes, item.updated_at,
        ),
        "observations": [
            (o.id, o.kind, o.note) for o in repo.list_observations(item_id=item_id)
        ],
        "suggestions": [
            (s.id, s.field, s.value, s.status)
            for s in repo.list_suggestions(item_id=item_id)
        ],
        "photos": [
            (p.id, p.filename, p.role)
            for p in repo.list_photos(item_id=item_id, role=None, limit=50)
        ],
        "events": repo.list_events(entity_type="item", entity_id=item_id),
    }


def test_acceptance_same_template_two_items(client, repo):
    """同一 Template + ITM-0001 → A 的資料；同一 Template + ITM-0002 → B 的資料。

    這是整個 Phase 的核心假設，所以同時驗證：Template 沒變、兩個 Item
    都沒變、preview 沒有產生任何 suggestion 或 event。
    """
    item_a = repo.create_item(
        name="Product A", brand="Brand A", model="Model A",
        category="Category A", quantity=1000,
    )
    item_b = repo.create_item(
        name="Product B", brand="Brand B", model="Model B",
        category="Category B", quantity=2000,
    )
    assert item_a.id != item_b.id

    template = repo.add_template(name="Acceptance", html=ACCEPTANCE_HTML)
    before = {
        item_a.id: _snapshot(repo, item_a.id, template.id),
        item_b.id: _snapshot(repo, item_b.id, template.id),
    }

    response_a = client.post(
        f"/api/templates/{template.id}/preview", json={"item_id": item_a.id}
    )
    assert response_a.status_code == 201 or response_a.status_code == 200
    html_a = response_a.json()["html"]

    response_b = client.post(
        f"/api/templates/{template.id}/preview", json={"item_id": item_b.id}
    )
    html_b = response_b.json()["html"]

    # 每個 Item 的資料都出現在自己的預覽裡
    for expected in ("Product A", "Brand A", "Model A", "Category A", "1000"):
        assert expected in html_a
    for expected in ("Product B", "Brand B", "Model B", "Category B", "2000"):
        assert expected in html_b

    # 兩個預覽確實不同（這正是「可重複套用不同 Item」的證明）
    assert html_a != html_b
    assert "Product B" not in html_a
    assert "Product A" not in html_b

    # Template 與兩個 Item 都沒有被改動
    after = {
        item_a.id: _snapshot(repo, item_a.id, template.id),
        item_b.id: _snapshot(repo, item_b.id, template.id),
    }
    assert after == before

    # Preview 不產生 suggestion，也不寫 event。
    # （建立 Item 本來就會有 item.created，這裡要斷言的是「preview 沒有
    #   額外增加任何事件」—— before/after 快照相等就是這個證明。）
    assert after[item_a.id]["suggestions"] == []
    assert after[item_b.id]["suggestions"] == []
    assert [event.type for event in after[item_a.id]["events"]] == ["item.created"]
    assert [event.type for event in after[item_b.id]["events"]] == ["item.created"]

    # Template 的生命週期事件只有建立時那一筆，沒有 preview 造成的
    template_events = repo.list_events(
        entity_type="template", entity_id=template.id
    )
    assert [event.type for event in template_events] == ["template.created"]


def test_acceptance_reuses_one_template_for_many_items(client, repo):
    """同一 Template 可以安全重複套用到任意多個 Item。"""
    template = repo.add_template(name="Reusable", html=ACCEPTANCE_HTML)
    items = [
        repo.create_item(name=f"Product {index}", brand=f"Brand {index}")
        for index in range(5)
    ]
    rendered = set()
    for item in items:
        html = client.post(
            f"/api/templates/{template.id}/preview", json={"item_id": item.id}
        ).json()["html"]
        rendered.add(html)
    assert len(rendered) == len(items)
    assert repo.get_template(template.id).html == ACCEPTANCE_HTML


def test_preview_writes_nothing_at_all(client, repo):
    """Preview 走過之後，整個資料庫不該多出任何一筆。"""
    item = repo.create_item(name="Read Only", brand="B")
    template = repo.add_template(name="T", html=ACCEPTANCE_HTML)

    before = _snapshot(repo, item.id, template.id)
    assert client.post(
        f"/api/templates/{template.id}/preview", json={"item_id": item.id}
    ).status_code == 200
    assert _snapshot(repo, item.id, template.id) == before