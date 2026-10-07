"""商品欄位 UI 語意「通用物品」測試。

目標：商品頁看起來是通用實體物品的證據與歸檔工具，而不是二手 3C 資料庫。
這裡釘住的是 **UI 顯示文字**，不是資料 —— 內部欄位名、API、AI schema、
Template 綁定、搜尋行為、列印行為全部必須與改動前完全一致。

最容易被搞壞的是「順手改資料層」：`model` 之所以還叫 `model`（而不是
`spec`），`condition` 之所以還叫 `condition`（而不是 `status`），就是因為
那會牽動 migration、API contract、既有資料與 Template 綁定。所以這支
測試把兩邊一起驗：label 是新的、內部名是舊的。

**i18n 之後**：欄位 label 不再寫在 markup 上，而是 data-i18n 指向的翻譯
key（ui/i18n.js）。所以這支測試的讀法也跟著改了 —— 它驗的是
「markup 上的 data-i18n 指向正確的 key，而那個 key 的繁體中文譯文是我們
要的通用語意」。這比直接比對字串更強：它同時保住了「翻譯存在」與
「譯文正確」。
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
SHOP_DIR = ROOT / "shop"
TOOLS_DIR = ROOT / "tools"

#: 內部欄位名。這些是資料庫與 API 的契約，不可動。
INTERNAL_FIELDS = (
    "name", "brand", "model", "category", "quantity", "condition",
    "notes", "attributes",
)

#: 欄位 → 商品頁顯示的 label（繁體中文）。
EXPECTED_LABELS = {
    "name": "名稱",
    "brand": "品牌",
    "model": "規格／型號",
    "category": "類型",
    "quantity": "數量",
    "condition": "狀態",
    "notes": "備註",
}

#: 3C／二手語境的舊 label。用字比對，出現就是回歸。
LEGACY_LABELS = ("品名", "品況")

#: 3C／二手領域的專屬詞。這些字不該出現在**商品欄位**的 UI 文字裡。
DOMAIN_SPECIFIC_TERMS = (
    "主機板", "顯示卡", "記憶體", "硬碟", "CPU", "GPU", "筆電", "二手",
)


# ----------------------------------------------------------------------
# 翻譯字典：從 ui/i18n.js 取出來看
# ----------------------------------------------------------------------

def _translations() -> dict[str, dict[str, str]]:
    """讀 ui/i18n.js 的 I18N_TRANSLATIONS。

    用 node 而不是 Python 解析：i18n.js 是 JavaScript，用 regex 硬 parse
    會在格式一改就出錯。node 已在 UI 測試裡是既有依賴（*_dom_harness.js）。
    """
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能讀 ui/i18n.js 的翻譯字典")
    # 路徑用 forward slashes 並在 node 端組成 JSON 字串，避免 Windows 的
    # 反斜線在 Python 字串與 JS 字串之間來回跳脫。
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
    return _translations()


@pytest.fixture(scope="module")
def zh(translations) -> dict[str, str]:
    return translations["zh-TW"]


def _field_label_keys() -> dict[str, str]:
    """item.js 的 FIELD_LABEL_KEYS：內部欄位名 → i18n key。"""
    source = (UI_DIR / "item.js").read_text(encoding="utf-8")
    block = re.search(
        r"const FIELD_LABEL_KEYS = \{(.*?)\n\};", source, re.S
    )
    assert block, "找不到 FIELD_LABEL_KEYS"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


def _i18n_attr_for(markup: str, field: str, attribute: str = "data-i18n") -> str | None:
    """取 markup 上 `<label for="f-X" attribute="...">` 的值。"""
    block = re.search(
        r'<div class="field"[^>]*>\s*<label for="f-' + field + r'"'
        r'([^>]*)>(.*?)</label>',
        markup,
        re.S,
    )
    assert block, f"f-{field} 沒有 label"
    found = re.search(attribute + r'="([^"]+)"', block.group(1))
    return found.group(1) if found else None


def _item_markup() -> str:
    return (UI_DIR / "item.html").read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """移除 JS 的行註解與區塊註解。

    這支測試要確認「畫面上不會出現舊詞」，但 item.js 的說明註解刻意引用
    舊 label —— 那是文件，不是行為。不排除註解的話，等於逼人刪掉維護用的
    說明。
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _strip_py_comments(source: str) -> str:
    """移除 Python 的註解與 docstring（理由同 _strip_js_comments）。"""
    import io
    import tokenize

    out: list[str] = []
    prev_type = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and prev_type in (
            tokenize.INDENT, tokenize.NEWLINE, tokenize.NL,
            tokenize.ENCODING, tokenize.DEDENT,
        ):
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = token.type
        out.append(token.string)
    return " ".join(out)


