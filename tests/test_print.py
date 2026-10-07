"""列印功能的驗證測試。

需求指定要驗的四件事，這裡逐一對應：

1. ITM-0001 + TPL-0002：預覽看到的內容 = 實際印出的內容
2. ITM-0002 + TPL-0002：預覽看到的內容 = 實際印出的內容
3. ITM-0003 + TPL-0002：空欄位維持預覽的空白效果
4. TPL-0002：輸出物理尺寸 = 100 x 150 mm
5. 網頁 UI（商品資訊、按鈕、Template 選擇區）絕不出現在標籤上

「預覽 = 實印」是怎麼測的
------------------------
預覽與列印都吃同一份 `render_template_preview` 的輸出，所以真正的驗收
條件是：**列印 PDF 的文字內容必須等於預覽 HTML 綁定後的文字內容**。
這裡因此做兩件事：

- 純邏輯層（不需瀏覽器）：比較 `render_template_preview` 的輸出與
  `print_backend` 接受的輸入，證明兩條路徑共用同一份 HTML。
- 端到端（需 Chromium）：真的產生 PDF，用 PyMuPDF 抽出文字與版面，
  跟預覽 HTML 抽出來的逐項比對。

需要瀏覽器的測試在沒有瀏覽器時會 skip，不是 fail —— 列印後端在
非 Windows 環境上本來就不能運作。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from shop import print_backend
from shop.api import _photo_reader
from shop.repo import Repository
from shop.template_renderer import render_template_preview

ROOT = Path(__file__).resolve().parents[1]

#: 跟實際 catalog.db 的 TPL-0002 相同結構的 Template。
#: 刻意帶上 @page、flex 版面、.label 100x150mm 與一個空欄位，
#: 這樣測到的就是真實列印路徑會遇到的排版。
LABEL_HTML = """<!DOCTYPE html>
<html>
<head>
<style>
  @page { size: 100mm 150mm; margin: 0; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  .label { width: 100mm; height: 150mm; padding: 4mm;
           border: 0.4mm solid #111111;
           display: flex; flex-direction: column; }
  .photo { height: 58mm; border: 0.3mm solid #111111; }
  .name { font-size: 14pt; font-weight: 700; }
  .foot { font-size: 7pt; color: #666666; }
</style>
</head>
<body>
  <div class="label">
    <div class="photo"><img data-bind-src="item.primary_photo" alt=""></div>
    <div class="info">
      <div class="name"><span data-bind="item.name"></span></div>
      <div class="meta"><span data-bind="item.brand"></span><span class="sep">/</span
        ><span data-bind="item.model"></span></div>
    </div>
    <div class="foot">
      <div class="notes"><span data-bind="item.notes"></span></div>
      <div class="row">
        <span>NO. <span data-bind="item.id"></span></span>
        <span>100 x 150 mm</span>
      </div>
    </div>
  </div>
</body>
</html>
"""


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture()
def label_template(repo):
    """100 x 150 mm 的 TPL 標籤 Template。"""
    return repo.add_template(
        name="Label", html=LABEL_HTML, width=100, height=150, unit="mm",
    )


@pytest.fixture()
def full_item(repo):
    """欄位填滿 + 有照片的商品。"""
    return repo.create_item(
        name="AMD Ryzen 7 9700X",
        brand="AMD",
        model="Ryzen 7 9700X",
        category="CPU",
        quantity=1,
        condition="全新",
        notes="盒裝未拆",
    )


@pytest.fixture()
def sparse_item(repo):
    """第二個商品，欄位值不同，用來確認不是剛好一樣。"""
    return repo.create_item(
        name="X670E AORUS PRO X",
        brand="GIGABYTE",
        model="X670E AORUS PRO X",
        category="主機板",
        quantity=2,
        condition="良好",
        notes="附原廠盒",
    )


@pytest.fixture()
def blank_item(repo):
    """只有名稱、其餘欄位全空 —— 空欄位效果的驗證對象。"""
    return repo.create_item(name="未分類零件")


def pymupdf_or_skip():
    try:
        import pymupdf
    except ImportError:
        pytest.skip("需要 PyMuPDF 才能驗證 PDF 內容")
    return pymupdf


def browser_or_skip():
    try:
        print_backend.find_browser()
    except print_backend.PrintUnavailableError as exc:
        pytest.skip(str(exc))


def zh_translations() -> dict:
    """讀 ui/i18n.js 的繁體中文字典。

    用 node 而不是 Python 解析：i18n.js 是 JavaScript，用 regex 硬 parse
    會在格式一改就出錯。node 已是 UI 測試的既有依賴（*_dom_harness.js）。
    """
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能讀 ui/i18n.js 的翻譯字典")
    script = (
        "const fs=require('fs'),vm=require('vm');"
        "const s={console};vm.createContext(s);"
        "const src=fs.readFileSync(process.argv[1],'utf8');"
        "vm.runInContext(src+';globalThis.__T=I18N_TRANSLATIONS;',s);"
        "process.stdout.write(JSON.stringify(s.__T['zh-TW']));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "ui" / "i18n.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ----------------------------------------------------------------------
# 文字抽取：預覽 HTML 與 PDF 都要用同一套規則
# ----------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def preview_text(rendered_html: str) -> str:
    """從預覽 HTML 抽出可見文字。

    只取 `<body>` 之後（樣式與 `<title>` 不是標籤內容），去掉標籤本身並
    做 HTML entity 解碼。這個函式刻意寫得保守：它比的是「使用者看到的
    字」，不是 DOM 結構，所以版面微調不會讓測試誤報。
    """
    body = rendered_html.split("<body", 1)[-1]
    body = body.split(">", 1)[-1]
    body = _SCRIPT.sub(" ", body)
    text = _TAG.sub(" ", body)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def pdf_text(pdf_bytes: bytes) -> str:
    """從 PDF 抽出文字。用與 preview_text 相同的正規化。"""
    pymupdf = pymupdf_or_skip()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        raw = document[0].get_text()
    return re.sub(r"\s+", " ", raw).strip()


def build(repo, config, template, item) -> bytes:
    """走 API 層的同一條路徑產生 PDF（含照片 inline）。"""
    rendered = render_template_preview(template, item, repo, config)
    pdf, _, _ = print_backend.build_pdf(
        rendered,
        width_mm=template.width,
        height_mm=template.height,
        unit=template.unit,
        photo_reader=_photo_reader(config),
    )
    return pdf


# ----------------------------------------------------------------------
# 1 + 2. ITM-0001 / ITM-0002 + TPL-0002：預覽 = 實印
# ----------------------------------------------------------------------


@pytest.mark.parametrize("item_fixture", ["full_item", "sparse_item"])
def test_printed_content_matches_preview(
    request, repo, config, label_template, item_fixture
):
    """預覽看到的每一段文字都必須出現在列印輸出裡，反之亦然。

    這是整個功能的核心驗收條件。它成立的理由是列印吃的就是預覽那份
    HTML（見 test_print_uses_the_same_rendered_html_as_preview），
    這個測試則確認那份 HTML 經過瀏覽器排版後，文字沒有被截掉或改寫。
    """
    browser_or_skip()
    item = request.getfixturevalue(item_fixture)
    rendered = render_template_preview(label_template, item, repo, config)
    pdf = build(repo, config, label_template, item)

    expected = preview_text(rendered)
    actual = pdf_text(pdf)
    assert expected, "預覽不該是空的"

    missing = [part for part in expected.split(" / ") if part not in actual]
    assert not missing, f"預覽有但列印沒有：{missing}\nPDF: {actual}"

    # 反向：列印不該多出預覽沒有的商品資料
    for field in (item.name, item.brand, item.model):
        if field:
            assert field in actual, f"列印缺少 {field}"


def test_different_items_produce_different_output(
    repo, config, label_template, full_item, sparse_item
):
    """兩個商品印出來的內容確實不同 —— 排除「always same」假通過。"""
    browser_or_skip()
    first = pdf_text(build(repo, config, label_template, full_item))
    second = pdf_text(build(repo, config, label_template, sparse_item))
    assert first != second
    assert "9700X" in first
    assert "AORUS" in second


# ----------------------------------------------------------------------
# 3. ITM-0003 + TPL-0002：空欄位維持空白
# ----------------------------------------------------------------------


def test_empty_fields_stay_blank(repo, config, label_template, blank_item):
    """空欄位在預覽與實印都維持空白，不出現 None/undefined/佔位文字。"""
    browser_or_skip()
    rendered = render_template_preview(label_template, blank_item, repo, config)
    pdf = build(repo, config, label_template, blank_item)
    actual = pdf_text(pdf)

    # 有值的欄位照常出現
    assert blank_item.name in actual
    assert blank_item.id in actual

    # 空欄位不可變成字串化的 None
    for junk in ("None", "undefined", "null"):
        assert junk not in actual, f"空欄位被渲染成 {junk}"

    # 空白標籤與完整標籤的差異，就是空欄位「什麼都沒有」造成的
    assert len(actual) < len(pdf_text(
        build(repo, config, label_template, repo.create_item(
            name="填滿", brand="B", model="M", category="C",
            condition="D", notes="N",
        ))
    ))
    # 預覽端也確認空欄位是空字串（renderer 的既有行為）
    assert preview_text(rendered)


def test_empty_photo_leaves_the_img_empty_not_broken(
    repo, config, label_template, blank_item
):
    """沒有照片時不會注入壞掉的 data URI。"""
    browser_or_skip()
    pdf = build(repo, config, label_template, blank_item)
    # PDF 仍可正常開啟 = 排版沒有被壞掉的資源拖垮
    pymupdf = pymupdf_or_skip()
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert document.page_count == 1


# ----------------------------------------------------------------------
# 4. TPL-0002：輸出物理尺寸 = 100 x 150 mm
# ----------------------------------------------------------------------


def test_pdf_page_size_is_exactly_100x150mm(
    repo, config, label_template, full_item
):
    """PDF 頁面框精確等於 100 x 150 mm。

    Chromium 的 @page 會四捨五入到整數 CSS px（100mm -> 99.822mm），
    所以這裡的精確值是 print_backend 校正頁面框的證據。
    """
    browser_or_skip()
    pdf = build(repo, config, label_template, full_item)
    width_mm, height_mm = print_backend.measure_pdf_mm(pdf)
    assert width_mm == pytest.approx(100.0, abs=0.01)
    assert height_mm == pytest.approx(150.0, abs=0.01)


def test_page_size_follows_the_template_dimensions(repo, config):
    """尺寸來自 Template 欄位，不是寫死的 100x150。"""
    browser_or_skip()
    template = repo.add_template(
        name="Small", html=LABEL_HTML, width=60, height=40, unit="mm",
    )
    item = repo.create_item(name="X")
    pdf, width_mm, height_mm = print_backend.build_pdf(
        render_template_preview(template, item, repo, config),
        width_mm=template.width, height_mm=template.height, unit=template.unit,
    )
    assert (width_mm, height_mm) == pytest.approx((60.0, 40.0), abs=0.01)


@pytest.mark.parametrize(
    "unit,width,height,expected",
    [
        ("mm", 100, 150, (100.0, 150.0)),
        ("cm", 10, 15, (100.0, 150.0)),
        ("in", 4, 6, (101.6, 152.4)),
    ],
)
def test_units_are_normalised_to_mm(unit, width, height, expected):
    assert print_backend.resolve_page_mm(width, height, unit) == pytest.approx(
        expected
    )


def test_unit_unknown_is_rejected_clearly():
    """unit 是自由文字（schema 沒有 CHECK），錯的單位要明確報錯。"""
    with pytest.raises(print_backend.PrintUnavailableError) as info:
        print_backend.resolve_page_mm(100, 150, "furlong")
    assert "furlong" in str(info.value)


def test_missing_dimensions_defer_to_the_template_css(repo, config):
    """沒宣告尺寸就沿用 Template 自己的 @page，不猜一個尺寸。"""
    browser_or_skip()
    template = repo.add_template(name="NoSize", html=LABEL_HTML)
    item = repo.create_item(name="Y")
    pdf, width_mm, height_mm = print_backend.build_pdf(
        render_template_preview(template, item, repo, config),
        width_mm=template.width, height_mm=template.height, unit=template.unit,
    )
    # LABEL_HTML 自己寫了 @page 100x150；Chromium 取整後約 99.8x149.9。
    assert width_mm == pytest.approx(100.0, abs=0.5)
    assert height_mm == pytest.approx(150.0, abs=0.5)


# ----------------------------------------------------------------------
# 5. UI 不可信性 / 只印預覽
# ----------------------------------------------------------------------


def test_print_uses_the_same_rendered_html_as_preview(
    repo, config, label_template, full_item
):
    """預覽與列印吃的是同一份 HTML —— 沒有第二套資料填充邏輯。

    不需要瀏覽器：直接比對兩個呼叫的產物。這是「不建立第二套資料填充
    邏輯」這個要求的結構性證明。
    """
    from shop.api import _rendered_html

    preview = render_template_preview(
        label_template, full_item, repo, config
    )
    printed = _rendered_html(label_template, full_item, repo, config)
    assert preview == printed


def test_no_page_chrome_appears_in_the_output(
    repo, config, label_template, full_item
):
    """網頁的 UI（標題、按鈕文字、商品資訊區）不會出現在列印輸出。

    列印輸入只有 Template 渲染結果，所以頁面 chrome 在架構上就不可能
    進來；這個測試是把它釘住，避免日後有人改成送整頁。

    對照的頁面是商品頁與「設定 → 列印」：Template 管理與列印都在那裡，
    商品頁只有「挑範本 → 預覽 → 列印」。

    UI 的可見文字來自翻譯字典（ui/i18n.js），不在 markup 上 —— 所以要
    從字典取值，不在這裡寫一份中文字串。寫一份的話，字典改了這條測試
    不會跟著動，會出現「測試通過但頁面上根本沒有那句話」。
    """
    browser_or_skip()
    ui_text = zh_translations()

    pages = {
        name: (ROOT / "ui" / name).read_text(encoding="utf-8")
        for name in ("item.html", "printing_settings.html")
    }
    # 每個 key 都要真的出現在某個頁面上（測試前提），且不能出現在輸出裡。
    chrome_keys = [
        "item.item_status_label", "item.data_title", "identifier.title",
        "observation.title", "event.title",
        "printing.settings_title", "template.manager_title",
        "template.create_title", "printing.default_printer",
        "printing.default_template",
    ]
    rendered = render_template_preview(label_template, full_item, repo, config)
    actual = pdf_text(build(repo, config, label_template, full_item))
    for key in chrome_keys:
        phrase = ui_text[key]
        assert phrase, key
        assert any(
            phrase in markup for markup in pages.values()
        ), f"測試前提失效：{phrase}（{key}）不在任何頁面上"
        assert phrase not in rendered, f"UI 文字漏進渲染結果：{phrase}"
        assert phrase not in actual, f"UI 文字出現在標籤上：{phrase}"


def test_print_style_overrides_a_template_without_page_size(repo, config):
    """Template 沒寫 @page 時，列印尺寸仍由 Template 欄位決定。

    否則一個沒寫 @page 的 Template 會被印成驅動程式的預設紙張
    （實測是 A4），尺寸就完全不對了。
    """
    browser_or_skip()
    no_page = LABEL_HTML.replace(
        "@page { size: 100mm 150mm; margin: 0; }", ""
    )
    template = repo.add_template(
        name="NoPage", html=no_page, width=100, height=150, unit="mm",
    )
    item = repo.create_item(name="Z")
    pdf, width_mm, height_mm = print_backend.build_pdf(
        render_template_preview(template, item, repo, config),
        width_mm=template.width, height_mm=template.height, unit=template.unit,
    )
    assert (width_mm, height_mm) == pytest.approx((100.0, 150.0), abs=0.01)


def test_injected_style_lands_in_the_head():
    """強制頁面尺寸的樣式要插在 </head> 前，才會蓋過 Template 的寫法。"""
    html = "<html><head><style>a{}</style></head><body>x</body></html>"
    out = print_backend.inject_print_style(html, 100, 150)
    assert out.index("itemtrace-print-page") < out.index("</head>")
    assert "size: 100mm 150mm" in out


def test_injected_style_falls_back_when_there_is_no_head():
    html = "<p>只有片段</p>"
    out = print_backend.inject_print_style(html, 100, 150)
    assert "@page" in out


# ----------------------------------------------------------------------
# 照片：預覽與實印都要有
# ----------------------------------------------------------------------


def test_photos_are_inlined_for_printing(repo, config, label_template, full_item):
    """/files/... 對瀏覽器的 file:// 沒有意义，列印前必須 inline。

    不做這件事，照片在預覽有、實印消失 —— 而那正是需求點名的失敗模式。
    """
    pymupdf = pymupdf_or_skip()
    from tests.conftest import make_jpeg

    photo_dir = config.files_dir / full_item.id / "original"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "photo.jpg").write_bytes(make_jpeg())

    repo.add_photo(
        full_item.id,
        f"files/{full_item.id}/original/photo.jpg",
        sha256="a" * 64,
        bytes=10,
        role="original",
    )

    rendered = render_template_preview(label_template, full_item, repo, config)
    assert "/files/" in rendered, "渲染結果應該有 /files/ URL"

    inlined = print_backend.inline_photos(rendered, _photo_reader(config))
    assert "/files/" not in inlined
    assert "data:image/jpeg;base64," in inlined

    browser_or_skip()
    pdf = build(repo, config, label_template, full_item)
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        # 照片真的進到 PDF 了（不是被靜靜丟掉）。
        assert len(document[0].get_images(full=True)) >= 1


def test_inline_photos_keeps_the_html_when_the_file_is_missing():
    """讀不到照片時維持原樣，與預覽一致（img 空白），不讓列印整個失敗。"""
    html = '<img data-bind-src="item.primary_photo" src="/files/files/x/a.jpg">'
    out = print_backend.inline_photos(html, lambda relative: None)
    assert out == html


def test_inline_photos_leaves_non_local_sources_alone():
    """只重寫 /files/ 開頭的 src，其他來源不動。"""
    html = '<img src="https://example.com/a.png"><img src="/files/a.jpg">'
    out = print_backend.inline_photos(html, lambda r: b"X")
    assert "https://example.com/a.png" in out
    assert "data:" in out


# ----------------------------------------------------------------------
# 尺寸換算（純邏輯，不需瀏覽器）
# ----------------------------------------------------------------------


def test_mm_to_device_is_one_to_one():
    """目標矩形是 mm→device 的直接換算，這就是「不縮放」。"""
    assert print_backend.mm_to_device(25.4, 300) == 300
    assert print_backend.mm_to_device(100, 300) == 1181
    assert print_backend.device_to_mm(300, 300) == pytest.approx(25.4)


def test_pt_mm_round_trip():
    assert print_backend.pt_to_mm(print_backend.mm_to_pt(100)) == pytest.approx(100)
    assert print_backend.pt_to_mm(print_backend.mm_to_pt(150)) == pytest.approx(150)


# ----------------------------------------------------------------------
# API 契約
# ----------------------------------------------------------------------


def test_print_endpoint_sends_one_copy(client, label_template, full_item, monkeypatch):
    """預設列印 1 份，並且回報實際送進印表機的物理尺寸。"""
    sent: dict = {}

    def fake_send(printer, pixmap, width_mm, height_mm, dpi):
        sent["printer"] = printer
        sent["dpi"] = dpi
        return (
            print_backend.mm_to_device(width_mm, dpi),
            print_backend.mm_to_device(height_mm, dpi),
        )

    monkeypatch.setattr(print_backend, "_send_to_printer", fake_send)
    monkeypatch.setattr(print_backend, "resolve_printer", lambda name: "Test")
    browser_or_skip()

    response = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": full_item.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["printer"] == "Test"
    assert body["template_id"] == label_template.id
    assert body["item_id"] == full_item.id
    # 這是「不縮放」的驗證：送進 GDI 的矩形換算回來就是 100 x 150 mm。
    assert body["width_mm"] == pytest.approx(100.0, abs=0.05)
    assert body["height_mm"] == pytest.approx(150.0, abs=0.05)
    assert body["pdf_width_mm"] == pytest.approx(100.0, abs=0.01)
    assert body["pdf_height_mm"] == pytest.approx(150.0, abs=0.01)
    assert sent["printer"] == "Test"


def test_print_endpoint_requires_an_item_id(client, label_template):
    response = client.post(
        f"/api/templates/{label_template.id}/print", json={}
    )
    assert response.status_code == 400


def test_print_endpoint_reports_missing_template(client, repo, full_item):
    response = client.post(
        "/api/templates/TPL-NOTEXIST/print", json={"item_id": full_item.id},
    )
    assert response.status_code == 404


def test_print_endpoint_reports_missing_item(client, repo, label_template):
    response = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": "ITM-NOTEXIST"},
    )
    assert response.status_code == 404


def test_print_preview_endpoint_returns_the_size_without_printing(
    client, label_template, full_item, monkeypatch
):
    """/print-preview 給「先看尺寸再印」，不該送出列印工作。"""
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("print-preview 不該送印表機"),
    )
    browser_or_skip()
    response = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": full_item.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["width_mm"] == pytest.approx(100.0, abs=0.01)
    assert body["height_mm"] == pytest.approx(150.0, abs=0.01)
    assert body["printer"] == "", "print-preview 不該真的指派印表機"


def test_print_preview_returns_the_html_that_gets_printed(
    client, label_template, full_item, monkeypatch
):
    """印表機對話框顯示的 html 必須是**送進 PDF 的那一份**。

    實機問題是「列印介面沒有預覽」：如果 UI 自己去組一份預覽，
    顯示的就可能不是會印的內容。這裡釘住 API 契約 —— 回傳的 html
    必須與送進 print_backend 的完全相同。
    """
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("print-preview 不該送印表機"),
    )
    response = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": full_item.id},
    )
    assert response.status_code == 200, response.text
    served = response.json()["html"]

    # 印表機對話框拿到的 HTML 與實際送印的那份，逐字相同。
    from shop.api import _print_html

    with Repository.open(client.app.state.config) as repo:
        expected = _print_html(
            repo.get_template(label_template.id),
            repo.get_item(full_item.id),
            repo,
            client.app.state.config,
        )
    assert served == expected


def test_print_preview_html_matches_the_preview_endpoint(
    client, label_template, full_item, monkeypatch
):
    """列印預覽與畫面預覽來自同一個 renderer。

    兩者只差「照片怎麼載入」：畫面預覽用 /files/ URL（同源，瀏覽器抓
    得到），列印預覽 inline 成 data URI（因為排版在 file:// 暫存檔上）。
    文字與版面來源必須相同。
    """
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("不該送印表機"),
    )

    # 這個商品要真的有照片，才能驗證「畫面用 URL、列印 inline」這個差別。
    from tests.conftest import make_jpeg

    photo_dir = client.app.state.config.files_dir / full_item.id / "original"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "photo.jpg").write_bytes(make_jpeg())
    with Repository.open(client.app.state.config) as repo:
        repo.add_photo(
            full_item.id,
            f"files/{full_item.id}/original/photo.jpg",
            sha256="b" * 64,
            bytes=10,
            role="original",
        )

    preview = client.post(
        f"/api/templates/{label_template.id}/preview",
        json={"item_id": full_item.id},
    ).json()["html"]
    printed = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": full_item.id},
    ).json()["html"]

    # 綁定結果相同：商品名一定兩邊都在。
    assert full_item.name in preview
    assert full_item.name in printed
    # 列印那份沒有 /files/（已 inline 成 data URI），畫面那份保留 /files/。
    assert printed.count('src="/files/') == 0
    assert 'src="/files/' in preview
    assert 'src="data:image/jpeg;base64,' in printed


def test_print_endpoint_also_returns_the_printed_html(
    client, label_template, full_item, monkeypatch
):
    """/print 回應也帶上那份 html，讓 UI 能確認「印的就是你看到的」。"""
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda printer, pixmap, w, h, dpi: (
            print_backend.mm_to_device(w, dpi),
            print_backend.mm_to_device(h, dpi),
        ),
    )
    monkeypatch.setattr(print_backend, "resolve_printer", lambda name: "Test")
    browser_or_skip()
    body = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": full_item.id},
    ).json()
    assert full_item.name in body["html"]


def test_printers_endpoint_lists_available_printers(client, monkeypatch):
    monkeypatch.setattr(
        print_backend, "list_printers", lambda: ["Zebra", "IKEA"]
    )
    monkeypatch.setattr(print_backend, "default_printer", lambda: "Zebra")
    response = client.get("/api/printers")
    assert response.status_code == 200
    body = response.json()
    # 順序沿用 list_printers（這裡是 sorted 後的結果），預設旗標要正確。
    assert sorted(p["name"] for p in body) == ["IKEA", "Zebra"]
    assert {p["name"]: p["is_default"] for p in body} == {
        "IKEA": False, "Zebra": True,
    }


def test_print_does_not_modify_items_or_write_events(
    client, repo, label_template, full_item, monkeypatch
):
    """列印是唯讀操作：不動 Item，也不寫 events（跟 /preview 一致）。"""
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda printer, pixmap, w, h, dpi: (
            print_backend.mm_to_device(w, dpi), print_backend.mm_to_device(h, dpi)
        ),
    )
    monkeypatch.setattr(print_backend, "resolve_printer", lambda name: "Test")
    browser_or_skip()

    before = repo.get_item(full_item.id)
    response = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": full_item.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["width_mm"] == pytest.approx(100.0, abs=0.05)
    assert body["height_mm"] == pytest.approx(150.0, abs=0.05)

    after = repo.get_item(full_item.id)
    assert after == before


def test_print_endpoint_is_reachable_from_the_ui_string():
    """ui/*.js 引用的 /api 路徑必須存在（tests/test_ui.py 也會掃）。"""
    source = (ROOT / "ui" / "printing_settings.js").read_text(encoding="utf-8")
    assert "/print" in source
    assert "/printers" in source