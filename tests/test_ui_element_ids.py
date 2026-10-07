"""每個 ui/*.js 抓的 id 都要真的存在於對應的 HTML。

為什麼需要這支：假 DOM 的 `getElementById` 對任何 id 都會回一個 stub，
所以「元素不存在 → `el(...).addEventListener` 是 undefined」的錯誤在
harness 裡**不會**出現，只會在真瀏覽器裡炸掉整頁的頂層腳本。
實測就踩到過：`printing_settings.js` 綁了一個 markup 裡沒有的按鈕，
結果整個 IIFE 中斷，範本列表永遠不載入（畫面是空的，看不出原因）。

這個測試把 id 對照表釘下來，讓那種錯誤在 pytest 就爆。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"

#: 每支 js 由哪些 html 載入。同一支 js 只會出現在這些頁面。
#: templates.js 不在這裡：/templates 現在只是轉頁頁面，不再載入任何 script。
JS_OWNERS: dict[str, tuple[str, ...]] = {
    "item.js": ("item.html",),
    "printing_settings.js": ("printing_settings.html",),
    "print_dialog.js": ("item.html", "printing_settings.html"),
    # i18n.js 是每一頁的第一支 script（translation 必須在任何 t() 之前可用）
    "i18n.js": ("item.html", "printing_settings.html", "inbox.html",
                "items.html", "capture.html", "settings.html"),
    # api.js 只有 item.html 載入；printing_settings.js 自帶一份 api()
    # （因為它不需要 showError 那套 DOM，且要獨立於商品頁的狀態）。
    "api.js": ("item.html",),
    "inbox.js": ("inbox.html",),
    "list.js": ("items.html",),
    "capture.js": ("capture.html",),
    "settings.js": ("settings.html",),
    "design.js": ("design.html",),
}

#: 不再被任何頁面載入的舊 script。
UNOWNED_SCRIPTS: frozenset[str] = frozenset()

#: 共用模組（print_dialog.js）在某些頁面上「可以有、也可以沒有」的 id。
#: 商品頁的商品是固定的（就是該頁那一件），所以沒有商品下拉；設定頁才需要。
#: 模組用 `if (!select) return;` 處理，缺元素是合法情況。
OPTIONAL_IDS: frozenset[str] = frozenset({
    # 商品下拉：只有設定頁有
    "print-item",
    # 範本預覽的商品下拉：只有設定頁的「範本預覽」區有
    "preview-item", "preview-template-id",
})

#: 明確排除的 id。留空 —— 每個例外都該在註解裡說明理由，不該默默放行。
IGNORED_IDS: frozenset[str] = frozenset()

#: `el("div")` 是 createElement，不是找 id="div"。頁面自己的 `el(id)`
#: helper 走 getElementById，但兩種寫法共用同一個函式名，所以靠「看起來
#: 是不是 HTML 標籤」來分辨。
#:
#: 真正的 id 幾乎不可能剛好叫 "div" 或 "tr"，所以這個判斷不會漏掉任何
#: 真實的 id 檢查。
HTML_TAGS: frozenset[str] = frozenset({
    "a", "b", "br", "button", "code", "div", "em", "figure", "figcaption",
    "form", "h1", "h2", "h3", "header", "img", "input", "label", "li",
    "main", "option", "p", "section", "select", "small", "span", "strong",
    "table", "tbody", "td", "textarea", "th", "thead", "tr", "ul",
})

#: 同理要求右括號緊接著，避免抓到字串相加或字串當第二個引數。
_EL_CALL = re.compile(r"""(?:^|[^\w.$])el\(\s*["']([a-zA-Z][\w-]*)["']\s*\)""")
_PRINT_EL_CALL = re.compile(
    r"""printEl\(\s*["']([a-zA-Z][\w-]*)["']\s*\)"""
)
#: item.js 直接呼叫 document.getElementById()，不經過 el()。
#: 只抓「完整字串引數」；`getElementById("f-" + id)` 這種字串相加不屬於
#: 這裡 —— 那是 field() helper 的實作，由 test_item_fields_all_have_inputs 驗。
_GET_BY_ID = re.compile(
    r"""getElementById\(\s*["']([a-zA-Z][\w-]*)["']\s*\)"""
)
#: item.js 的 field("name") 組出 "f-" + name（商品欄位）。
#: 命名空間是 FIELDS 常數，不是出現在程式碼裡的字串，所以不從這裡收集。
FIELD_PREFIX = "f-"


def _ids_in_markup(path: Path) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', path.read_text(encoding="utf-8")))


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def _strip_comments(source: str) -> str:
    """移除註解。

    必要的話因為註解裡經常會寫到 `el("template-preview")` 這種「這裡本來
    沒有這個 id」的說明，會被誤判成真的在用。
    """
    source = _BLOCK_COMMENT.sub(" ", source)
    return _LINE_COMMENT.sub("", source)


def _ids_used(script: str, source: str) -> set[str]:
    source = _strip_comments(source)
    found = (
        set(_EL_CALL.findall(source))
        | set(_PRINT_EL_CALL.findall(source))
        | set(_GET_BY_ID.findall(source))
    )
    # `el("div")` 是 createElement，不是 getElementById("div")。
    found -= HTML_TAGS
    return {i for i in found if i not in OPTIONAL_IDS}


def test_optional_ids_are_present_where_they_are_needed():
    """OPTIONAL_IDS 要真的在某個頁面上存在，不能列了就算。

    全部都沒有的話，列進去只是為了讓檢查變鬆，沒有任何意義。
    """
    markup = "\n".join(
        (UI_DIR / page).read_text(encoding="utf-8")
        for page in ("item.html", "printing_settings.html")
    )
    for element_id in OPTIONAL_IDS:
        assert f'id="{element_id}"' in markup, (
            f"{element_id} 標成選用，但沒有任何頁面提供它"
        )


def test_shared_print_dialog_required_ids_exist_on_both_pages():
    """對話框的核心節點（範本、印表機、預覽、錯誤、送出）兩頁都要有。

    缺任何一個都會讓某一頁的列印流程靜默失效，所以明確要求兩邊都有。
    """
    required = (
        "print-dialog", "print-template", "print-printer", "print-preview",
        "print-error", "print-size", "print-confirm", "print-close",
    )
    for page in ("item.html", "printing_settings.html"):
        markup = (UI_DIR / page).read_text(encoding="utf-8")
        missing = [i for i in required if f'id="{i}"' not in markup]
        assert not missing, f"{page} 缺少列印對話框元素：{missing}"


def test_item_page_has_no_template_crud_ids():
    """商品頁不該有 Template 管理的節點。"""
    markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    for gone in (
        "create-template-form", "template-rows", "template-editor",
        "template-html", "template-name",
    ):
        assert gone not in markup, gone


def test_item_fields_all_have_inputs():
    """item.js 的 FIELDS 清單每個都要有對應的輸入框。

    field(name) 取的是 "f-" + name，所以 FIELDS 的常數陣列也要一起查 ——
    它不出現在呼叫點的引數字串裡，靠正則抓不到。
    """
    markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    source = (UI_DIR / "item.js").read_text(encoding="utf-8")
    block = re.search(r"const FIELDS = \[(.*?)\];", source, re.S)
    assert block, "找不到 FIELDS 清單"
    names = set(re.findall(r'"([\w-]+)"', block.group(1)))
    assert names, "FIELDS 是空的"
    missing = [f"{FIELD_PREFIX}{n}" for n in names if f'id="{FIELD_PREFIX}{n}"' not in markup]
    assert not missing, f"item.html 缺少欄位輸入框：{sorted(missing)}"


def test_every_script_has_a_declared_owner_page():
    """每支 ui/*.js 都必須有對應的 HTML，否則底下的檢查會漏掉它。"""
    for script in JS_OWNERS:
        assert (UI_DIR / script).is_file(), script


def test_scripts_only_exist_where_declared():
    """JS_OWNERS 過期會讓 id 檢查形同虛設，所以反向也驗一次。

    沒有被任何頁面引用的 script 要明確列在 UNOWNED_SCRIPTS，不能默默
    留在 ui/ 目錄裡 —— 那是最容易漂移的地方。
    """
    actual = {p.name for p in UI_DIR.glob("*.js")}
    declared = set(JS_OWNERS) | UNOWNED_SCRIPTS
    assert actual == declared, f"多出或缺少的 ui script：{actual ^ declared}"


def test_no_page_loads_an_unowned_script():
    """標成「不再被引用」的 script 不該又被某個頁面載入回來。"""
    for page in UI_DIR.glob("*.html"):
        markup = page.read_text(encoding="utf-8")
        for src in re.findall(r'src="/static/([^"]+)"', markup):
            assert src not in UNOWNED_SCRIPTS, (
                f"{page.name} 又載入了已無人使用的 {src}"
            )


def test_every_element_id_a_script_touches_exists():
    # i18n.js 刻意不在這份對照表裡：它是共用模組，靠 data-i18n 屬性與
    # #print-error / #print-size 這類 id 運作，而那些元素由**呼叫頁面**提供。
    # 把 i18n.js 當成「只屬於某一頁的 script」來查會誤報（它自己一個 id
    # 都不抓）。
    for script, pages in JS_OWNERS.items():
        if script == "i18n.js":
            continue
        source = (UI_DIR / script).read_text(encoding="utf-8")
        used = _ids_used(script, source)
        assert used, f"{script} 沒抓到任何 el()，檢查本身壞了"
        for page in pages:
            available = _ids_in_markup(UI_DIR / page)
            missing = used - available
            assert not missing, (
                f"{script} 用到 {page} 沒有的 id：{sorted(missing)}"
            )


def test_pages_reference_existing_scripts():
    """html 引用的 js 都要存在，否則整頁靜默失效。"""
    for page in UI_DIR.glob("*.html"):
        for src in re.findall(r'src="/static/([^"]+)"', page.read_text(
            encoding="utf-8"
        )):
            assert (UI_DIR / src).is_file(), f"{page.name} 引用了不存在的 {src}"


def test_pages_load_shared_modules_before_their_own_script():
    """共用模組必須在頁面自己的 script 之前。

    頁面 script 的頂層會呼叫共用模組的函式（printBind()），順序反了就是
    ReferenceError，整頁都不跑 —— 而且假 DOM 抓不到這類錯誤。
    """
    expected_order = {
        "item.html": ("i18n.js", "api.js", "print_dialog.js", "item.js"),
        "printing_settings.html": ("i18n.js", "print_dialog.js",
                                   "printing_settings.js"),
    }
    for page, order in expected_order.items():
        markup = (UI_DIR / page).read_text(encoding="utf-8")
        sources = re.findall(r'src="/static/([^"]+)"', markup)
        assert sources == list(order), f"{page} 的 script 順序：{sources}"


def test_i18n_is_the_first_script_on_every_page():
    """i18n.js 必須排在每一頁的第一位。

    頁面 script 的第一件事就是 i18nInit()，而 i18nApply() 要讀
    localStorage 的語言偏好。順序反了就是「先用預設語言畫一次再切換」，
    而且 t() 會在翻譯還沒載入時被呼叫 —— 這類錯誤在假 DOM 上不一定會爆，
    所以在這裡釘住順序。
    """
    for page in UI_DIR.glob("*.html"):
        sources = re.findall(
            r'src="/static/([^"]+)"', page.read_text(encoding="utf-8")
        )
        if not sources:
            continue  # 沒有 script 的靜態頁面（例如轉頁頁本來就不該有）
        assert sources[0] == "i18n.js", f"{page.name}: {sources}"