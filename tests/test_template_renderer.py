"""template_renderer.py 的單元測試。

驗證：
- 文字 binding 正確替換並 HTML escape
- 圖片 binding 正確替換 src
- None/空值轉空字串
- 未知 binding 不渲染
- Template/Item 分離：渲染不修改原資料
"""

from __future__ import annotations

import pytest

from shop.models import Item, Template
from shop.template_renderer import (
    TemplateViewModel,
    TemplateRenderer,
    render_template,
    render_template_preview,
    RenderError,
)



# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


class FakeRepo:
    """最小 Repository stub：只提供 list_photos。"""

    def __init__(self, photos=None):
        self._photos = photos or []

    def list_photos(self, *, item_id, role, limit):
        return self._photos


class FakeConfig:
    def __init__(self):
        pass


class FakePhoto:
    def __init__(self, filename):
        self.filename = filename


# ----------------------------------------------------------------------
# 1. TemplateViewModel
# ----------------------------------------------------------------------


def test_view_model_from_item():
    item = Item(
        id="ITM-0001",
        name="Test Product",
        brand="TestBrand",
        model="TestModel",
        category="TestCat",
        quantity=5,
        condition="New",
        notes="Some notes",
    )
    repo = FakeRepo([FakePhoto("files/ITM-0001/original/a.jpg")])
    config = FakeConfig()

    vm = TemplateViewModel.from_item(item, repo, config)

    assert vm.id == "ITM-0001"
    assert vm.name == "Test Product"
    assert vm.brand == "TestBrand"
    assert vm.model == "TestModel"
    assert vm.category == "TestCat"
    assert vm.quantity == "5"
    assert vm.condition == "New"
    assert vm.notes == "Some notes"
    assert vm.primary_photo == "/files/files/ITM-0001/original/a.jpg"


def test_view_model_empty_photo():
    """無照片時 primary_photo 為空字串。"""
    item = Item(id="ITM-0001", name="Test")
    repo = FakeRepo([])
    config = FakeConfig()

    vm = TemplateViewModel.from_item(item, repo, config)
    assert vm.primary_photo == ""


def test_view_model_get_field():
    vm = TemplateViewModel(
        id="1", name="N", brand="B", model="M", category="C",
        quantity="1", condition="New", notes="Notes", primary_photo="/x.jpg"
    )
    assert vm.get_field("name") == "N"
    assert vm.get_field("brand") == "B"
    assert vm.get_field("unknown") == ""


# ----------------------------------------------------------------------
# 2. TemplateRenderer
# ----------------------------------------------------------------------


def test_text_binding_replacement():
    """data-bind 文字內容被替換。"""
    vm = TemplateViewModel(
        id="1", name="Product A", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><h1 data-bind="item.name"></h1></body></html>""")
    renderer.close()
    output = renderer.render()
    assert "<h1>Product A</h1>" in output
    assert "data-bind" not in output


def test_image_binding_replacement():
    """data-bind-src 替換 img src。"""
    vm = TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo="/photo.jpg"
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><img data-bind-src="item.primary_photo" class="pic"></body></html>""")
    renderer.close()
    output = renderer.render()
    assert 'src="/photo.jpg"' in output
    assert 'class="pic"' in output
    assert "data-bind-src" not in output


def test_html_escaping():
    """文字 binding 內容被 HTML escape。"""
    vm = TemplateViewModel(
        id="1", name='<script>alert(1)</script>', brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><div data-bind="item.name"></div></body></html>""")
    renderer.close()
    output = renderer.render()
    # 原始 script 標籤被 escape，輸出包含 escaped 版本
    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in output


def test_empty_value_becomes_empty_string():
    """None/空值轉空字串。"""
    vm = TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><span data-bind="item.name"></span></body></html>""")
    renderer.close()
    output = renderer.render()
    assert "<span></span>" in output