# ----------------------------------------------------------------------
# 1. 商品頁顯示新的 label
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field,label", sorted(EXPECTED_LABELS.items()))
def test_item_form_shows_the_new_label(field, label, zh):
    """商品頁表單的每個欄位都顯示通用語意的 label。

    i18n 之後這是兩段驗證：
      a. markup 上的 data-i18n 指向正確的 key
      b. 那個 key 的繁體中文譯文是我們要的字
    只驗 (a) 會漏掉「key 對但譯文是舊的二手用語」；只驗 (b) 會漏掉
    「譯文對但頁面沒有掛上去」。
    """
    key = _i18n_attr_for(_item_markup(), field)
    assert key, f"f-{field} 的 label 沒有 data-i18n"
    assert zh.get(key) == label, (
        f"{field} 對應 {key}，譯文是 {zh.get(key)!r}，應為 {label!r}"
    )


def test_item_form_still_uses_the_internal_field_ids():
    """label 改了（現在是 data-i18n），輸入框的 id 必須仍是 f-<內部欄位名>。

    id 是 JS 與 field.changed 事件的對接點，改它等於改資料契約。
    """
    markup = _item_markup()
    for field in INTERNAL_FIELDS:
        if field in ("attributes",):
            continue  # 沒有表單輸入框
        assert f'id="f-{field}"' in markup, field
        assert f'for="f-{field}"' in markup, field


def test_field_label_keys_match_the_form(zh):
    """AI 建議卡與修改歷史用的 FIELD_LABEL_KEYS 要與表單一致。"""
    keys = _field_label_keys()
    for field, label in EXPECTED_LABELS.items():
        key = keys.get(field)
        assert key, f"FIELD_LABEL_KEYS 少了 {field}"
        assert zh.get(key) == label, (
            f"FIELD_LABEL_KEYS[{field}] = {key}，譯文是 {zh.get(key)!r}，"
            f"表單用的是 {label!r}"
        )


def test_every_internal_field_has_a_ui_label():
    """每個內部欄位都要有 label —— 沒有就會直接把英文名露給使用者。

    修改歷史裡的 field.changed 事件帶的就是內部名。
    """
    keys = _field_label_keys()
    for field in INTERNAL_FIELDS:
        assert field in keys, f"{field} 沒有 UI label，歷史會露出內部名"


def test_status_and_condition_use_different_labels(zh):
    """condition（商品本身的描述）與 items.status（歸檔生命週期）
    必須是不同的文字，否則使用者分不出來。

    status 不在表單裡，但會出現在頁首與修改歷史，所以仍然需要 label。
    """
    keys = _field_label_keys()
    assert zh[keys["condition"]] == "狀態"
    status_label = zh[keys["status"]]
    assert status_label != "狀態"
    assert "商品" in status_label, (
        "items.status 的 label 要標明是「商品狀態」，與 condition 的「狀態」區開"
    )


def test_item_header_labels_the_lifecycle_status():
    """頁首顯示 items.status 時要明確標成「商品狀態」。"""
    assert "商品狀態" in _item_markup()


def test_list_page_distinguishes_lifecycle_status(zh):
    """列表頁的狀態篩選器是 items.status，不能就叫「狀態」。"""
    markup = (UI_DIR / "items.html").read_text(encoding="utf-8")
    key = re.search(
        r'id="f-status"[\s\S]{0,200}?data-i18n="([^"]+)"', markup
    )
    assert key, "狀態篩選器沒有 data-i18n"
    assert zh[key.group(1)] == "全部商品狀態"


