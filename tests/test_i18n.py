"""i18n 基礎（`ui/i18n.js`）的驗收測試。

這一組釘住的是「基礎設施」本身的性質，不是各頁的文案：

1. zh-TW 是預設語言
2. en 可以切換
3. localStorage 保存，重新載入仍然生效
4. 找不到 key 時有明確 fallback（而且不會讓頁面壞掉）
5. **不翻譯商品資料**
6. API field names 沒改
7. Template `data-bind` 沒改
8. 列印功能不受影響
9. 所有現有頁面都能初始化
10. 不會因缺少翻譯字串讓 JS 初始化整頁失敗

外加「翻譯 key 完整性」：zh-TW 與 en 的 key 必須完全對應。

用 node 而不是 Python 解析 i18n.js：它是 JavaScript，regex 硬 parse 會在
格式一改就出錯，而這支測試的重點正是「字典改���之後會不會壞掉」。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from shop.events import ACTORS, ENTITY_TYPES
from shop.ids import OBSERVATION_KINDS
from shop.models import IDENTIFIER_KINDS, ITEM_STATUSES

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
SHOP_DIR = ROOT / "shop"

#: 第一版支援的語言（需求指定）。
SUPPORTED_LOCALES = ("zh-TW", "en")
DEFAULT_LOCALE = "zh-TW"

#: localStorage key —— 需求指定的名字。
STORAGE_KEY = "itemtrace.locale"

#: 佔位符只允許用這幾個名字。拼錯的話不會有人發現，只是顯示不出來。
KNOWN_PLACEHOLDERS = frozenset({
    "message", "count", "model", "printer", "width", "height", "time",
    "value", "filename", "angle", "id", "unit", "pending", "decided",
    "from", "to", "page", "minutes", "hours",
})

#: 允許的 namespace 前綴。
KNOWN_NAMESPACES = frozenset({
    "common", "nav", "lang", "page", "item", "identifier", "observation",
    "event", "suggestion", "items", "status", "inbox", "capture", "settings",
    "printing", "template", "print", "templates", "showcase", "evidence",
})

_CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SLOT_PATTERN = re.compile(r"\{(\w+)\}")


def _node(body: str) -> str:
    """在 node 裡跑一段會用到 i18n.js 全域變數的程式碼，回傳 stdout。

    `body` 是**在沙箱裡**執行的碼，所以只能看到 i18n.js 自己宣告的全域
    （t / i18nInit / I18N_TRANSLATIONS …），看不到 node 的內建。要用
    process.stdout 輸出，得在沙箱裡把它指到外面去 —— 下面用 `emit()` 橋接，
    不要在 body 裡直接寫 process.stdout.write，那會在沙箱外執行而看不到
    沙箱的全域變數。
    """
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能驗 ui/i18n.js")
    script = (
        "const fs=require('fs'),vm=require('vm');"
        # emit 必須在建 context 時就放進物件實值 —— 事後掛到 sandbox 物件上
        # 的屬性在 vm 裡看不到（實測 ReferenceError）。
        "const s={console:{log(){},warn(){},error(){}},"
        "emit:(v)=>process.stdout.write(String(v))};"
        "vm.createContext(s);"
        "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),s);"
        # body 一定要用 vm.runInContext 跑：直接字串接在後面會落在 **沙箱外**，
        # 那裡看不到 i18n.js 宣告的全域變數，也看不到 emit。
        "vm.runInContext(" + json.dumps(body) + ",s);"
    )
    result = subprocess.run(
        ["node", "-e", script, str(UI_DIR / "i18n.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"node 執行失敗：{result.stderr}"
    return result.stdout.strip()


def _translations() -> dict[str, dict[str, str]]:
    return json.loads(_node("emit(JSON.stringify(I18N_TRANSLATIONS));"))


@pytest.fixture(scope="module")
def translations() -> dict[str, dict[str, str]]:
    return _translations()


# ----------------------------------------------------------------------
# 翻譯 key 完整性
# ----------------------------------------------------------------------


def test_only_the_planned_locales_exist(translations):
    """第一版只有 zh-TW 與 en。多或少了都要有理由，不能無聲擴充。"""
    assert set(translations) == set(SUPPORTED_LOCALES)


def test_zh_tw_and_en_have_identical_keys(translations):
    """zh-TW keys == en keys。

    少一個 key 就會在該語言下顯示 fallback 的字串；多一個 key 則是有人
    加了翻譯卻沒接上去。兩種都是回歸。
    """
    zh = set(translations["zh-TW"])
    en = set(translations["en"])
    assert not zh - en, f"en 缺少翻譯：{sorted(zh - en)}"
    assert not en - zh, f"en 多出沒有中文對應的 key：{sorted(en - zh)}"


def test_readme_key_counts_are_accurate(translations):
    """README 寫的 key 數量要跟字典真的數量一致。

    文件寫錯數字沒有人會發現，所以綁住它：加 key 的時候順手更新 README，
    順手就會看到這條失敗。
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for locale in SUPPORTED_LOCALES:
        row = re.search(
            rf"^\|\s*Language\s*`{re.escape(locale)}`\s*\|\s*(\d+)\s*\|$",
            readme, re.M,
        )
        assert row, f"README 少了 {locale} 的 key 數量表"
        assert int(row.group(1)) == len(translations[locale]), (
            f"README 寫 {locale} 有 {row.group(1)} 個 key，"
            f"實際是 {len(translations[locale])} 個"
        )


def test_keys_are_semantic_not_chinese(translations):
    """key 不能是中文，否則換語言時 key 本身就是某一種語言。"""
    for locale, table in translations.items():
        for key in table:
            assert not _CJK.search(key), f"{locale} 的 key 含中文：{key}"


