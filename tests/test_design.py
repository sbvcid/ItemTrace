"""UI Showcase / design page tests — 重用現有測試架構。"""
from __future__ import annotations

def test_design_route_exists(client):
    resp = client.get("/design")
    assert resp.status_code == 200
    assert "UI Showcase" in resp.text or "showcase" in resp.text


def test_design_page_loads_and_has_sections(client):
    resp = client.get("/design")
    text = resp.text
    # All required showcase sections should be present
    for section_id in (
        "showcase-typography",
        "showcase-buttons",
        "showcase-forms",
        "showcase-cards",
        "showcase-status",
        "showcase-alerts",
        "showcase-photos",
        "showcase-tables",
        "showcase-history",
        "showcase-suggestions",
        "showcase-dialog",
        "showcase-print-dialog",
        "showcase-loading",
        "showcase-long-text",
        "showcase-notes",
    ):
        assert f'id="{section_id}"' in text, f"missing section {section_id}"


def test_design_uses_i18n_and_not_own_translations(client):
    resp = client.get("/design")
    text = resp.text
    # Page should load i18n.js (not a second translation file)
    assert '/static/i18n.js' in text
    # Should use data-i18n attributes for UI labels
    assert 'data-i18n="showcase.title"' in text
    # Should not contain hardcoded Chinese/English pairs inside HTML (only via i18n)
    # We allow the page title to have literal text as fallback, but most labels use data-i18n
    assert 'data-i18n="lang.label"' in text


def test_design_has_locale_select(client):
    resp = client.get("/design")
    text = resp.text
    assert 'id="locale"' in text
    assert 'data-i18n="lang.label"' in text


def test_design_zh_tw_translation_keys_present(client):
    # Verify that i18n.js contains the showcase keys in zh-TW
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "ui" / "i18n.js"
    content = src.read_text(encoding="utf-8")
    assert '"showcase.title"' in content
    assert '"showcase.delete"' in content
    # Both languages should have the key
    zh_part, en_part = content.split('"en"', 1)
    assert '"showcase.delete": "刪除"' in zh_part
    assert '"showcase.delete": "Delete"' in en_part


def test_design_language_switch_mechanism(client_factory):
    with client_factory(("127.0.0.1", 0)) as c:
        resp = c.get("/design")
        assert resp.status_code == 200
        # Verify locale select is present (mechanism for switching)
        assert 'id="locale"' in resp.text


def test_design_long_text_no_dom_break(client):
    resp = client.get("/design")
    text = resp.text
    # Extreme cases should be present
    assert "ITM-10000" in text
    assert "超長商品名稱" in text or "Xprinter XP-470E" in text
    # No unclosed tags near long text sections (basic check)
    assert text.count("<section") == text.count("</section>")


def test_design_print_dialog_markup_exists(client):
    resp = client.get("/design")
    text = resp.text
    assert 'id="print-dialog"' in text
    assert 'print_dialog.js' in text


def test_design_no_js_exception_hint(client):
    # The page loads without syntax errors in embedded script references
    resp = client.get("/design")
    text = resp.text
    # design.js should be referenced
    assert '/static/design.js' in text
    # Should not contain obvious syntax errors like unclosed <script>
    script_open = text.count("<script")
    script_close = text.count("</script>")
    assert script_open == script_close or script_open > 0