# ----------------------------------------------------------------------
# 2. 舊的 3C／二手用語不再出現在欄位 label
# ----------------------------------------------------------------------


@pytest.mark.parametrize("legacy", LEGACY_LABELS)
def test_legacy_labels_are_gone(legacy, zh):
    """舊的二手 3C label 不該出現在任何「商品欄位」譯文裡。

    只查這幾個欄位 key，不用全域掃描：inbox 的說明文字、範本管理的按鈕
    裡出現那兩個字是合理的（只是解釋用法），全域掃描會誤判。
    """
    keys = _field_label_keys()
    for field, key in keys.items():
        assert legacy not in zh.get(key, ""), f"{field}（{key}）含「{legacy}」"

    for key in ("item.model_placeholder", "item.category_placeholder",
                "item.condition_placeholder"):
        assert legacy not in zh.get(key, ""), key


@pytest.mark.parametrize("term", DOMAIN_SPECIFIC_TERMS)
def test_domain_specific_terms_do_not_leak_into_field_labels(term, zh):
    """3C 領域的專屬詞不該出現在欄位 label / placeholder。"""
    keys = _field_label_keys()
    keys.update({
        "model_placeholder": "item.model_placeholder",
        "category_placeholder": "item.category_placeholder",
        "condition_placeholder": "item.condition_placeholder",
    })
    for field, key in keys.items():
        assert term not in zh.get(key, ""), f"{field}（{key}）含 {term}"


def test_search_placeholder_is_generic(zh):
    """搜尋說明也要通用化（但查詢欄位不變）。"""
    markup = (UI_DIR / "items.html").read_text(encoding="utf-8")
    key = re.search(r'id="q"[^>]*data-i18n-placeholder="([^"]+)"', markup).group(1)
    text = zh[key]
    assert "品名" not in text
    assert "型號" not in text
    assert "品牌" in text
    # 後端實際查的欄位是 name/brand/model/identifier，用「規格」描述 model
    assert "規格" in text


def test_list_fallback_title_is_generic(zh):
    """列表頁的「未填名稱」提示走翻譯，不是寫死在 JS。"""
    source = (UI_DIR / "list.js").read_text(encoding="utf-8")
    assert "未填名稱" not in _strip_js_comments(source), (
        "「未填名稱」應該來自 t('items.untitled')，不是寫死的字串"
    )
    assert zh["items.untitled"] == "（未填名稱）"


def test_legacy_words_are_documented_in_comments():
    """反過來確認：舊詞仍在 item.js 的註解裡被記錄為「已改掉的舊 label」。

    這是刻意保留的說明 —— 只留程式碼而沒有理由，下一個人很容易改回去。
    """
    source = (UI_DIR / "item.js").read_text(encoding="utf-8")
    assert any(word in source for word in LEGACY_LABELS), (
        "註解裡應該記錄舊 label 是什麼，以及為什麼改掉"
    )


# ----------------------------------------------------------------------
# 3-5. 資料層、AI schema、Template 綁定全部不變
# ----------------------------------------------------------------------


def test_internal_field_names_untouched_in_dataclass():
    """Python dataclass 的欄位名不可動。"""
    source = (SHOP_DIR / "models.py").read_text(encoding="utf-8")
    block = re.search(r"class Item\b.*?(?=\n@|\nclass )", source, re.S)
    assert block, "找不到 Item dataclass"
    text = block.group(0)
    for field in INTERNAL_FIELDS:
        assert f"{field}:" in text, f"Item dataclass 少了 {field}"
    names = set(re.findall(r"^\s{4}(\w+):", text, re.M))
    assert names == set(INTERNAL_FIELDS) | {"id", "status", "created_at",
                                          "updated_at"}, names


def test_api_field_names_untouched():
    """API 仍然用內部欄位名。"""
    source = (SHOP_DIR / "schemas.py").read_text(encoding="utf-8")
    for field in ("name", "brand", "model", "category", "quantity",
                  "condition", "notes"):
        assert f"{field}:" in source, f"schemas.py 少了 {field}"


def test_repository_field_names_untouched():
    source = (SHOP_DIR / "repo.py").read_text(encoding="utf-8")
    for field in ("name", "brand", "model", "category", "quantity",
                  "condition", "notes"):
        assert f'"{field}"' in source, f"repo.py 少了 {field}"