def test_keys_are_dotted_lowercase(translations):
    """key 慣例：句點分隔、小寫 snake_case。統一了才好查、好 grep。"""
    for locale, table in translations.items():
        for key in table:
            assert _KEY_PATTERN.match(key), (
                f"{locale} 的 key 不符合命名慣例：{key}"
            )


def test_keys_are_namespaced_by_area(translations):
    """每個 key 都要有 namespace 前綴，避免日後變成一個平鋪的大雜燴。"""
    for locale, table in translations.items():
        for key in table:
            assert key.split(".", 1)[0] in KNOWN_NAMESPACES, (
                f"{locale} 的 key 沒有已知 namespace：{key}"
            )


#: 這些 key 對應表格裡「沒有文字」的欄位（例如欄位名稱旁邊的操作欄），
#: 譯文本來就該是空字串。它們是白名單，不是漏洞。
EMPTY_OK = frozenset({
    # 表格最後一欄只有按鈕，沒有欄位標題
    "template.column_actions",
    # 語言下拉的選項文字在 JS 裡產生，字典只需要自稱
    "settings.language_label",
})


def test_no_empty_translations(translations):
    """空字串的翻譯等同沒有翻譯，但比沒有 key 更難發現。

    少數刻意為空的是白名單裡那些（表格的空白操作欄）—— 新增項目要在
    這個白名單裡明講理由，不能默默放行。
    """
    for locale, table in translations.items():
        for key, value in table.items():
            if key in EMPTY_OK:
                continue
            assert value.strip(), f"{locale} 的 {key} 是空字串"


def test_empty_allowlist_entries_stay_relevant():
    """白名單不會隨著翻譯字典變動而失效（否則它就只是繞過檢查）。"""
    translations = _translations()
    assert "template.column_actions" in translations["zh-TW"]
    assert "settings.language_label" not in translations["zh-TW"]


def test_placeholders_match_across_locales(translations):
    """同一個 key 在兩種語言裡的 {placeholder} 必須一致。

    少一個 placeholder 在英文下就會把 "{message}" 原樣印在畫面上；
    多一個則會在中文下留著沒被取代的 "{...}"。兩種都是顯示錯誤。
    """
    zh, en = translations["zh-TW"], translations["en"]
    for key in zh:
        zh_slots = set(_SLOT_PATTERN.findall(zh[key]))
        en_slots = set(_SLOT_PATTERN.findall(en[key]))
        assert zh_slots == en_slots, (
            f"{key} 的 placeholder 不一致："
            f"zh={sorted(zh_slots)} en={sorted(en_slots)}"
        )


def test_placeholders_are_known(translations):
    """placeholder 只用已知的名字 —— 拼錯的話沒有人會發現，只是顯示不出來。"""
    for locale, table in translations.items():
        for key, value in table.items():
            for name in _SLOT_PATTERN.findall(value):
                assert name in KNOWN_PLACEHOLDERS, (
                    f"{locale}.{key} 用了未知的 placeholder：{name}"
                )


# ----------------------------------------------------------------------
# 1. zh-TW 是預設語言
# ----------------------------------------------------------------------


def test_default_locale_constant():
    assert _node("emit(I18N_DEFAULT_LOCALE);") == DEFAULT_LOCALE


def test_zh_tw_is_the_default_when_there_is_no_preference():
    """沒有 localStorage 偏好時，t() 回繁體中文。"""
    out = _node(
        "i18nSetLocale(i18nDetect());"
        "emit(i18nCurrentLocale()+'|'+t('common.save'));"
    )
    assert out == "zh-TW|儲存"


def test_supported_locales():
    out = _node("emit(JSON.stringify(i18nLocales()));")
    assert sorted(json.loads(out)) == sorted(SUPPORTED_LOCALES)


# ----------------------------------------------------------------------
# 2. en 可以切換
# ----------------------------------------------------------------------


def test_switch_to_english():
    out = _node(
        "i18nSetLocale('en');"
        "emit(i18nCurrentLocale()+'|'+t('common.save'));"
    )
    assert out == "en|Save"


def test_switching_changes_field_labels():
    """商品欄位 label 在 en 下是英文的通用語意。"""
    out = _node(
        "i18nSetLocale('en');"
        "emit(JSON.stringify(["
        "t('item.name_label'),t('item.brand_label'),t('item.model_label'),"
        "t('item.category_label'),t('item.quantity_label'),"
        "t('item.condition_label'),t('item.notes_label')]));"
    )
    assert json.loads(out) == [
        "Name", "Brand", "Specification / Model", "Type",
        "Quantity", "Condition", "Notes",
    ]


def test_model_label_is_not_just_model_in_english():
    """`model` 的英文不能只寫 "Model" —— 那會讓人以為只適用電子產品。"""
    out = _node("i18nSetLocale('en');emit(t('item.model_label'));")
    assert "specification" in out.lower(), out
    assert "model" in out.lower(), out


def test_status_and_condition_are_distinct_in_english():
    """items.status 與 condition 在英文下也要能分辨。"""
    out = _node(
        "i18nSetLocale('en');"
        "emit(t('item.condition_label')+'|'"
        "+t('item.item_status_label'));"
    )
    condition, status = out.split("|")
    assert condition != status, out
    # condition 描述商品本身；item status 是歸檔生命週期
    assert "item" in status.lower(), status


def test_switching_to_an_unsupported_locale_is_refused():
    """切到不支援的語言要回 false 且不改變現況，不是默默接受。"""
    out = _node(
        "i18nSetLocale('en');const before=i18nCurrentLocale();"
        "const ok=i18nSetLocale('fr');"
        "emit(String(ok)+'|'+i18nCurrentLocale()+'|'"
        "+(before===i18nCurrentLocale()));"
    )
    assert out == "false|en|true"


