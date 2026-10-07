"""template_validator.py 的單元測試。

驗證：
- 合法 HTML/標籤/屬性通過
- 禁止標籤/屬性/URL/事件被拒
- CSS @import / 外部 url() 被拒
- 未知 binding 被拒
"""

from __future__ import annotations

import pytest

from shop.template_validator import (
    ALLOWED_TAGS,
    FORBIDDEN_TAGS,
    ALLOWED_BINDINGS,
    validate_template,
    validate_binding,
    ValidationError,
)

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

# ----------------------------------------------------------------------
# 1. 合法 Template
# ----------------------------------------------------------------------


def test_valid_template_passes():
    validate_template(VALID_HTML)  # 不拋出例外即通過


def test_minimal_valid_template():
    """最小合法 template：只需要 html/body，允許的標籤。"""
    html = """<html><body><div data-bind="item.name"></div></body></html>"""
    validate_template(html)


def test_valid_css_in_style_tag():
    """<style> 內的合法 CSS 通過。"""
    html = """<html><head><style>.a{color:red;}</style></head><body></body></html>"""
    validate_template(html)


# ----------------------------------------------------------------------
# 2. 禁止標籤
# ----------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["script", "iframe", "object", "embed", "form", "link", "base"])
def test_forbidden_tags_rejected(tag):
    html = f"""<html><body><{tag}></{tag}></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert f"禁止的標籤: <{tag}>" in str(exc.value)


def test_meta_refresh_rejected():
    """meta 不在允許清單，所以連帶 meta refresh 一起擋掉。"""
    html = """<html><head><meta http-equiv="refresh" content="0"></head><body></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止的標籤: <meta>" in str(exc.value)


def test_link_stylesheet_rejected():
    """外部樣式表 / favicon 一律拒絕（會造成外部請求）。"""
    html = """<html><head><link rel="stylesheet" href="//evil.com/x.css"></head><body></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止的標籤: <link>" in str(exc.value)


def test_allow_and_deny_lists_do_not_contradict():
    """允許清單與拒絕清單不能同時含同一個標籤。

    先前 link/meta 同時出現在兩邊，只靠「拒絕檢查在前」才安全；
    這裡把它變成結構性不變式。
    """
    assert not (ALLOWED_TAGS & FORBIDDEN_TAGS)
    # 規格點名的危險標籤必須真的不在允許清單裡
    for tag in ("script", "iframe", "object", "embed", "form", "base",
                "input", "button", "select", "textarea", "option",
                "label", "frame", "frameset", "noscript"):
        assert tag not in ALLOWED_TAGS
        assert tag in FORBIDDEN_TAGS


# ----------------------------------------------------------------------
# 3. 禁止屬性
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr",
    ["onclick", "onload", "onerror", "onmouseover", "onfocus"],
)
def test_event_handler_attributes_rejected(attr):
    html = f"""<html><body><div {attr}="alert(1)"></div></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert f"禁止的事件屬性: {attr}" in str(exc.value)


@pytest.mark.parametrize("attr", ["OnClick", "ONLOAD", "onMouseOver"])
def test_event_handlers_rejected_regardless_of_case(attr):
    """HTML 屬性名大小寫不敏感，validator 也要擋。"""
    html = f"""<html><body><div {attr}="alert(1)"></div></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止的事件屬性" in str(exc.value)


def test_unknown_attribute_rejected():
    html = """<html><body><div data-unknown="foo"></div></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "不允許的屬性: data-unknown" in str(exc.value)


def test_srcset_rejected():
    """srcset 是另一條外部資源載入路徑，不在屬性白名單。"""
    html = """<html><body><img srcset="//evil.com/a.png 1x" alt=""></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "srcset" in str(exc.value)


# ----------------------------------------------------------------------
# 4. 禁止 URL 協定
# ----------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["javascript:", "data:", "file:", "http:", "https:"])
def test_forbidden_url_schemes_rejected(scheme):
    html = f"""<html><body><a href="{scheme}//evil.com">x</a></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止的 URL 協定" in str(exc.value)


@pytest.mark.parametrize(
    "payload",
    [
        '//evil.com/x.png',      # protocol-relative
        '//evil.com',            # protocol-relative 根
        ' ///evil.com/x.png',   # 前導空白
        'HTTPS://evil.com/x.png',  # 大寫 scheme
        r'C:\Windows\win.ini',     # 絕對路徑
        '\\\\evil\\share',        # UNC
    ],
)
def test_protocol_relative_and_absolute_urls_rejected(payload):
    """protocol-relative（//host）沒有冒號，純靠 scheme 黑名單擋不到。

    這一類在 iframe srcdoc 裡會直接變成對該 origin 的請求。
    """
    html = f'<html><body><img src="{payload}" alt=""></body></html>'
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "URL" in str(exc.value)


def test_same_origin_relative_url_is_allowed():
    """同源相對路徑與錨點仍然可用（Template 內部自帶的資源）。"""
    validate_template('<html><body><img src="files/a.jpg" alt=""></body></html>')
    validate_template('<html><body><a href="#top">x</a></body></html>')


def test_data_bind_src_allows_binding_not_url():
    """data-bind-src 是 binding，不受 URL 限制；圖片由 renderer 填入。"""
    html = """<html><body><img data-bind-src="item.primary_photo"></body></html>"""
    validate_template(html)


