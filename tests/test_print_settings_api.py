"""列印設定（`/api/settings/printing`）與範本管理頁的契約測試。

兩件事要分清楚：

1. **列印設定**（`shop/print_config.py` + `shop/settings.py`）
   預設印表機與預設範本存進 `tools/print_config.local.json`。
   刻意不驗證印表機名稱或範本 ID 是否存在 —— Windows 的印表機會被改名或
   移除，Template 也會被刪除；硬擋只會讓使用者改了設定卻存不進去。

2. **列印核心沒有被 UI 重構改變**
   `/print-preview` 與 `/print` 仍然回傳同一份 rendered HTML（送進 PDF 的
   那一份）。這組測試專門釘住這件事，避免把 UI 拆開時順手動到 backend。
"""

from __future__ import annotations

import json

import pytest

from shop import print_config, print_backend
from shop.api import _print_html
from shop.repo import Repository

LABEL_HTML = """<!doctype html>
<html><head><style>@page { size: 100mm 150mm; margin: 0; }
.label { width: 100mm; height: 150mm; }
</style></head>
<body><div class="label">
<img data-bind-src="item.primary_photo" alt="">
<h1 data-bind="item.name"></h1>
<div data-bind="item.brand"></div>
</div></body></html>
"""


@pytest.fixture()
def label_template(repo):
    return repo.add_template(
        name="Label", html=LABEL_HTML, width=100, height=150, unit="mm",
    )


@pytest.fixture()
def other_template(repo):
    return repo.add_template(
        name="Small", html=LABEL_HTML, width=60, height=40, unit="mm",
    )


@pytest.fixture()
def item(repo):
    return repo.create_item(name="AMD Ryzen 7 9700X", brand="AMD")


@pytest.fixture()
def print_config_file(tmp_path, monkeypatch):
    """把設定檔指到 tmp_path，不碰真的 tools/print_config.local.json。"""
    target = tmp_path / "print_config.local.json"
    monkeypatch.setattr(
        print_config, "config_path", lambda root=None: target
    )
    return target


@pytest.fixture()
def printers_stub(monkeypatch):
    """攔下真正送印表機的那一段。測試不該真的印東西。"""
    calls: list = []

    def fake_send(printer, pixmap, width_mm, height_mm, dpi):
        calls.append({
            "printer": printer,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "dpi": dpi,
            "pixel": (pixmap.width, pixmap.height),
        })
        return (
            print_backend.mm_to_device(width_mm, dpi),
            print_backend.mm_to_device(height_mm, dpi),
        )

    monkeypatch.setattr(print_backend, "_send_to_printer", fake_send)
    return calls


def browser_or_skip():
    try:
        print_backend.find_browser()
    except print_backend.PrintUnavailableError as exc:
        pytest.skip(str(exc))


# ----------------------------------------------------------------------
# print_config.py：檔案格式
# ----------------------------------------------------------------------


def test_missing_file_is_not_an_error(print_config_file):
    """檔案不存在只是「未設定」，不該拋錯。"""
    settings = print_config.read_settings()
    assert settings.printer is None
    assert settings.template_id is None
    assert settings.exists is False
    assert settings.error is None


def test_round_trip(print_config_file):
    print_config.save_settings("Xprinter XP-470E", "TPL-0002")
    loaded = print_config.read_settings()
    assert loaded.printer == "Xprinter XP-470E"
    assert loaded.template_id == "TPL-0002"
    assert loaded.exists is True
    assert loaded.error is None


def test_blank_values_become_none(print_config_file):
    """空白字串等同「不要預設」，不能存成空字串。"""
    print_config.save_settings("  ", "  ")
    loaded = print_config.read_settings()
    assert loaded.printer is None
    assert loaded.template_id is None


def test_malformed_file_reports_the_reason(print_config_file):
    """壞掉的 JSON 要回報原因，讓頁面能覆寫掉它 —— 不能 500。"""
    print_config_file.write_text("{ not json", encoding="utf-8")
    settings = print_config.read_settings()
    assert settings.exists is True
    assert settings.error is not None
    assert print_config_file.name in settings.error