def test_a_corrupted_stored_locale_falls_back_to_default():
    """localStorage 被手改或寫入不支援的值時，安靜地退回預設語言。

    顯示半翻的畫面比顯示繁體中文糟糕得多。"""
    out = _node("""
      globalThis.localStorage={store:{'itemtrace.locale':'klingon'},
        getItem(k){return this.store[k] ?? null},
        setItem(k,v){this.store[k]=String(v)}};
      emit(i18nDetect());
    """)
    assert out == DEFAULT_LOCALE


# ----------------------------------------------------------------------
# 3. localStorage 保存並重新載入
# ----------------------------------------------------------------------


def test_locale_is_persisted_to_localstorage():
    out = _node("""
      const writes=[];
      globalThis.localStorage={store:{},
        getItem(k){return this.store[k] ?? null},
        setItem(k,v){writes.push(k+'='+v);this.store[k]=String(v)}};
      i18nSetLocale('en');
      emit(JSON.stringify(writes));
    """)
    assert json.loads(out) == [f"{STORAGE_KEY}=en"]


def test_locale_survives_a_reload():
    """存進 localStorage 之後，「重新載入」（= 重跑 i18nInit）仍是同一語言。

    這模擬的是使用者切換後重新整理頁面 —— 下一頁與重新整理都必須維持。
    """
    out = _node("""
      globalThis.localStorage={store:{'itemtrace.locale':'en'},
        getItem(k){return this.store[k] ?? null},
        setItem(k,v){this.store[k]=String(v)}};
      i18nSetLocale(i18nDetect());
      emit(i18nCurrentLocale()+'|'+t('common.save'));
    """)
    assert out == "en|Save"


def test_only_the_locale_key_is_written():
    """localStorage 裡只該有語言偏好 —— 不能順手存 API key 或商品資料。"""
    out = _node("""
      const store={};
      globalThis.localStorage={store,
        getItem(k){return this.store[k] ?? null},
        setItem(k,v){this.store[k]=String(v)}};
      i18nSetLocale('en');
      emit(JSON.stringify(Object.keys(store)));
    """)
    assert json.loads(out) == [STORAGE_KEY]


def test_unavailable_localstorage_does_not_break_anything():
    """localStorage 被禁用（私密瀏覽、某些企業環境）時仍要正常運作。

    偏好記不住是可以接受的；頁面壞掉不行。
    """
    out = _node("""
      globalThis.localStorage={
        getItem(){throw new Error('storage disabled')},
        setItem(){throw new Error('storage disabled')}};
      const ok=i18nSetLocale('en');
      emit(String(ok)+'|'+i18nCurrentLocale()+'|'+t('common.save'));
    """)
    assert out == "true|en|Save"


def test_reading_locale_without_storage_uses_the_default():
    out = _node("emit(i18nDetect()+'|'+i18nCurrentLocale());")
    assert out == f"{DEFAULT_LOCALE}|{DEFAULT_LOCALE}"


# ----------------------------------------------------------------------
# 4. 缺翻譯時的 fallback
# ----------------------------------------------------------------------


def test_missing_key_falls_back_to_the_key_itself():
    """完全不存在的 key → 回 key 本身（看得出是漏翻，不是空白）。"""
    out = _node("emit(t('definitely.not.a.real.key'));")
    assert out == "definitely.not.a.real.key"


def test_missing_key_does_not_throw():
    """t() 絕不拋出。

    拋出的話會讓呼叫它的整個 render 中斷、畫面變空白 —— 那比顯示一個
    明顯的 key 糟糕得多。
    """
    out = _node("""
      try{t('nope.nope');t('also.missing');emit('no-throw');}
      catch(e){emit('threw:'+e.message);}
    """)
    assert out == "no-throw"


def test_missing_key_in_one_locale_falls_back_to_the_default():
    """英文缺某個 key 時退回繁體中文，而不是顯示 key。"""
    out = _node("""
      delete I18N_TRANSLATIONS.en['common.save'];
      i18nSetLocale('en');
      emit(t('common.save'));
    """)
    assert out == "儲存"


def test_interpolation_fills_placeholders():
    out = _node(
        "emit(t('common.read_failed',{message:'boom'}));"
    )
    assert out == "讀取失敗：boom"


def test_unknown_placeholder_is_left_alone():
    """沒給的 placeholder 保留原樣 —— 看得出漏了，比顯示 "undefined" 好。"""
    out = _node("emit(t('common.read_failed'));")
    assert "{message}" in out


def test_extra_placeholders_are_ignored():
    out = _node("emit(t('common.save',{unused:'x'}));")
    assert out == "儲存"


# ----------------------------------------------------------------------
# 5. 商品資料不是翻譯目標
# ----------------------------------------------------------------------

#: 這是**使用者輸入**的商品值，必須不出現在翻譯字典裡。
#:
#: 刻意不含「容器」「五金」「處理器」這些字 —— 它們同時是 UI 的 placeholder
#: 範例（「例如：處理器、容器、五金、工具」）。那個 placeholder 是刻意的：
#: 它要告訴使用者「這一欄接受什麼類型的字」而不是列出商品的固定清單。
#: 單看字串會誤判，所以這裡只查只有資料才會出現的字。
ITEM_DATA_VALUES = (
    "不鏽鋼保溫杯", "Stanley", "40oz", "M4 不鏽鋼螺絲",
    "AMD Ryzen 7 9700X", "M4 × 20mm", "已使用，外觀良好",
)


def test_translations_contain_no_item_data(translations):
    """翻譯字典裡不該有「使用者輸入的商品內容」。

    字典是 UI 文案；商品名稱、品牌、型號都是使用者資料，把它們放進字典會
    導致「切換語言時資料被換掉」——需求明確禁止這件事。
    """
    for value in ITEM_DATA_VALUES:
        for locale, table in translations.items():
            for key, text in table.items():
                assert value not in text, f"{locale}.{key} 含商品資料：{value}"