def test_schema_sql_untouched():
    """SQLite schema 的欄位名不可動（既有資料不需要 migration）。"""
    schema = (SHOP_DIR / "schema.sql").read_text(encoding="utf-8")
    items_block = re.search(
        r"CREATE TABLE IF NOT EXISTS items\s*\((.*?)\n\)", schema, re.S
    )
    assert items_block, "schema.sql 找不到 items 表"
    columns = set(re.findall(r"^\s{4}(\w+)", items_block.group(1), re.M))
    for field in INTERNAL_FIELDS:
        assert field in columns, f"items 表少了 {field}"
    assert "spec" not in columns, "不該出現 spec 欄位"
    assert "specification" not in columns
    assert "lifecycle_status" not in columns


def test_allowed_fields_untouched():
    """AI 的 ALLOWED_FIELDS 完全不動 —— suggestion field 名是既有契約。"""
    source = (SHOP_DIR / "ai_client.py").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_FIELDS\s*=\s*[\{\(](.*?)[\}\)]", source, re.S)
    assert block, "找不到 ALLOWED_FIELDS"
    assert set(re.findall(r'"([^"]+)"', block.group(1))) == {
        "name", "brand", "model", "category", "condition",
        "identifier:serial", "identifier:imei", "identifier:barcode",
    }


def test_ai_response_schema_untouched():
    """AI 的 RESPONSE_SCHEMA property 名不動。"""
    source = (SHOP_DIR / "ai_client.py").read_text(encoding="utf-8")
    for field in ("name", "brand", "model", "category", "condition"):
        assert f'"{field}"' in source, f"AI schema 少了 {field}"
    assert '"spec"' not in source


def test_template_data_bind_untouched():
    """Template 的 data-bind 用內部欄位名，不可改成 label。"""
    source = (SHOP_DIR / "template_renderer.py").read_text(encoding="utf-8")
    registry = (SHOP_DIR / "template_validator.py").read_text(encoding="utf-8")
    block = re.search(
        r"ALLOWED_BINDINGS\s*:\s*frozenset[^=]*=\s*frozenset\(\((.*?)\)\)",
        registry,
        re.S,
    )
    assert block, "找不到 ALLOWED_BINDINGS"
    allowed = set(re.findall(r'"([^"]+)"', block.group(1)))
    for field in ("name", "brand", "model", "category", "condition",
                  "quantity", "notes"):
        assert f"item.{field}" in allowed, f"data-bind 不再接受 item.{field}"
    assert not (allowed & {f"item.{label}" for label in EXPECTED_LABELS.values()})

    code = _strip_py_comments(source)
    for label in EXPECTED_LABELS.values():
        assert label not in code, f"template_renderer 出現 UI label：{label}"

    assert "model=item.model" in source
    assert "condition=item.condition" in source


def test_template_binds_internal_field_names_end_to_end(client):
    """端到端：Template 用內部欄位名綁定，資料仍填得進去。"""
    template = client.post("/api/templates", json={
        "name": "Bind",
        "html": "<!doctype html><html><body>"
                "<span data-bind=\"item.name\"></span>"
                "<span data-bind=\"item.brand\"></span>"
                "<span data-bind=\"item.model\"></span>"
                "<span data-bind=\"item.category\"></span>"
                "<span data-bind=\"item.condition\"></span>"
                "</body></html>",
        "width": 100, "height": 150, "unit": "mm",
    })
    assert template.status_code == 201, template.text
    item_id = client.post("/api/items", json={
        "name": "不鏽鋼保溫杯", "brand": "Stanley", "model": "40oz",
        "category": "容器", "condition": "已使用，外觀良好",
    }).json()["id"]

    html = client.post(
        f"/api/templates/{template.json()['id']}/preview",
        json={"item_id": item_id},
    ).json()["html"]
    for expected in ("不鏽鋼保溫杯", "Stanley", "40oz", "容器",
                     "已使用，外觀良好"):
        assert expected in html, expected
    assert "data-bind=" not in html