def test_data_bind_src_rejects_text_fields():
    """只有圖片欄位能綁 data-bind-src。"""
    html = """<html><body><img data-bind-src="item.name"></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "不是可綁定的圖片欄位" in str(exc.value)


# ----------------------------------------------------------------------
# 5. CSS 限制
# ----------------------------------------------------------------------


def test_css_import_rejected():
    html = """<html><head><style>@import url("x.css");</style></head><body></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止模式" in str(exc.value)


def test_css_external_url_rejected():
    html = """<html><head><style>.a{background:url(http://x/y)}</style></head><body></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止模式" in str(exc.value)


@pytest.mark.parametrize(
    "css",
    [
        "url(data:text/html,<script>alert(1)</script>)",
        "url(//evil.com/x.png)",
        "url('//evil.com/x.png')",
        "URL(HTTPS://evil.com/x)",
        "expression(alert(1))",
        "behavior:url(x.htc)",
        "@import 'evil.css'",
    ],
)
def test_css_external_loading_forms_rejected(css):
    """data: / protocol-relative / 大寫 URL() / expression / behavior
    都是外部資源載入或執行的載體。"""
    html = f"<html><head><style>.a{{background:{css}}}</style></head><body></body></html>"
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止模式" in str(exc.value)


@pytest.mark.parametrize(
    "style",
    [
        "background:url(http://evil.com/x.png)",
        "background:url(//evil.com/x.png)",
        "background:url(data:text/html,<script>alert(1)</script>)",
    ],
)
def test_inline_style_attribute_gets_the_same_css_checks(style):
    """inline style 也是 CSS，必須跟 <style> 走同一套檢查。

    先前 validator 只掃 <style> 內容，style 屬性整條路徑沒掃，
    等於留了一個外部請求的後門。
    """
    html = f'<html><body><div style="{style}">x</div></body></html>'
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "style" in str(exc.value).lower()


def test_plain_inline_style_is_allowed():
    validate_template(
        '<html><body><div style="color: red; font-weight: bold">x</div></body></html>'
    )


def test_css_relative_url_allowed():
    """Phase 1 的 CSS 一律禁止 url()。

    圖片只能來自 item.primary_photo binding，所以 Template 沒有任何正當
    理由需要 CSS url()。全部拒絕可以一次排除 http/https/file/data/
    protocol-relative/相對路徑這一整類外部資源載入 —— 其中相對路徑在
    iframe srcdoc 裡會相對 parent 的 base 解析，等於能打到本機任何 GET。
    """
    html = """<html><head><style>.a{background:url(../secret.png)}</style></head><body></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止模式" in str(exc.value)


def test_comment_cannot_smuggle_a_url():
    """註解在 quirks mode / 老引擎下可能被當內容解析。"""
    html = "<html><body><!-- javascript:alert(1) --></body></html>"
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "禁止" in str(exc.value)


# ----------------------------------------------------------------------
# 6. Binding 驗證
# ----------------------------------------------------------------------


def test_unknown_data_bind_rejected():
    html = """<html><body><span data-bind="item.unknown"></span></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "未知的文字 binding" in str(exc.value)


def test_unknown_data_bind_src_rejected():
    html = """<html><body><img data-bind-src="item.unknown"></body></html>"""
    with pytest.raises(ValidationError) as exc:
        validate_template(html)
    assert "未知的圖片 binding" in str(exc.value)


@pytest.mark.parametrize("binding", sorted(ALLOWED_BINDINGS))
def test_all_allowed_bindings_pass(binding):
    """所有 allowlist binding 都要通過。"""
    kind = "image" if binding == "item.primary_photo" else "text"
    attr = "data-bind-src" if kind == "image" else "data-bind"
    html = f"""<html><body><span {attr}="{binding}"></span></body></html>"""
    validate_template(html)


# ----------------------------------------------------------------------
# 7. validate_binding 單元測試
# ----------------------------------------------------------------------


def test_validate_binding_text_ok():
    validate_binding("item.name", "text")
    validate_binding("item.brand", "text")


def test_validate_binding_image_ok():
    validate_binding("item.primary_photo", "image")


def test_validate_binding_unknown_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_binding("item.foo", "text")
    assert "未知的文字 binding" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        validate_binding("item.foo", "image")
    assert "未知的圖片 binding" in str(exc.value)


def test_validate_binding_invalid_kind():
    with pytest.raises(ValidationError) as exc:
        validate_binding("item.name", "invalid")
    assert "未知的 binding 類型" in str(exc.value)


# ----------------------------------------------------------------------
# 8. HTML 解析錯誤不崩潰
# ----------------------------------------------------------------------


def test_malformed_html_handled():
    """不合法 HTML 應拋出 ValidationError 而非崩潰。"""
    html = """<html><body><div><span></div></span></body></html>"""
    # HTMLParser 會自動修正巢狀，不一定會錯
    # 但我們至少要不拋出未處理例外
    try:
        validate_template(html)
    except ValidationError:
        pass  # 可接受
    except Exception as exc:
        pytest.fail(f"不應拋出非 ValidationError: {exc}")


def test_today_binding_is_allowed():
    """驗證 data-bind="today" 在 validator 通過且不接受為圖片 binding。"""
    html = '<div class="t t-date">日期：<span data-bind="today"></span></div>'
    validate_template(html)

    validate_binding("today", "text")
    with pytest.raises(ValidationError):
        validate_binding("today", "image")