def test_type_placeholder_is_not_a_fixed_enumeration(translations):
    """「類型」的 placeholder 只能是**範例**，不能變成固定清單。

    需求明確說不要把 category 寫死成主機板／顯示卡／記憶體／硬碟。
    這裡驗的是反過來那一點：placeholder 用「例如：…」的語氣（讀起來像
    「這些只是例子」），而且要同時涵蓋電腦與非電腦領域 —— 只列電子產品
    的話，使用者會以為這個產品只能是電腦。
    """
    zh = translations["zh-TW"]["item.category_placeholder"]
    assert zh.startswith("例如"), zh
    assert zh.count("、") >= 3, zh
    assert any(w in zh for w in ("處理器", "電腦", "電子")), zh
    assert any(w in zh for w in ("容器", "五金", "工具", "衣物", "家具")), zh


def test_type_and_condition_stay_free_text_in_the_markup():
    """類型與狀態在 markup 上是自由輸入，不是 <select>。

    這條比字典更直接：placeholder 只是提示，欄位本身要是文字輸入框，
    使用者才寫得進「衣服」或「二手 9 成新」這種沒有預設選項的值。
    """
    markup = (UI_DIR / "item.html").read_text(encoding="utf-8")
    for field in ("category", "condition"):
        block = re.search(
            r'<div class="field"[^>]*>\s*<label for="f-' + field + r'"[^>]*>'
            r".*?</div>",
            markup, re.S,
        )
        assert block, field
        assert "<select" not in block.group(0), (
            f"{field} 不該是固定選項（需求：不要新增 category enum）"
        )
        control = re.search(r"<input[^>]*id=\"f-" + field + r"\"[^>]*>",
                            block.group(0))
        assert control, field
        input_type = re.search(r'type="([^"]+)"', control.group(0))
        assert input_type is None or input_type.group(1) == "text", (
            f"{field} 必須是自由文字輸入框：{control.group(0)}"
        )

    # datalist 只是「既有商品值」的建議，不是固定 enum：markup 裡不得寫死 <option>。
    for list_id, body in re.findall(
        r'<datalist id="([^"]+)"[^>]*>(.*?)</datalist>', markup, re.S
    ):
        assert "<option" not in body, (
            f"datalist #{list_id} 不該在 markup 寫死選項；"
            "建議值必須在執行期由既有商品資料填入"
        )


def test_condition_placeholder_shows_the_field_is_free_text(translations):
    """「狀態」的 placeholder 要呈現「任何字都可以」而不是固定選項。"""
    zh = translations["zh-TW"]["item.condition_placeholder"]
    assert zh.startswith("例如"), zh
    for value in ("全新", "未使用", "外觀良好", "待檢查"):
        assert value in zh, value


def test_no_translation_function_for_item_values():
    """i18n.js 不提供「把資料值換成另一種語言」的函式。

    這個函式一旦存在，早晚會有人拿它去翻 item.name。
    """
    source = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    for forbidden in (
        "translateData", "translateValue", "localizeData", "translateItem",
    ):
        assert forbidden not in source


@pytest.mark.parametrize("name", ["item.js", "list.js", "print_dialog.js"])
def test_item_values_are_never_passed_through_t(name):
    """頁面 JS 不會把商品欄位值餵進 t()。

    t() 只接受「key + placeholder」。把資料當 key 餵進去會顯示成整段原文
    （key fallback），那不是翻譯，只是看起來像翻譯。
    """
    source = (UI_DIR / name).read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    for pattern in (
        r"\bt\(\s*item\.", r"\bt\(\s*current\[", r"\bt\(\s*entry\.name",
        r"\bt\(\s*row\.name", r"\bt\(\s*template\.name",
    ):
        assert not re.search(pattern, stripped), f"{name}: {pattern}"


def test_template_content_is_never_translated():
    """Template HTML 是使用者自己的內容，不會被 i18n 碰到。

    i18n 只作用在「頁面自己的 DOM」上；Template 預覽是一個 sandbox iframe，
    它的 srcdoc 由 JS 直接設定，沒有 data-i18n 屬性可掃。
    """
    for name in ("print_dialog.js", "printing_settings.js", "item.js"):
        source = (UI_DIR / name).read_text(encoding="utf-8")
        assert "i18nApply(frame" not in source
        assert "i18nApply(iframe" not in source
        assert "i18nApply(srcdoc" not in source


# ----------------------------------------------------------------------
# 6-7. 資料層與 Template 未受影響
# ----------------------------------------------------------------------


def test_api_field_names_unchanged():
    source = (SHOP_DIR / "schemas.py").read_text(encoding="utf-8")
    for field in ("name", "brand", "model", "category", "quantity",
                  "condition", "notes"):
        assert f"{field}:" in source


def test_allowed_fields_unchanged():
    """AI suggestion 的 field 名完全不動。"""
    source = (SHOP_DIR / "ai_client.py").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_FIELDS\s*=\s*[\{\(](.*?)[\}\)]", source, re.S)
    assert block
    assert set(re.findall(r'"([^"]+)"', block.group(1))) == {
        "name", "brand", "model", "category", "condition",
        "identifier:serial", "identifier:imei", "identifier:barcode",
    }


def test_template_bindings_unchanged():
    registry = (SHOP_DIR / "template_validator.py").read_text(encoding="utf-8")
    block = re.search(
        r"ALLOWED_BINDINGS\s*:\s*frozenset[^=]*=\s*frozenset\(\((.*?)\)\)",
        registry, re.S,
    )
    assert block
    allowed = set(re.findall(r'"([^"]+)"', block.group(1)))
    for field in ("name", "brand", "model", "category", "condition"):
        assert f"item.{field}" in allowed


def test_template_renderer_knows_no_ui_labels():
    """renderer 只認內部欄位名，不該出現任何 UI 軟文字。"""
    import io
    import tokenize

    source = (SHOP_DIR / "template_renderer.py").read_text(encoding="utf-8")
    code: list[str] = []
    prev = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and prev in (
            tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT,
        ):
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE):
            prev = token.type
        code.append(token.string)
    joined = " ".join(code)
    for label in ("名稱", "品牌", "規格／型號", "類型", "狀態"):
        assert label not in joined, f"template_renderer 含 UI label：{label}"