def test_template_validator_untouched():
    """validator 只認內部欄位名，不該知道 UI label。

    排除「類型」：validator 裡既有 `不支援的 binding 類型` 這句，那個「類型」
    指的是 binding 的種類（text / src），與商品的 category 欄位無關。
    """
    source = _strip_py_comments(
        (SHOP_DIR / "template_validator.py").read_text(encoding="utf-8")
    )
    for label in EXPECTED_LABELS.values():
        if label == "類型":
            continue
        assert label not in source, f"template_validator 出現 UI label：{label}"
    assert "binding 類型" in source


def test_no_ui_label_leaked_into_python(translations):
    """UI label 不該出現在**資料層**模組的程式碼裡。

    那是資料層，不是顯示層。註解與 docstring 不算（那是文件）。

    刻意排除的三個模組各有原因：
    - `ai_client.py`：PROMPT 是給模型看的規格書，用中文欄位說明是正確的。
    - `api.py`：`Query(description=...)` 是 OpenAPI 文件。
    - `template_validator.py`：`binding 類型` 指 binding 的種類。
    """
    labels = set(EXPECTED_LABELS.values()) | {
        translations["zh-TW"]["item.item_status_label"],
        translations["zh-TW"]["item.attributes_label"],
    }
    allowed = {"ai_client.py", "api.py", "template_validator.py"}
    offenders = []
    for path in sorted(SHOP_DIR.glob("*.py")) + sorted(TOOLS_DIR.glob("*.py")):
        if path.name in allowed:
            continue
        code = _strip_py_comments(path.read_text(encoding="utf-8"))
        for label in labels:
            if label in code:
                offenders.append(f"{path.name}: {label}")
    assert not offenders, f"UI label 出現在 Python 程式碼裡：{offenders}"


def test_new_generic_labels_appear_nowhere_in_python(translations):
    """這輪**新加**的 label（規格／型號、其他屬性）不該 anywhere 在 Python。

    「類型」與「備註」在那些檔案裡是既有文案（binding 種類、OpenAPI 描述、
    AI prompt），但「規格／型號」是本專案自訂的語意 —— 沒有任何資料層理由
    知道這個說法。
    """
    new_only = ("規格／型號", translations["en"]["item.attributes_label"])
    for path in sorted(SHOP_DIR.glob("*.py")) + sorted(TOOLS_DIR.glob("*.py")):
        code = _strip_py_comments(path.read_text(encoding="utf-8"))
        for label in new_only:
            assert label not in code, f"{path.name}: {label}"


# ----------------------------------------------------------------------
# 6-7. 搜尋與列印行為不變
# ----------------------------------------------------------------------


def test_search_still_queries_the_same_columns():
    """搜尋 SQL 查的欄位不可動（改 label 不影響查詢）。"""
    source = (SHOP_DIR / "repo.py").read_text(encoding="utf-8")
    block = re.search(r"def list_items\b.*?(?=\n    def )", source, re.S)
    assert block, "找不到 list_items（搜尋在這裡）"
    body = block.group(0)
    for field in ("name", "brand", "model", "category", "notes", "attributes"):
        assert f"i2.{field} LIKE" in body, f"搜尋不再查 {field}"
    assert "d.value LIKE" in body and "d.normalized LIKE" in body


def test_print_backend_untouched_by_labels():
    source = _strip_py_comments(
        (SHOP_DIR / "print_backend.py").read_text(encoding="utf-8")
    )
    for label in EXPECTED_LABELS.values():
        assert label not in source


def test_printing_ui_untouched_by_labels(translations):
    for name in ("print_dialog.js", "printing_settings.js"):
        source = (UI_DIR / name).read_text(encoding="utf-8")
        for legacy in LEGACY_LABELS:
            assert legacy not in _strip_js_comments(source), f"{name}: {legacy}"
        for term in DOMAIN_SPECIFIC_TERMS:
            assert term not in source, f"{name}: {term}"


# ----------------------------------------------------------------------
# 8. 既有商品資料不需 migration
# ----------------------------------------------------------------------