def test_unknown_binding_renders_empty():
    """不在 registry 的 binding 渲染為空（驗證器應已攔截，但防禦性渲染）。"""
    vm = TemplateViewModel(
        id="1", name="N", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    # 手工構造未知 binding（正常不會過驗證）
    renderer.feed("""<html><body><span data-bind="item.unknown"></span></body></html>""")
    renderer.close()
    output = renderer.render()
    assert "<span></span>" in output


def test_attributes_preserved():
    """非 binding 屬性保留。"""
    vm = TemplateViewModel(
        id="1", name="N", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><div class="card" id="main" data-bind="item.name"></div></body></html>""")
    renderer.close()
    output = renderer.render()
    assert 'class="card"' in output
    assert 'id="main"' in output


def test_nested_tags():
    """巢狀標籤正常處理。"""
    vm = TemplateViewModel(
        id="1", name="N", brand="B", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""
    <html><body>
        <div class="outer">
            <h1 data-bind="item.name"></h1>
            <div data-bind="item.brand"></div>
        </div>
    </body></html>
    """)
    renderer.close()
    output = renderer.render()
    assert "N" in output
    assert "B" in output
    assert "data-bind" not in output


def test_bound_element_replaces_its_whole_content():
    """data-bind 的元素，整個內容換成欄位值。

    綁定元素裡再套子標籤時，值要落在綁定元素上、不是最深層那層，
    而且綁定元素內的靜態內容會被丟棄（不是被搬到別處）。
    """
    vm = TemplateViewModel(
        id="1", name="Product A", brand="B", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed('<div data-bind="item.name"><span>static</span></div>')
    renderer.close()
    output = renderer.render()
    assert output == "<div>Product A</div>"


def test_two_bound_elements_are_independent():
    """連續兩個綁定元素不會互相污染（深度計數要歸零）。"""
    vm = TemplateViewModel(
        id="1", name="A", brand="B", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed(
        '<p data-bind="item.name"></p><p data-bind="item.brand"></p><p>static</p>'
    )
    renderer.close()
    output = renderer.render()
    assert output == "<p>A</p><p>B</p><p>static</p>"


def test_doctype_is_preserved():
    """doctype 必須保留：preview 走 iframe srcdoc，掉了會變 quirks mode。"""
    vm = TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("<!doctype html><html><body><p>x</p></body></html>")
    renderer.close()
    assert renderer.render().startswith("<!doctype html>")


def test_void_element_gets_no_stray_end_tag():
    vm = TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo="/p.jpg"
    )
    renderer = TemplateRenderer(vm)
    renderer.feed('<img data-bind-src="item.primary_photo" alt=""/>')
    renderer.close()
    output = renderer.render()
    assert 'src="/p.jpg"' in output
    assert 'alt=""' in output
    assert "</img>" not in output
    assert "data-bind-src" not in output


def test_renderer_enforces_the_binding_allowlist():
    """即使 binding 繞過 validator，renderer 也不能解析非白名單欄位。

    getattr(view_model, "__class__") 會拿到型別物件，後面 html.escape
    會爆掉；這裡要的是乾淨地渲染成空字串。
    """
    vm = TemplateViewModel(
        id="1", name="N", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    for hostile in ("item.__class__", "item.__dict__", "os.environ", "db.items"):
        renderer = TemplateRenderer(vm)
        renderer.feed(f'<div data-bind="{hostile}"></div>')
        renderer.close()
        assert renderer.render() == "<div></div>", hostile


def test_get_field_rejects_unknown_names():
    vm = TemplateViewModel(
        id="1", name="N", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo=""
    )
    assert vm.get_field("item.name") == "N"
    assert vm.get_field("name") == "N"
    assert vm.get_field("item.__dict__") == ""
    assert vm.get_field("nope") == ""


def test_self_closing_img():
    """自閉合 img 標籤處理。"""
    vm = TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo="/x.jpg"
    )
    renderer = TemplateRenderer(vm)
    renderer.feed("""<html><body><img data-bind-src="item.primary_photo" alt="pic"/></body></html>""")
    renderer.close()
    output = renderer.render()
    assert 'src="/x.jpg"' in output


# ----------------------------------------------------------------------
# 3. render_template 高層函式
# ----------------------------------------------------------------------


def test_render_template_integration():
    """完整渲染流程。"""
    template = Template(
        id="TPL-001",
        name="Test Template",
        html=VALID_HTML,
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    item = Item(
        id="ITM-0001",
        name="Product A",
        brand="Brand A",
        model="Model A",
        category="Cat A",
        quantity=10,
        condition="New",
        notes="Desc A",
    )
    repo = FakeRepo([FakePhoto("files/ITM-0001/original/a.jpg")])
    config = FakeConfig()

    output = render_template(template, item, repo, config)

    assert "Product A" in output
    assert "Brand A" in output
    assert "Brand A" in output
    assert 'src="/files/files/ITM-0001/original/a.jpg"' in output
    assert "data-bind" not in output


def test_render_template_does_not_mutate_template_or_item():
    """渲染不修改原 Template 或 Item。"""
    template = Template(
        id="TPL-001", name="T", html=VALID_HTML,
        created_at="", updated_at=""
    )
    item = Item(id="ITM-0001", name="Original")
    repo = FakeRepo([FakePhoto("files/ITM-0001/original/a.jpg")])
    config = FakeConfig()

    original_html = template.html
    original_name = item.name

    render_template(template, item, repo, config)

    assert template.html == original_html
    assert item.name == original_name


def test_render_template_error_wrapped():
    """渲染錯誤包裝為 RenderError。"""
    # 傳入無效 template (非 Template 實例)
    with pytest.raises(RenderError):
        render_template("not a template", Item(id="1"), FakeRepo(), FakeConfig())


def test_render_template_preview_alias():
    """preview 別名功能相同。"""
    template = Template(id="1", name="T", html=VALID_HTML, created_at="", updated_at="")
    item = Item(id="1", name="N")
    repo = FakeRepo([FakePhoto("files/1/original/x.jpg")])
    config = FakeConfig()

    out1 = render_template(template, item, repo, config)
    out2 = render_template_preview(template, item, repo, config)
    assert out1 == out2


# ----------------------------------------------------------------------
# 測試用常數
# ----------------------------------------------------------------------

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


def test_render_template_today_binding():
    """驗證 data-bind="today" 正確輸出當前 YYYY/MM/DD 日期。"""
    from datetime import datetime
    expected_today = datetime.now().strftime("%Y/%m/%d")

    template = Template(
        id="TPL-002",
        name="Invoice with Today",
        html='<!doctype html><html><body><div class="t t-date">日期：<span data-bind="today"></span></div></body></html>',
        created_at="",
        updated_at="",
    )
    item = Item(id="ITM-0001", name="Product")
    repo = FakeRepo([])
    config = FakeConfig()

    output = render_template(template, item, repo, config)
    assert f'<div class="t t-date">日期：<span>{expected_today}</span></div>' in output
    assert "data-bind" not in output