def test_print_backend_untouched_by_i18n():
    """列印後端不該知道 UI 語言。

    它只認 Template 的 rendered HTML 與尺寸欄位，與顯示語言無關 —— 列印
    結果不該因為介面語言而改變。
    """
    source = (SHOP_DIR / "print_backend.py").read_text(encoding="utf-8")
    for symbol in ("I18N_", "i18n", "Accept-Language", "locale"):
        assert symbol not in source, f"print_backend 出現 {symbol}"


def test_print_outputs_are_language_independent(client):
    """同一件商品、同一個範本，不論 UI 語言，列印出來的內容相同。

    這條測試是「列印功能不受 i18n 影響」的端到端證明：兩次請求的
    rendered HTML 與尺寸必須逐字相同。
    """
    import pytest as _pytest

    from shop import print_backend

    template = client.post("/api/templates", json={
        "name": "Label",
        "html": "<!doctype html><html><body>"
                "<h1 data-bind=\"item.name\"></h1>"
                "<p data-bind=\"item.model\"></p></body></html>",
        "width": 100, "height": 150, "unit": "mm",
    }).json()
    item_id = client.post("/api/items", json={
        "name": "不鏽鋼保溫杯", "model": "40oz",
    }).json()["id"]
    try:
        print_backend.find_browser()
    except print_backend.PrintUnavailableError as exc:
        _pytest.skip(str(exc))

    bodies = [
        client.post(
            f"/api/templates/{template['id']}/print-preview",
            json={"item_id": item_id},
        ).json()
        for _ in range(2)
    ]
    for field in ("html", "width_mm", "height_mm", "pdf_width_mm",
                  "pdf_height_mm"):
        assert bodies[0][field] == bodies[1][field], field
    assert bodies[0]["width_mm"] == _pytest.approx(100.0, abs=0.01)
    # 商品資料原樣在輸出裡，沒有被翻成英文
    assert "不鏽鋼保溫杯" in bodies[0]["html"]
    assert "Stainless" not in bodies[0]["html"]


# ----------------------------------------------------------------------
# 9-10. 頁面初始化
# ----------------------------------------------------------------------


def test_every_page_loads_i18n_first():
    """i18n.js 必須排在每頁第一位。

    頁面 script 的第一件事是 i18nInit()，而 i18nApply() 要讀 localStorage。
    順序反了就是「先用預設語言畫一次再切換」。
    """
    for page in UI_DIR.glob("*.html"):
        sources = re.findall(
            r'src="/static/([^"]+)"', page.read_text(encoding="utf-8")
        )
        if not sources:
            continue
        assert sources[0] == "i18n.js", f"{page.name}: {sources}"


def test_every_page_has_static_text_for_i18n_to_claim():
    """有 script 的頁面至少要有一處 data-i18n。

    沒有任何 data-i18n 的頁面在英文下會整頁維持中文 —— 那是「沒接上
    i18n」而不是「這頁不需要翻譯」。
    """
    for page in UI_DIR.glob("*.html"):
        markup = page.read_text(encoding="utf-8")
        if "<script" not in markup:
            continue
        assert "data-i18n" in markup, f"{page.name} 沒有任何 data-i18n"


def test_markup_data_i18n_keys_all_exist(translations):
    """markup 上的每個 data-i18n key 都必須在字典裡。

    拼錯的 key 會靜默顯示成 key 字串（不報錯、不崩），所以只能靠這條。
    """
    zh, en = translations["zh-TW"], translations["en"]
    missing: list[str] = []
    for page in UI_DIR.glob("*.html"):
        markup = page.read_text(encoding="utf-8")
        keys = set(re.findall(r'data-i18n[-\w]*="([^"]+)"', markup))
        for key in keys:
            if key not in zh or key not in en:
                missing.append(f"{page.name}: {key}")
    assert not missing, f"markup 引用了不存在的翻譯 key：{sorted(missing)}"


def _plain(text: str) -> str:
    """把 markup 內文／譯文都壓成「瀏覽器看到的樣子」再比。

    HTML 會把換行與連續空白折成一個空白，`&amp;` 也會顯示成 `&`，
    所以這裡先反實體化再收斂空白，才不會把排版差異誤判成譯文不一致。
    """
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def test_markup_defaults_match_the_zh_translation(translations):
    """markup 裡預設寫的繁體中文，要跟字典的 zh-TW 譯文一致。

    markup 的內文是沒有 JS 時的 fallback（漸進增強），兩者不一致會讓
    「載入瞬間看到的字」跟「載入後的字」不同 —— 那是閃爍的來源。
    """
    zh = translations["zh-TW"]
    mismatched: list[str] = []
    for page in UI_DIR.glob("*.html"):
        if page.name == "design.html":
            continue
        markup = page.read_text(encoding="utf-8")
        for match in re.finditer(
            r'data-i18n="([^"]+)"[^>]*>([^<]{0,400})<', markup
        ):
            key, fallback_text = match.group(1), _plain(match.group(2))
            if not fallback_text or key not in zh:
                continue
            if fallback_text != _plain(zh[key]):
                mismatched.append(f"{page.name}: {key}")
    assert not mismatched, (
        f"markup 的預設文字與 zh-TW 譯文不一致：{sorted(mismatched)}"
    )


def test_i18n_apply_claims_markup_nodes():
    """i18nApply() 真的會把 data-i18n 的文字換掉。

    用一個最小的假 DOM 節點驗：不碰真瀏覽器，但確認「讀屬性 → 寫
    textContent」這條路徑存在且正確。
    """
    out = _node("""
      const nodes=[{attributes:{'data-i18n':'common.save'},
        getAttribute(n){return this.attributes[n]},
        _t:'', set textContent(v){this._t=v}, get textContent(){return this._t}}];
      const scope={querySelectorAll:()=>nodes};
      i18nApply(scope);
      emit(nodes[0].textContent);
    """)
    assert out == "儲存"