def test_existing_items_read_and_write_unchanged(client):
    """用既有的內部欄位名建立與讀回商品 —— 證明不需要 migration。"""
    created = client.post("/api/items", json={
        "name": "不鏽鋼保溫杯", "brand": "Stanley", "model": "40oz",
        "category": "容器", "quantity": 1, "condition": "已使用，外觀良好",
        "notes": "沒有蓋子",
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["model"] == "40oz"
    assert body["category"] == "容器"
    assert body["condition"] == "已使用，外觀良好"

    fetched = client.get(f"/api/items/{body['id']}").json()["item"]
    for field in ("name", "brand", "model", "category", "quantity",
                  "condition", "notes"):
        assert fetched[field] == body[field], field


def test_patch_with_unchanged_field_names(client):
    """PATCH 也仍用內部欄位名。"""
    created = client.post("/api/items", json={
        "name": "M4 不鏽鋼螺絲", "model": "M4 × 20mm",
        "category": "五金", "quantity": 100, "condition": "未使用",
    }).json()
    patched = client.patch(f"/api/items/{created['id']}", json={
        "condition": "外觀良好", "model": "M4 × 25mm",
    })
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["condition"] == "外觀良好"
    assert body["model"] == "M4 × 25mm"
    assert body["quantity"] == 100


# ----------------------------------------------------------------------
# 9. 通用商品語意：非 3C 資料要能正常走完整流程
# ----------------------------------------------------------------------

NON_3C_ITEMS = [
    {
        "name": "不鏽鋼保溫杯",
        "brand": "Stanley",
        "model": "40oz",          # 顯示為「規格／型號」
        "category": "容器",
        "quantity": 1,
        "condition": "已使用，外觀良好",
        "notes": "沒有蓋子",
    },
    {
        "name": "M4 不鏽鋼螺絲",
        "brand": "",                # 品牌可以留空
        "model": "M4 × 20mm",
        "category": "五金",
        "quantity": 100,
        "condition": "未使用",
        "notes": "",
    },
    {
        "name": "棉質工作手套",
        "brand": "",
        "model": "L",              # 尺寸，不是型號
        "category": "衣物",
        "quantity": 12,
        "condition": "有刮痕",
        "notes": "",
    },
]


@pytest.mark.parametrize("payload", NON_3C_ITEMS, ids=lambda p: p["name"])
def test_non_3c_items_round_trip(client, payload):
    """非 3C 商品建立 → 讀回 → 搜尋 → 依類型篩選，全都不需要特例。"""
    created = client.post("/api/items", json=payload)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    fetched = client.get(f"/api/items/{item_id}").json()["item"]
    assert fetched["name"] == payload["name"]
    assert fetched["condition"] == payload["condition"]

    found = client.get("/api/items", params={"q": payload["name"]}).json()
    assert any(row["id"] == item_id for row in found), payload["name"]

    by_category = client.get(
        "/api/items", params={"category": payload["category"]}
    ).json()
    assert any(row["id"] == item_id for row in by_category)


@pytest.mark.parametrize("payload", NON_3C_ITEMS, ids=lambda p: p["name"])
def test_non_3c_items_print(client, monkeypatch, payload):
    """非 3C 商品的列印預覽也要正常產生，且尺寸仍由範本決定。"""
    from shop import print_backend

    template = client.post("/api/templates", json={
        "name": "Label",
        "html": "<!doctype html><html><head>"
                "<style>@page { size: 100mm 150mm; margin: 0; }"
                ".l { width: 100mm; height: 150mm; }</style></head>"
                "<body><div class=\"l\"><h1 data-bind=\"item.name\"></h1>"
                "<p data-bind=\"item.model\"></p>"
                "<p data-bind=\"item.condition\"></p></div></body></html>",
        "width": 100, "height": 150, "unit": "mm",
    }).json()
    item_id = client.post("/api/items", json=payload).json()["id"]

    try:
        print_backend.find_browser()
    except print_backend.PrintUnavailableError as exc:
        pytest.skip(str(exc))

    preview = client.post(
        f"/api/templates/{template['id']}/print-preview",
        json={"item_id": item_id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert payload["name"] in body["html"]
    assert body["width_mm"] == pytest.approx(100.0, abs=0.01)
    assert body["height_mm"] == pytest.approx(150.0, abs=0.01)


def test_condition_accepts_any_free_text(client):
    """狀態欄位是自由文字 —— 不該有任何 enum 或白名單擋住使用者。"""
    for value in ("全新", "未使用", "已使用", "外觀良好", "有刮痕",
                  "待檢查", "功能正常", "M4 × 20mm", "二手 9 成新",
                  "已過保", "unknown", "0"):
        created = client.post("/api/items", json={
            "name": "測試", "condition": value,
        })
        assert created.status_code == 201, value
        assert created.json()["condition"] == value


def test_category_accepts_any_free_text(client):
    """類型欄位是自由文字。"""
    for value in ("處理器", "保溫杯", "工具", "零件", "衣物", "家具",
                  "相機", "家電", "辦公用品", "容器", "五金"):
        created = client.post("/api/items", json={
            "name": "測試", "category": value,
        })
        assert created.status_code == 201, value
        assert created.json()["category"] == value


def test_spec_placeholder_suggests_non_3c_values(zh):
    """placeholder 要提示這個欄位不只裝型號。"""
    text = zh["item.model_placeholder"]
    assert "型號" in text
    assert "尺寸" in text or "容量" in text, text


def test_category_and_condition_have_no_enum():
    """類型與狀態不能被寫成固定選項。"""
    markup = _item_markup()
    for field in ("category", "condition"):
        # label 上還有其他屬性（data-i18n），所以不能寫成 `">` 直接結尾。
        block = re.search(
            r'<div class="field"[^>]*>\s*<label for="f-' + field + r'"[^>]*>'
            r'.*?</div>',
            markup, re.S,
        )
        assert block, field
        assert "<select" not in block.group(0), f"{field} 不該是 select"
        assert "required" not in block.group(0), f"{field} 不該是必填"


# ----------------------------------------------------------------------
# 10. 假 DOM 上：label 與歷史都用新譯文
#
# 假 DOM 抓不到「data-i18n 指向錯的 key」這種錯誤（它只是把字串塞進
# 節點），所以這裡跑真正的 item.js，確認 AI 建議卡與修改歷史用的是新 label。
# 真實瀏覽器另外驗過一次，兩邊都對。
# ----------------------------------------------------------------------


def _run_item_harness() -> dict[str, dict]:
    harness = ROOT / "tests" / "item_dom_harness.js"
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


@pytest.fixture(scope="module")
def item_views():
    return _run_item_harness()


def test_suggestion_cards_use_the_new_labels(item_views, zh):
    """AI 建議卡用新的 UI label（繁體中文）。"""
    row = item_views["建議顯示資料"]
    assert row["cards"], "情境沒有產生建議卡"
    text = row["cards"][0]["text"]
    assert text.startswith(zh["item.brand_label"]), text
    for legacy in LEGACY_LABELS:
        assert legacy not in text


def test_identifier_suggestions_keep_their_own_labels(item_views, zh):
    """識別碼類建議的 label 不受商品欄位改名影響。"""
    row = item_views["接受 identifier"]
    assert row["cards"][0]["text"].startswith(zh["identifier.kind.serial"])


def test_event_history_uses_the_new_labels(item_views, zh):
    """修改歷史的欄位名稱也要用新 label。

    event.type 是資料庫的值（item.created），但顯示給人看的是譯文：
    歷史是主要 UI，不該在中���介面出現一堆英文代碼。
    """
    row = item_views["一筆 events"]
    joined = " ".join(r["text"] for r in row["eventRows"])
    assert zh["event.type.item_created"] in joined
    assert "item.created" not in joined
    for legacy in LEGACY_LABELS:
        assert legacy not in joined


def test_harness_contracts_stay_stable(item_views):
    """假 DOM 情境本身沒被這輪改動影響（回歸護欄）。"""
    for label in (
        "建議顯示資料", "識別碼縮圖與撞號連結", "接受一般欄位", "拒絕一般欄位",
        "接受 identifier", "復原按鈕只出現在可復原事件", "先打字再接受",
        "欄位儲存成功但歷史載入失敗",
    ):
        row = item_views[label]
        assert row["error"] is None, label
        assert row.get("unmapped", []) == [], label