def test_non_object_json_is_rejected(print_config_file):
    print_config_file.write_text("[1, 2]", encoding="utf-8")
    settings = print_config.read_settings()
    assert settings.error is not None


def test_written_file_is_valid_json(print_config_file):
    print_config.save_settings("Xprinter", "TPL-0002")
    data = json.loads(print_config_file.read_text(encoding="utf-8"))
    assert data == {"printer": "Xprinter", "template_id": "TPL-0002"}


def test_write_is_atomic_no_temp_left_behind(tmp_path, monkeypatch):
    """寫入用 tmp + rename，中斷時不會留下半個 JSON 檔在專案目錄。"""
    target = tmp_path / "print_config.local.json"
    monkeypatch.setattr(print_config, "config_path", lambda root=None: target)
    print_config.save_settings("A", "TPL-1")
    print_config.save_settings("B", "TPL-2")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert print_config.read_settings().printer == "B"


# ----------------------------------------------------------------------
# API：讀寫設定
# ----------------------------------------------------------------------


def test_get_settings_when_unconfigured(client, print_config_file):
    body = client.get("/api/settings/printing").json()
    assert body["printer"] is None
    assert body["template_id"] is None
    assert body["error"] is None
    assert body["config_file"].endswith("print_config.local.json")


def test_save_and_read_back(client, print_config_file):
    resp = client.post("/api/settings/printing", json={
        "printer": "Xprinter XP-470E", "template_id": "TPL-0002",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["printer"] == "Xprinter XP-470E"
    assert body["template_id"] == "TPL-0002"
    assert client.get("/api/settings/printing").json()["printer"] == "Xprinter XP-470E"


def test_saving_an_unknown_printer_is_allowed(client, print_config_file):
    """印表機可能被移除；硬擋只會讓設定存不進去。真正列印時才會報錯。"""
    resp = client.post("/api/settings/printing", json={
        "printer": "Printer That No Longer Exists", "template_id": None,
    })
    assert resp.status_code == 200
    assert resp.json()["printer"] == "Printer That No Longer Exists"


def test_saving_an_unknown_template_is_allowed(client, print_config_file):
    """範本可能被刪掉；設定要能存下來，列印時才會 404。"""
    resp = client.post("/api/settings/printing", json={
        "printer": None, "template_id": "TPL-9999",
    })
    assert resp.status_code == 200
    assert resp.json()["template_id"] == "TPL-9999"


def test_settings_are_readable_from_lan(client, print_config_file, client_factory):
    """手機要能在設定頁調整 —— 列印設定不含機密，不限制 loopback。"""
    with client_factory(("192.168.1.50", 5000)) as lan:
        resp = lan.post("/api/settings/printing", json={
            "printer": "Xprinter XP-470E", "template_id": "TPL-0002",
        })
        assert resp.status_code == 200
        assert lan.get("/api/settings/printing").json()["template_id"] == "TPL-0002"


def test_malformed_settings_file_is_reported_not_raised(
    client, print_config_file
):
    print_config_file.write_text("{oops", encoding="utf-8")
    resp = client.get("/api/settings/printing")
    assert resp.status_code == 200
    assert resp.json()["error"] is not None


# ----------------------------------------------------------------------
# 列印核心沒有被 UI 重構改變
# ----------------------------------------------------------------------


def test_print_preview_still_returns_the_printed_html(
    client, label_template, item, monkeypatch
):
    """UI 重構後，`/print-preview` 仍必須回傳送進 PDF 的那一份 HTML。"""
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("print-preview 不該送印表機"),
    )
    body = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": item.id},
    ).json()
    with Repository.open(client.app.state.config) as repo:
        expected = _print_html(
            repo.get_template(label_template.id),
            repo.get_item(item.id),
            repo,
            client.app.state.config,
        )
    assert body["html"] == expected