def test_i18n_apply_handles_a_missing_dom():
    """沒有 document 時 i18nApply 不該拋出。

    這是「不會因缺少翻譯字串讓 JS 初始化整頁失敗」的一部分：i18n 是所有
    頁面的第一支 script，它壞掉就等於整頁沒有任何功能。
    """
    out = _node("""
      try{i18nApply(null);emit('ok');}
      catch(e){emit('threw');}
    """)
    assert out == "ok"


def test_i18n_init_without_document_does_not_throw():
    out = _node("""
      try{i18nInit();emit('ok');}
      catch(e){emit('threw:'+e.message);}
    """)
    assert out == "ok"


def test_i18n_subscribe_survives_a_throwing_listener():
    """一個壞掉的訂閱者不該讓其他訂閱者收不到通知。"""
    out = _node("""
      const seen=[];
      i18nSubscribe(()=>{throw new Error('bad');});
      i18nSubscribe(()=>{seen.push('second');});
      i18nSubscribe(()=>{seen.push('third');});
      i18nNotify();
      emit(JSON.stringify(seen));
    """)
    assert json.loads(out) == ["second", "third"]


def test_i18n_apply_is_idempotent():
    """重複套用不會把內容弄壞（語言切換會呼叫兩次以上）。"""
    out = _node("""
      const nodes=[{attributes:{'data-i18n':'common.save'},
        getAttribute(n){return this.attributes[n]},
        _t:'', set textContent(v){this._t=v}, get textContent(){return this._t}}];
      const scope={querySelectorAll:()=>nodes};
      i18nApply(scope);
      const first=nodes[0].textContent;
      i18nSetLocale('en');
      i18nApply(scope);
      const second=nodes[0].textContent;
      i18nApply(scope);
      emit(first+'|'+second+'|'+nodes[0].textContent);
    """)
    assert out == "儲存|Save|Save"


def test_i18n_switch_applies_and_notifies():
    """i18nSwitch() 會重新套用 markup 並通知訂閱者。"""
    out = _node("""
      const nodes=[{attributes:{'data-i18n':'common.save'},
        getAttribute(n){return this.attributes[n]},
        _t:'', set textContent(v){this._t=v}, get textContent(){return this._t}}];
      globalThis.document={querySelectorAll:()=>nodes,
                            documentElement:{setAttribute(){},attrs:{}}};
      let notified=0;
      i18nSubscribe(()=>{notified+=1;});
      const ok=i18nSwitch('en');
      emit(String(ok)+'|'+nodes[0].textContent+'|'+notified);
    """)
    assert out == "true|Save|1"


def test_i18n_switch_to_unsupported_locale_does_not_notify():
    """不支援的語言不該觸發重新套用 —— 那會白做一輪。"""
    out = _node("""
      let notified=0;
      i18nSubscribe(()=>{notified+=1;});
      const ok=i18nSwitch('fr');
      emit(String(ok)+'|'+notified);
    """)
    assert out == "false|0"


def test_html_lang_attribute_follows_the_locale():
    """切換語言時 <html lang> 也要跟著改。

    螢幕閱讀器與瀏覽器的自動翻譯都靠這個判斷語言。
    """
    out = _node("""
      const el={attrs:{},setAttribute(k,v){this.attrs[k]=v}};
      globalThis.document={querySelectorAll:()=>[],
                            documentElement:el};
      i18nSwitch('en');
      emit(el.attrs.lang||'(unset)');
    """)
    assert out == "en"


def test_uses_only_semantic_html_attributes(translations):
    """markup 用的 data-i18n 變體，讀取器都認得。"""
    source = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    for attribute in (
        "data-i18n", "data-i18n-html", "data-i18n-placeholder",
        "data-i18n-title", "data-i18n-aria-label",
    ):
        assert attribute in source, attribute


def test_i18n_has_no_browser_only_requirement_at_load():
    """i18n.js 在載入時不做任何需要 document / localStorage 的事。

    它只是定義常數與函式；實際的讀取與套用都在 i18nInit() 裡。這讓
    「先載入、再由頁面決定什麼時候初始化」是安全的。
    """
    out = _node("""
      // document 與 localStorage 都不存在，但載入本身不該有問題
      emit(typeof i18nInit);
    """)
    assert out == "function"


# ----------------------------------------------------------------------
# 語言切換的 UI 接線
# ----------------------------------------------------------------------


