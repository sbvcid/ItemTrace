"""商品頁列印對話框與「設定 → 列印」頁的行為測試（node + 假 DOM）。

驗的是「使用者實際看到什麼」，不是字串比對：

* 商品頁：預設值套用、切換範本會更新預覽、沒有 Template CRUD
* 設定頁：預設印表機／範本可讀寫、範本新增／編輯／刪除
* 兩邊共用 ui/print_dialog.js，所以對話框行為必須一致
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
ITEM_HARNESS = ROOT / "tests" / "item_dom_harness.js"
PRINTING_HARNESS = ROOT / "tests" / "printing_dom_harness.js"


def _run(harness: Path) -> dict:
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能操作頁面")
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(f"harness 執行失敗：{result.stderr}")
    rows = json.loads(result.stdout)
    broken = [row["label"] for row in rows if row.get("error")]
    assert not broken, f"harness 情境失敗：{broken}"
    return {row["label"]: row for row in rows}


def _load_translations() -> dict[str, dict[str, str]]:
    """讀 ui/i18n.js 的翻譯字典（node 解析，不用 regex 硬 parse JS）。

    頁面上的可見文字來自這份字典，所以驗「頁面上有沒有某句話」時必須
    從字典取值 —— 在測試裡寫一份中文字串的話，字典改了就會出現
    「測試通過但頁面上沒有那句話」。
    """
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能讀 ui/i18n.js 的翻譯字典")
    script = (
        "const fs=require('fs'),vm=require('vm');"
        "const s={console};vm.createContext(s);"
        "const src=fs.readFileSync(process.argv[1],'utf8');"
        "vm.runInContext(src+';globalThis.__T=I18N_TRANSLATIONS;',s);"
        "process.stdout.write(JSON.stringify(s.__T));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(UI_DIR / "i18n.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(f"讀取 i18n.js 失敗：{result.stderr}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def translations() -> dict[str, dict[str, str]]:
    return _load_translations()


@pytest.fixture(scope="module")
def item_views():
    return _run(ITEM_HARNESS)


@pytest.fixture(scope="module")
def printing_views():
    return _run(PRINTING_HARNESS)


# ----------------------------------------------------------------------
# 頁面結構
# ----------------------------------------------------------------------


def test_printing_settings_page_exists(client):
    resp = client.get("/settings/printing")
    assert resp.status_code == 200
    assert "列印設定" in resp.text
    assert "print_dialog.js" in resp.text
    assert "printing_settings.js" in resp.text


def test_templates_page_is_removed(client):
    """/templates 已經徹底移除，直接回應 404。"""
    resp = client.get("/templates")
    assert resp.status_code == 404


def test_printing_settings_page_has_the_two_regions(client):
    markup = (UI_DIR / "printing_settings.html").read_text(encoding="utf-8")
    for element_id in (
        # 列印設定
        "setting-printer", "setting-template", "save-print-settings",
        "print-settings-status", "print-settings-error",
        # 範本管理
        "template-rows", "create-template-form", "template-name",
        "template-html", "template-width", "template-height", "template-unit",
        "template-editor", "edit-id", "edit-name", "edit-html",
        "edit-width", "edit-height", "edit-unit", "edit-save", "edit-cancel",
        # 範本預覽
        "preview-item", "preview-frame", "print-open",
        # 共用列印對話框
        "print-dialog", "print-item", "print-template", "print-printer",
        "print-preview", "print-error", "print-size", "print-confirm",
        "print-close",
    ):
        assert f'id="{element_id}"' in markup, element_id


def test_item_page_print_dialog_has_no_template_crud(client):
    """商品頁只有「挑範本 → 預覽 → 列印」，沒有 Template 管理。"""
    markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    assert 'id="print-label"' in markup
    assert 'id="print-template"' in markup
    assert 'id="print-confirm"' in markup
    # 商品固定是本頁這一件，不需要商品下拉
    assert 'id="print-item"' not in markup
    # Template 的 CRUD 不該出現在商品頁
    for crud in (
        "template-editor", "create-template-form", "template-rows",
        "edit-save", "delete-template",
    ):
        assert crud not in markup, crud


def test_item_page_links_to_the_printing_settings_page(translations):
    """商品頁要引導使用者去哪裡管理範本。

    i18n 之後那段說明文字來自翻譯字典，所以這裡驗「有掛 data-i18n 的
    key，且那個 key 的譯文裡確實指到設定頁」——只驗 markup 有沒有
    /settings/printing 會漏掉「文字被抽走了、連結提示不見了」的情況。
    """
    markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    keys = re.findall(r'data-i18n="([^"]+)"', markup)
    zh = translations["zh-TW"]
    en = translations["en"]
    manage = [k for k in keys if k == "print.manage_link"]
    assert manage, "商品頁沒有指向範本管理的提示"
    assert "列印" in zh["print.manage_link"] and "範本管理" in zh["print.manage_link"]
    # 英文版那一句也要說得出該去哪裡（翻譯不能只說「需要修改範本」）
    assert "Printing" in en["print.manage_link"], en["print.manage_link"]


def _toggles_with_hidden_attribute(path: Path) -> list[str]:
    """回傳用 `hidden` 屬性（不是 .hidden class）控制顯示的 id。"""
    markup = path.read_text(encoding="utf-8")
    found: list[str] = []
    for match in re.finditer(r'id="([\w-]+)"[^>]*>', markup):
        tag = match.group(0)
        element_id = match.group(1)
        rest = tag.split(">", 1)[0]
        # hidden 必須是屬性，不能只是 class="... hidden ..."
        if re.search(r'(?:^|\s)hidden(?:\s|$|=)', rest) and "hidden" not in (
            re.search(r'class="([^"]*)"', rest).group(1).split()
            if re.search(r'class="([^"]*)"', rest) else []
        ):
            found.append(element_id)
    return found


def test_print_dialog_starts_hidden_on_both_pages():
    """對話框是按［列印］才開的，不該一進頁面就佔掉半個畫面。"""
    for name in ("item.html", "printing_settings.html"):
        assert "print-dialog" in _toggles_with_hidden_attribute(
            UI_DIR / name
        ), f"{name} 的列印對話框初始要用 hidden 屬性隱藏"


def test_template_editor_uses_the_hidden_attribute():
    """編輯面板的隱藏方式要跟 js 的切換一致。

    markup 用 `class="hidden"` 而 js 用 `.hidden = true` 切換，兩邊不同步：
    按「編輯」時 js 設 hidden=false，但 class 裡的 `hidden` 仍然讓
    `display:none` 生效，面板就是不出現。
    """
    markup = (UI_DIR / "printing_settings.html").read_text(encoding="utf-8")
    assert "template-editor" in _toggles_with_hidden_attribute(
        UI_DIR / "printing_settings.html"
    )
    tag = re.search(r'<div id="template-editor"[^>]*>', markup).group(0)
    assert "hidden" in tag
    assert 'class="card hidden"' not in tag

    source = (UI_DIR / "printing_settings.js").read_text(encoding="utf-8")
    assert 'el("template-editor").hidden = false' in source
    assert 'el("template-editor").classList' not in source, (
        "classList 與 markup 的 hidden 屬性不同步"
    )


def test_print_dialog_uses_the_hidden_attribute():
    """列印對話框同理：js 用 .hidden = true/false。"""
    source = (UI_DIR / "print_dialog.js").read_text(encoding="utf-8")
    assert 'printEl("print-dialog").hidden = false' in source
    assert 'printEl("print-dialog").hidden = true' in source
    assert "print-dialog\").classList" not in source


def test_both_pages_share_the_same_print_dialog_module():
    """兩個頁面必須用同一份對話框程式碼，不各寫一份。"""
    item_markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    printing_markup = (UI_DIR / "printing_settings.html").read_text(
        encoding="utf-8"
    )
    assert "/static/print_dialog.js" in item_markup
    assert "/static/print_dialog.js" in printing_markup
    # 舊的 templates.js 不該還帶著一份對話框
    old = UI_DIR / "templates.js"
    if old.is_file():
        assert "printBind" not in old.read_text(encoding="utf-8")


def test_print_dialog_uses_css_variables_app_css_defines():
    """變數必須是 app.css 真的定義的那組；用錯會讓整條規則失效。"""
    import re

    app_css = (UI_DIR / "app.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", app_css))
    for name in ("item.html", "printing_settings.html"):
        markup = (UI_DIR / name).read_text(encoding="utf-8")
        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", markup))
        assert used - defined == set(), (
            f"{name} 用了未定義的變數：{sorted(used - defined)}"
        )


def test_no_out_of_scope_print_features():
    """第一版不做列印歷史、佇列、排程。"""
    for name in ("print_dialog.js", "printing_settings.js", "item.js"):
        source = (UI_DIR / name).read_text(encoding="utf-8")
        for out_of_scope in (
            "print-history", "printHistory", "cancel-print", "print-queue",
            "schedule-print", "printCount", "copies",
        ):
            assert out_of_scope not in source, f"{name}: {out_of_scope}"


def test_frontend_never_uses_window_print():
    """瀏覽器的整頁列印會把商品資訊與按鈕一起印出來，不能使用。"""
    for name in ("print_dialog.js", "printing_settings.js", "item.js"):
        source = (UI_DIR / name).read_text(encoding="utf-8")
        assert "window.print" not in source, name


# ----------------------------------------------------------------------
# 商品頁列印：預設值與切換範本
# ----------------------------------------------------------------------


def test_item_print_dialog_applies_defaults(item_views):
    row = item_views["列印對話框套用預設值"]
    assert row["error"] is None
    opened = row["printOpened"]
    assert opened["dialogVisible"] is True
    assert opened["selectedTemplate"] == "TPL-0002", "要用設定裡的預設範本"
    assert opened["selectedPrinter"] == "Xprinter XP-470E", "要用設定裡的預設印表機"
    assert "輸出尺寸 100.0 × 150.0 mm" in opened["sizeText"]
    assert opened["errorText"] == ""
    assert opened["confirmDisabled"] is False


def test_item_print_dialog_falls_back_without_settings(item_views):
    """沒有設定值時退回第一個範本 + Windows 預設印表機，而不是報錯。"""
    row = item_views["列印對話框沒有設定值"]
    assert row["printOpened"]["selectedTemplate"] == "TPL-0002"
    assert row["printOpened"]["selectedPrinter"] == "Xprinter XP-470E"
    assert row["printOpened"]["errorText"] == ""


def test_item_print_preview_comes_from_print_preview_endpoint(item_views):
    """預覽必須是 /print-preview 回來的 html（= 送進 PDF 的那份）。"""
    row = item_views["列印對話框套用預設值"]
    assert row["printOpened"]["previewSrcdoc"] == (
        "<html><body><h1>PRINT:TPL-0002</h1><p>item:ITM-0001</p></body></html>"
    )
    assert any(
        c == "POST /api/templates/TPL-0002/print-preview"
        for c in row["printCalls"]
    )


def test_switching_template_refreshes_the_preview(item_views):
    """切換範本 → 重新呼叫 print-preview → 預覽換成新範本的內容。"""
    row = item_views["切換範本會更新預覽"]
    assert row["printOpened"]["previewSrcdoc"].count("PRINT:TPL-0002") == 1
    after = row["printAfter"]
    assert after["previewSrcdoc"] == (
        "<html><body><h1>PRINT:TPL-0003</h1><p>item:ITM-0001</p></body></html>"
    )
    assert after["previewCalls"] == ["TPL-0002", "TPL-0003"], "切換後要重新載入"
    assert "輸出尺寸 60.0 × 40.0 mm" in after["sizeText"]
    # 切換範本不該送印表機
    assert not any(c.endswith("/print") for c in row["printCalls"])


def test_item_page_prints_one_copy_with_the_selected_printer(item_views):
    row = item_views["商品頁送出一份列印"]
    assert row["error"] is None
    assert "POST /api/templates/TPL-0002/print" in row["printCalls"]
    assert "已送出 1 份到 Xprinter XP-470E｜100.0 × 150.0 mm" in row["printAfter"]["sizeText"]
    assert row["printAfter"]["errorText"] == ""
    assert row["printAfter"]["confirmDisabled"] is False


def test_item_print_no_printers_says_so(item_views):
    row = item_views["列印時找不到印表機"]
    assert "找不到 Windows 印表機" in row["printOpened"]["errorText"]
    assert row["printOpened"]["confirmDisabled"] is True


def test_item_print_printer_list_failure_is_distinct(item_views):
    """讀不到清單（server 缺依賴）與沒印表機（Windows 沒裝）要分開講。"""
    row = item_views["讀不到印表機清單"]
    assert "讀取印表機清單失敗" in row["printOpened"]["errorText"]
    assert row["printOpened"]["confirmDisabled"] is True


def test_item_print_preview_failure_blocks_printing(item_views):
    row = item_views["列印預覽載入失敗"]
    assert "載入列印預覽失敗" in row["printOpened"]["errorText"]
    assert row["printOpened"]["previewSrcdoc"] is None
    assert row["printOpened"]["confirmDisabled"] is True


def test_item_print_submit_failure_is_reported(item_views):
    row = item_views["列印送出失敗"]
    assert "列印失敗" in row["printAfter"]["errorText"]
    assert "找不到印表機" in row["printAfter"]["errorText"]


def test_item_print_has_no_template_crud_calls(item_views):
    """商品頁的列印不該呼叫 Template 的新增／修改／刪除。"""
    row = item_views["商品頁送出一份列印"]
    for call in row["printCalls"]:
        method = call.split(" ", 1)[0]
        assert method == "GET" or method == "POST"
        # 會改到 Template 的端點：POST /templates、PUT、DELETE
        assert not call.startswith("POST /api/templates "), call
        assert not call.startswith("PUT "), call
        assert not call.startswith("DELETE "), call


# ----------------------------------------------------------------------
# 設定頁：列印設定
# ----------------------------------------------------------------------


def test_printing_settings_loads_printers_and_templates(printing_views):
    row = printing_views["載入設定與範本"]
    assert row["unmapped"] == []
    assert row["printerOptions"] == [
        "Microsoft Print to PDF", "Xprinter XP-470E",
    ]
    assert row["selectedPrinter"] == "Xprinter XP-470E"
    assert row["templateOptions"] == ["TPL-0002", "TPL-0003"]
    assert row["selectedTemplate"] == "TPL-0003", "要用設定裡的預設範本"
    assert "GET /api/printers" in row["calls"]
    assert "GET /api/settings/printing" in row["calls"]


def test_printing_settings_lists_all_template_columns(printing_views):
    """表格要有 ID／名稱／寬／高／建立／更新／操作。"""
    row = printing_views["載入設定與範本"]
    first = row["rowTexts"][0]
    assert first[0] == "TPL-0002"
    assert first[1] == "Label 100x150"
    assert first[2] == "100"
    assert first[3] == "150"
    assert "2024" in first[4] and "2024" in first[5]
    assert "預覽" in first[6] and "編輯" in first[6] and "刪除" in first[6]


def test_printing_settings_saves_defaults(printing_views):
    row = printing_views["儲存列印設定"]
    assert row["unmapped"] == []
    assert row["postPath"] == "/api/settings/printing"
    assert row["postBody"] == {
        "printer": "Xprinter XP-470E", "template_id": "TPL-0003",
    }
    assert row["store"] == {
        "printer": "Xprinter XP-470E", "template_id": "TPL-0003",
    }
    assert row["status"] == "已儲存列印設定"


def test_printing_settings_save_failure_is_reported(printing_views):
    row = printing_views["儲存設定失敗"]
    assert "儲存失敗" in row["status"]
    assert "磁碟滿" in row["status"]


def test_printing_settings_reports_missing_printers(printing_views):
    """沒有印表機時要顯示明確訊息，不能是空白下拉視窗。"""
    row = printing_views["設定頁找不到印表機"]
    assert row["settingPrinterOption"] == ["（找不到印表機）"]
    assert "找不到 Windows 印表機" in row["dialogError"]
    assert row["confirmDisabled"] is True


# ----------------------------------------------------------------------
# 設定頁：範本管理
# ----------------------------------------------------------------------


def test_printing_settings_creates_template(printing_views):
    row = printing_views["新增範本"]
    assert row["unmapped"] == []
    assert row["postName"] == "New Label"
    assert row["postWidth"] == 80
    assert row["postHeight"] == 120
    assert row["postUnit"] == "mm"
    assert "data-bind" in row["postHtml"], "送出的是 Template 的原始 HTML"
    assert row["rowsAfter"] == row["rowsBefore"] + 1
    assert row["rowTexts"][-1][1] == "New Label"


def test_printing_settings_create_rejection_is_shown(printing_views):
    """被 validator 擋下要顯示理由，而且不能偷偷加進列表。"""
    row = printing_views["新增範本被拒"]
    assert row["alerts"]
    assert "驗證失敗" in row["alerts"][0]
    assert row["rows"] == 2


def test_printing_settings_edits_template(printing_views):
    row = printing_views["編輯範本"]
    assert row["editorVisible"] is True
    assert row["loadedId"] == "TPL-0002"
    assert row["loadedName"] == "Label 100x150"
    assert row["putPath"] == "/api/templates/TPL-0002"
    assert row["putName"] == "Renamed Label"
    assert "data-bind" in row["putHtml"]
    assert row["putWidth"] == 100
    assert row["putHeight"] == 150
    assert row["putUnit"] == "mm"
    assert row["editorHiddenAfterSave"] is True
    assert row["rowTexts"][0][1] == "Renamed Label"


def test_printing_settings_deletes_template(printing_views):
    row = printing_views["刪除範本"]
    assert row["rows"] == ["TPL-0003"]
    assert row["deletes"] == ["DELETE /api/templates/TPL-0002"]


def test_printing_settings_delete_can_be_cancelled(printing_views):
    row = printing_views["刪除但取消"]
    assert row["deletes"] == 0
    assert row["rows"] == 2


def test_printing_settings_template_preview_is_sandboxed(printing_views):
    row = printing_views["範本預覽"]
    assert row["frameCount"] == 1
    assert row["srcdoc"] == "<html><body><h1>PREVIEW:TPL-0002</h1></body></html>"
    assert row["sandbox"] == "", "不可信 HTML 必須在 sandbox iframe 裡"
    assert row["itemOptions"] == ["ITM-0001"]


def test_printing_settings_template_rows_have_no_extra_actions(printing_views):
    """第一版每列只有預覽／編輯／刪除。"""
    row = printing_views["設定頁範本列操作"]
    for labels in row["labels"]:
        assert labels == ["預覽", "編輯", "刪除"]


def test_printing_settings_says_so_when_there_are_no_templates(printing_views):
    """沒有範本時要明說，不能是空白表格。"""
    row = printing_views["沒有範本"]
    assert row["unmapped"] == []
    assert len(row["rows"]) == 1
    assert "尚無範本" in row["rows"][0][0]
    assert row["templateOptions"] == []


def test_printing_settings_preview_failure_is_reported(printing_views):
    row = printing_views["範本預覽失敗"]
    assert row["frameCount"] == 0
    assert "預覽失敗" in row["emptyText"]
    assert "Template 渲染失敗" in row["emptyText"]


def test_printing_settings_editor_loads_the_existing_template(printing_views):
    """點「編輯」要把既有內容（含尺寸，型別是字串）帶進表單。"""
    row = printing_views["編輯帶入既有內容"]
    assert row["editorVisible"] is True
    assert row["id"] == "TPL-0003"
    assert row["name"] == "Small 60x40"
    assert row["htmlHasBind"] is True
    assert row["width"] == "60"
    assert row["height"] == "40"
    assert row["unit"] == "mm"
    assert row["widthIsString"] is True, (
        "input.value 必須是字串；塞 number 進去會讓存檔時的 .trim() 拋錯"
    )


def test_printing_settings_edit_rejection_keeps_the_editor_open(printing_views):
    """編輯被 validator 擋下要顯示原因，且編輯器保持開啟讓使用者改。"""
    row = printing_views["編輯範本被拒"]
    assert row["alerts"]
    assert "驗證失敗" in row["alerts"][0]
    assert row["stillOpen"] is True
    assert row["rowName"] == "Label 100x150", "被拒的內容不能寫進列表"


# ----------------------------------------------------------------------
# 設定頁：共用列印對話框
# ----------------------------------------------------------------------


def test_printing_settings_dialog_applies_defaults(printing_views):
    row = printing_views["設定頁開啟列印對話框"]
    assert row["visible"] is True
    assert row["selectedTemplate"] == "TPL-0003", "要用設定裡的預設範本"
    assert row["selectedPrinter"] == "Xprinter XP-470E"
    assert row["itemOptions"] == ["ITM-0001"]
    assert "輸出尺寸 60.0 × 40.0 mm" in row["sizeText"]
    assert row["errorText"] == ""
    assert row["confirmDisabled"] is False
    assert row["previewSrcdoc"] == "<html><body><h1>PRINT:TPL-0003</h1></body></html>"


def test_printing_settings_dialog_falls_back_without_settings(printing_views):
    row = printing_views["沒有設定值的列印對話框"]
    assert row["selectedTemplate"] == "TPL-0002"
    assert row["selectedPrinter"] == "Xprinter XP-470E"


# ----------------------------------------------------------------------
# 兩個頁面共用同一份對話框程式碼
# ----------------------------------------------------------------------


def test_both_harnesses_report_the_same_defaults():
    """商品頁與設定頁對同一份設定必須得出同樣的預選結果。

    這是「共用同一段程式」的行為證據：兩邊都是套用 settings.template_id
    與 settings.printer，只是商品頁固定了商品、範本清單也不同。
    """
    item = json.loads(
        subprocess.run(
            ["node", str(ITEM_HARNESS)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        ).stdout
    )
    printing = json.loads(
        subprocess.run(
            ["node", str(PRINTING_HARNESS)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        ).stdout
    )
    defaults = {row["label"]: row for row in item}
    page = {row["label"]: row for row in printing}

    # 沒有設定值時，兩邊都選第一個範本 + Windows 預設印表機。
    assert defaults["列印對話框沒有設定值"]["printOpened"]["selectedTemplate"] \
        == page["沒有設定值的列印對話框"]["selectedTemplate"] == "TPL-0002"
    assert defaults["列印對話框沒有設定值"]["printOpened"]["selectedPrinter"] \
        == page["沒有設定值的列印對話框"]["selectedPrinter"] == "Xprinter XP-470E"