def test_switching_template_only_changes_the_rendered_html(
    client, label_template, other_template, item, monkeypatch
):
    """切換範本要重新渲染，且**不修改範本本身**。

    兩個範本刻意用同一份 HTML、只差尺寸欄位：這樣 rendered HTML 相同是
    正確的（同一段 Template 綁同一件商品本來就該產出同樣內容），真正要驗
    的是「回應指向的範本與尺寸跟著換了」以及「Template 沒被動到」。
    內容是否不同由下一支測試負責。
    """
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("print-preview 不該送印表機"),
    )
    before = {t.id: (t.name, t.html, t.updated_at) for t in _templates(client)}

    first = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": item.id},
    ).json()
    second = client.post(
        f"/api/templates/{other_template.id}/print-preview",
        json={"item_id": item.id},
    ).json()

    assert first["template_id"] == label_template.id
    assert second["template_id"] == other_template.id
    # 尺寸跟著範本走：100x150 vs 60x40
    assert first["width_mm"] == pytest.approx(100.0, abs=0.01)
    assert second["width_mm"] == pytest.approx(60.0, abs=0.01)
    assert second["height_mm"] == pytest.approx(40.0, abs=0.01)

    after = {t.id: (t.name, t.html, t.updated_at) for t in _templates(client)}
    assert after == before, "切換範本不該修改 Template"


def test_switching_to_a_different_template_changes_the_content(
    client, repo, label_template, item, monkeypatch
):
    """真正換一份 HTML 的範本，預覽內容必須跟著換。"""
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("print-preview 不該送印表機"),
    )
    other = repo.add_template(
        name="Different",
        html=LABEL_HTML.replace('<h1 data-bind="item.name"></h1>',
                                 '<h1 data-bind="item.brand"></h1>'),
        width=100, height=150, unit="mm",
    )
    first = client.post(
        f"/api/templates/{label_template.id}/print-preview",
        json={"item_id": item.id},
    ).json()
    second = client.post(
        f"/api/templates/{other.id}/print-preview",
        json={"item_id": item.id},
    ).json()
    assert first["html"] != second["html"]
    # 第一個範本印商品名，第二個印品牌 —— 內容確實換了。
    assert "<h1>AMD Ryzen 7 9700X</h1>" in first["html"]
    assert "<h1>AMD</h1>" in second["html"]


def _templates(client):
    with Repository.open(client.app.state.config) as repo:
        return repo.list_templates(limit=200)


def test_print_endpoint_uses_the_selected_printer(
    client, label_template, item, printers_stub
):
    """選定的印表機要被真的使用，而不是被忽略。"""
    browser_or_skip()
    body = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": item.id, "printer": "Xprinter XP-470E"},
    ).json()
    assert body["printer"] == "Xprinter XP-470E"
    assert printers_stub[-1]["printer"] == "Xprinter XP-470E"


def test_print_endpoint_still_reports_100x150(
    client, label_template, item, printers_stub
):
    browser_or_skip()
    body = client.post(
        f"/api/templates/{label_template.id}/print",
        json={"item_id": item.id, "printer": "Xprinter XP-470E"},
    ).json()
    assert body["width_mm"] == pytest.approx(100.0, abs=0.05)
    assert body["height_mm"] == pytest.approx(150.0, abs=0.05)
    assert body["pdf_width_mm"] == pytest.approx(100.0, abs=0.01)
    assert body["pdf_height_mm"] == pytest.approx(150.0, abs=0.01)


def test_printers_endpoint_still_works(client, monkeypatch):
    monkeypatch.setattr(
        print_backend, "list_printers", lambda: ["Xprinter XP-470E"]
    )
    monkeypatch.setattr(
        print_backend, "default_printer", lambda: "Xprinter XP-470E"
    )
    body = client.get("/api/printers").json()
    assert body == [{"name": "Xprinter XP-470E", "is_default": True}]


def test_existing_template_data_survives(client, repo, label_template, item):
    """既有範本（TPL-0002 那種）不能因為頁面重構而消失或改變。"""
    body = client.get(f"/api/templates/{label_template.id}").json()
    assert body["html"] == LABEL_HTML
    assert body["width"] == 100
    assert body["height"] == 150
    assert body["unit"] == "mm"