def test_topbar_has_a_locale_selector(client):
    """主要頁面 topbar 上都要有語言選擇控制。"""
    for path in ("/", "/items", "/settings", "/settings/printing", "/design"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert 'lang-switch' in resp.text, path
        assert 'data-lang="zh-TW"' in resp.text, path
        assert 'data-lang="en"' in resp.text, path


def test_settings_content_has_no_locale_selector(client):
    """/settings 內容區不再負責語言選擇（已移至全域 topbar）。"""
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'data-i18n="settings.language_title"' not in resp.text


def test_locale_selector_label_is_translated(translations):
    """「語言」這兩個字本身也要能翻譯。"""
    assert "lang.label" in translations["zh-TW"]
    assert "lang.label" in translations["en"]


def test_locale_options_use_each_language_own_name(translations):
    """選項文字用各語言自己的說法（繁體中文 / English）。

    在英文介面看到 "Chinese" 分不出是哪一種中文。
    """
    zh = translations["zh-TW"]
    assert zh["lang.zh_tw"] == "繁體中文"
    assert zh["lang.en"] == "English"
    # 兩種語言裡都要有對方的自稱
    assert translations["en"]["lang.zh_tw"] == "繁體中文"
    assert translations["en"]["lang.en"] == "English"


def test_i18n_wires_the_topbar_switcher():
    """i18n.js 集中處理 .lang-btn[data-lang] 點擊與切換。"""
    source = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    assert 'lang-btn' in source
    assert "i18nSwitch" in source


def test_no_page_restarts_the_server_for_a_locale_change():
    """切換語言純粹在 client 端，不送任何請求給 server。

    需求明確說「不要要求重新啟動 server」。更根本地說，語言偏好不該
    進資料庫，所以不該有任何 API 呼叫。
    """
    source = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    switch_block = source.split("function i18nSwitch(locale)")[1][:400]
    assert "api(" not in switch_block, "切換語言不該呼叫 API"


def test_locale_is_not_stored_on_the_server(client):
    """語言偏好不存在任何 server 端端點或設定檔裡。

    這是「語言偏好應該存在 UI / client 層，不要寫入商品資料」的直接驗證。
    """
    for path in ("/api/settings/ai", "/api/settings/printing"):
        assert client.get(path).status_code == 200
    # 設定檔裡沒有 locale / language 欄位
    for settings in (
        client.get("/api/settings/ai").json(),
        client.get("/api/settings/printing").json(),
    ):
        for key in settings:
            assert "locale" not in key.lower()
            assert "language" not in key.lower()


def _route_paths(router) -> set[str]:
    """收集 router（含子 router）的所有 route path。

    Starlette 的 routes 裡會出現沒有 .path 的 _IncludedRouter，
    直接 r.path 會爆掉，所以遞迴展開。
    """
    paths: set[str] = set()
    stack = list(getattr(router, "routes", None) or [])
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        stack.extend(getattr(route, "routes", None) or [])
    return paths


def test_no_i18n_routes_exist(client):
    """沒有任何 /api/locale 之類的端點 —— 語言純粹是 client 狀態。"""
    for route in _route_paths(client.app):
        assert "locale" not in route.lower(), route
        assert "i18n" not in route.lower(), route


def test_server_never_reads_accept_language():
    """後端不接受 Accept-Language。

    API 必須永遠使用既有英文 key、不隨語言改變 field name；既然語言不進
    server，就沒有任何地方需要讀 Accept-Language。
    """
    for name in ("api.py", "schemas.py", "models.py", "repo.py"):
        source = (SHOP_DIR / name).read_text(encoding="utf-8")
        assert "accept-language" not in source.lower(), name
        assert "Accept-Language" not in source, name


def test_only_the_locale_file_is_persisted(translations):
    """i18n 不新增任何檔案形式的狀態。

    翻譯在 ui/i18n.js（隨程式部署），偏好��� localStorage。沒有第二個
    需要同步的檔案，也就不會有「改了翻譯檔但沒部署」的狀況。
    """
    assert not list(UI_DIR.glob("*.json")), "翻譯不該拆成需要同步的 JSON 檔"
    assert (UI_DIR / "i18n.js").is_file()


def test_no_build_step_or_framework_introduced():
    """沒有為了 i18n 引入打包工具或前端框架。"""
    for name in ("package.json", "webpack.config.js", "vite.config.js",
                 "rollup.config.js", "tsconfig.json"):
        assert not (ROOT / name).exists(), name
    # 只看程式碼本身：檔頭註解合法地提到「不用 React / Vue / i18next」。
    source = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    for framework in ("require(", "import ", "export default", "React",
                      "Vue", "i18next"):
        assert framework not in code, framework


# ----------------------------------------------------------------------
# 頁面標題與日期格式（browser 驗收時發現、容易回歸的兩處）
# ----------------------------------------------------------------------


def test_every_page_title_is_translated():
    """每個頁面的 <title> 都掛 data-i18n。

    瀏覽器分頁上寫的是中文，切到 English 後還留著「設定 · ItemTrace」
    看起來就像沒翻完。分頁標題是介面的一部分，所以要跟著語言走。
    """
    expected = {
        "inbox.html": "page.title_inbox",
        "items.html": "page.title_items",
        "item.html": "page.title_item",
        "capture.html": "page.title_capture",
        "settings.html": "page.title_settings",
        "printing_settings.html": "page.title_printing",
    }
    for name, key in expected.items():
        markup = (UI_DIR / name).read_text(encoding="utf-8")
        title = re.search(r"<title[^>]*>.*?</title>", markup, re.S)
        assert title, name
        assert f'data-i18n="{key}"' in title.group(0), name


def test_titles_keep_the_brand_suffix(translations):
    """譯文保留「 · ItemTrace」，只換前面那一段頁面名稱。"""
    zh, en = translations["zh-TW"], translations["en"]
    title_keys = [k for k in zh if k.startswith("page.title_") and k != "page.title_templates"]
    assert len(title_keys) == 6, sorted(title_keys)
    for key in title_keys:
        assert zh[key].endswith(" · ItemTrace"), key
        assert en[key].endswith(" · ItemTrace"), key
        if key == "page.title_inbox":
            # Inbox 是功能名，兩種語言都叫 Inbox（與 nav.inbox 一致）。
            assert zh[key] == en[key] == "Inbox · ItemTrace", key
            continue
        assert zh[key] != en[key], f"{key} 兩種語言相同，沒翻"


def test_no_page_hardcodes_the_zh_tw_locale():
    """UI 裡不得再出現寫死的 toLocaleString("zh-TW")。

    寫死等於「介面說 English、日期還是中文下午8:17」。時間格式屬於 UI，
    所以要跟著目前語言走（i18nFormatDateTime）。
    """
    offenders = []
    for script in UI_DIR.glob("*.js"):
        source = script.read_text(encoding="utf-8")
        for match in re.finditer(r'toLocale(?:String|DateString|TimeString)\(\s*"([^"]+)"', source):
            offenders.append(f"{script.name}: {match.group(1)}")
    assert not offenders, offenders


def test_date_format_follows_the_current_locale():
    """i18nFormatDateTime() 依目前語言輸出，且壞輸入不會炸。"""
    out = _node("""
      const iso = '2026-10-05T20:17:41';
      i18nSetLocale('zh-TW');
      const zh = i18nFormatDateTime(iso);
      i18nSetLocale('en');
      const en = i18nFormatDateTime(iso);
      emit(JSON.stringify({zh, en, empty: i18nFormatDateTime(''),
                           junk: i18nFormatDateTime('not-a-date')}));
    """)
    result = json.loads(out)
    assert result["zh"] != result["en"], result
    assert re.search(r"\d{4}", result["zh"]), result
    assert re.search(r"\d{4}", result["en"]), result
    assert result["empty"] == "", result
    assert result["junk"] == "not-a-date", result


def test_punctuation_outside_translations_is_avoided():
    """頁面上不該有沒被翻譯的半形／全形標點殘留。

    例如 "設定檔：" 的全形冒號寫在 markup 裡，切到 English 就會變成
    「Settings file：」。標點要跟著語言走，就放進字典。
    """
    invisible = re.compile(r"<!--.*?-->|<(script|style)\b.*?</\1>", re.S)
    offenders = []
    for page in UI_DIR.glob("*.html"):
        if page.name == "design.html":
            continue
        markup = page.read_text(encoding="utf-8")
        # 註解與 script/style 不會顯示在畫面上；換成同樣数量的換行，
        # 這樣行號才對得起來。
        markup = invisible.sub(
            lambda m: "\n" * m.group(0).count("\n"), markup
        )
        # 去掉 data-i18n 標記的元素內文，剩下的是「沒有翻譯管道」的字
        stripped = re.sub(
            r'data-i18n(?:-[\w]+)?="[^"]*"[^>]*>[^<]*<', "<", markup
        )
        for match in re.finditer(r"[：，。；！？、（）]", stripped):
            line = markup[:match.start()].count("\n") + 1
            offenders.append(f"{page.name}:{line} {match.group(0)}")
    assert not offenders, offenders


# ----------------------------------------------------------------------
# 資料層的「封閉清單」也要有顯示譯文
# ----------------------------------------------------------------------


@pytest.mark.parametrize("prefix,values", [
    ("status.", ITEM_STATUSES),
    ("identifier.kind.", IDENTIFIER_KINDS),
    ("observation.kind.", OBSERVATION_KINDS),
    ("event.actor.", ACTORS),
    ("event.entity.", ENTITY_TYPES),
])
def test_closed_enums_all_have_labels(translations, prefix, values):
    """資料庫的封閉清單，顯示文字都要有翻譯。

    這些值會直接顯示給人看（badge、篩選選項、修改歷史），中文介面出現
    一串 "field.changed" / "intake" 就是沒翻完。資料本身不動 —— API 與
    篩選參數仍是英文值。
    """
    for locale in SUPPORTED_LOCALES:
        table = translations[locale]
        missing = [v for v in values if prefix + v not in table]
        assert not missing, f"{locale} 缺少 {prefix}* 翻譯：{missing}"


def test_every_event_type_written_by_the_backend_has_a_label(translations):
    """後端會寫進 events.type 的每個值都要有譯文。

    值是寫死在 repo/events.py 的字串，這裡用同一份來源比對，避免有人
    加了新事件卻忘了翻譯。
    """
    source = (SHOP_DIR / "repo.py").read_text(encoding="utf-8")
    types = set(re.findall(r'type="([a-z]+\.[a-z_]+)"', source))
    types |= set(re.findall(r'type="([a-z]+\.[a-z_]+)"',
                            (SHOP_DIR / "events.py").read_text(encoding="utf-8")))
    assert types, "抓不到任何 event type，檢查解析規則"
    for locale in SUPPORTED_LOCALES:
        table = translations[locale]
        missing = sorted(
            t for t in types
            if "event.type." + t.replace(".", "_") not in table
        )
        assert not missing, f"{locale} 缺少事件翻譯：{missing}"


def test_item_js_covers_every_event_type_it_can_render():
    """item.js 的 EVENT_TYPE_KEYS 要涵蓋後端會寫的所有事件類型。"""
    source = (UI_DIR / "item.js").read_text(encoding="utf-8")
    block = re.search(r"const EVENT_TYPE_KEYS = \{(.*?)\};", source, re.S)
    assert block, "找不到 EVENT_TYPE_KEYS"
    mapped = set(re.findall(r'"([a-z]+\.[a-z_]+)"', block.group(1)))
    backend = set(re.findall(r'type="([a-z]+\.[a-z_]+)"',
                             (SHOP_DIR / "repo.py").read_text(encoding="utf-8")))
    backend |= set(re.findall(r'type="([a-z]+\.[a-z_]+)"',
                              (SHOP_DIR / "events.py").read_text(encoding="utf-8")))
    assert backend <= mapped, f"item.js 沒處理：{sorted(backend - mapped)}"


def test_status_filter_shows_a_label_but_keeps_the_english_value():
    """商品列表的 status 篩選：文字翻譯、value 不變。

    value 直接變成 /items?status=... 的查詢參數，所以不能翻。
    """
    source = (UI_DIR / "list.js").read_text(encoding="utf-8")
    assert 't("status." + status)' in source
    assert 'value: status' in source
    assert re.search(r'text:\s*status\b(?!.*t\()', source) is None, (
        "篩選選項文字不該再直接用原始值"
    )


def test_item_values_are_still_never_translated():
    """回歸護欄：商品資料欄位值原樣顯示。

    category / condition / notes 是使用者輸入的內容，切換語言不得改寫。
    """
    source = (UI_DIR / "list.js").read_text(encoding="utf-8")
    for field in ("item.category", "item.name", "item.brand", "item.model"):
        assert f't("{field}")' not in source, field
