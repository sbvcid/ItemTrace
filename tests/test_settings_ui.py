"""`/settings` 頁面的行為（用假 DOM 跑真正的 ui/settings.js）。

兩條重點：
   1. 頁面永遠拿不到已儲存的 API key —— 密碼欄每次載入都是空的
   2. 區網也能看也能改（server 刻意只服務受信任區網，
      與「區網本來就能讀寫所有商品資料」的信任模型一致；
      不信任區網就別把 server_host 設成 0.0.0.0）
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
HARNESS = Path(__file__).resolve().parent / "settings_dom_harness.js"


@pytest.fixture(scope="module")
def views():
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能操作頁面")
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


# ----------------------------------------------------------------------
# 1. 載入
# ----------------------------------------------------------------------


def test_page_loads_the_current_model(views):
    assert views["已設定時載入"]["model"] == "seed/model:free"


def test_key_field_is_blank_on_load(views):
    """已儲存的 key 不會回傳，所以密碼欄必須是空的。"""
    assert views["已設定時載入"]["keyValue"] == ""
    assert views["未設定時載入"]["keyValue"] == ""


def test_key_state_is_shown_as_a_status_not_a_value(views):
    assert "已設定" in views["已設定時載入"]["keyState"]
    assert "不會顯示" in views["已設定時載入"]["keyState"]
    assert "未設定" in views["未設定時載入"]["keyState"]


def test_page_names_the_config_file(views):
    assert views["已設定時載入"]["configFile"] == "tools/ai_config.local.json"


def test_no_error_on_load(views):
    assert views["已設定時載入"]["errorText"] == ""
    assert views["未設定時載入"]["errorText"] == ""


# ----------------------------------------------------------------------
# 2. 區網：也能改（受信任區網）
# ----------------------------------------------------------------------


def test_lan_sees_the_page_and_controls_are_enabled(views):
    row = views["區網檢視"]
    assert row["model"] == "seed/model:free", "區網應該看得到 model"
    assert row["disabled"] == [False] * 7, "區網也能改（受信任區網）"
    assert row["lanWarningHidden"] is False, "要顯示區網提示"


def test_lan_sees_the_key_status_but_not_the_key(views):
    row = views["區網檢視"]
    assert "已設定" in row["keyState"]


def test_localhost_controls_are_enabled(views):
    assert views["已設定時載入"]["disabled"] == [False] * 7
    assert views["已設定時載入"]["lanWarningHidden"] is True


# ----------------------------------------------------------------------
# 3. 修改 model
# ----------------------------------------------------------------------


def test_changing_only_the_model_posts_no_key(views):
    posted = views["只改 model"]["posted"]
    assert len(posted) == 1
    assert posted[0]["path"] == "/api/settings/ai"
    assert posted[0]["method"] == "POST"
    assert posted[0]["body"] == {
        "model": "new/model:free",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
    }
    assert "api_key" not in posted[0]["body"], "沒填就不該送 key 欄位"


def test_saving_reports_success(views):
    assert "設定已儲存" in views["只改 model"]["status"]


def test_save_failure_shows_the_server_message(views):
    row = views["儲存失敗"]
    assert "儲存失敗" in row["errorText"]
    assert "base_url" in row["errorText"]
    assert row["status"] == ""


def test_failure_does_not_wipe_the_input(views):
    """失敗時不要把使用者剛填的東西清掉。"""
    assert views["儲存失敗"]["keyValue"] == ""


# ----------------------------------------------------------------------
# 4. 修改 API key
# ----------------------------------------------------------------------


def test_changing_the_key_posts_it(views):
    posted = views["改 API key"]["posted"][0]
    assert posted["body"]["api_key"] == "sk-or-v1-TEST-LOCAL-KEY"
    assert posted["body"]["model"] == "seed/model:free"


def test_key_is_cleared_after_a_successful_save(views):
    """存完就把密碼欄清掉，不要留在 DOM 裡。"""
    assert views["改 API key"]["keyValueAfter"] == ""


def test_saved_key_still_shows_as_configured(views):
    assert "已設定" in views["改 API key"]["keyState"]


# ----------------------------------------------------------------------
# 5. 測試 API
# ----------------------------------------------------------------------


def test_test_api_posts_to_the_test_endpoint(views):
    posted = views["測試 API 成功"]["posted"][0]
    assert posted["path"] == "/api/settings/ai/test"
    assert posted["method"] == "POST"


def test_test_api_success_message(views):
    assert "API 測試成功" in views["測試 API 成功"]["status"]
    assert views["測試 API 成功"]["errorText"] == ""


def test_test_api_failure_shows_the_real_error(views):
    row = views["測試 API 失敗"]
    assert row["status"] == ""
    assert "API 測試失敗" in row["errorText"]
    assert "No auth" in row["errorText"]


def test_test_api_can_use_an_unsaved_key(views):
    """剛貼上還沒存的 key 也能先測。"""
    posted = views["測試未儲存的 key"]["posted"][0]
    assert posted["body"]["api_key"] == "sk-or-v1-UNSAVED-KEY-000000"
    assert posted["body"]["model"] == "typed/model:free"


def test_test_api_never_sends_itemtrace_data(views):
    """測試按鈕不該碰商品或照片。"""
    for label in ("測試 API 成功", "測試未儲存的 key"):
        for call in views[label]["posted"]:
            assert call["path"] == "/api/settings/ai/test"
            assert set(call["body"]) <= {"model", "api_key",
                                            "provider", "base_url"}


# ----------------------------------------------------------------------
# 6. 清除
# ----------------------------------------------------------------------


def test_clear_is_skipped_when_the_user_cancels(views):
    assert views["清除但取消"]["cleared"] is False
    assert views["清除但取消"]["status"] == ""


def test_clear_happens_after_confirmation(views):
    assert views["清除並確認"]["cleared"] is True
    assert "已清除" in views["清除並確認"]["status"]


def test_clear_resets_the_status_and_field(views):
    row = views["清除並確認"]
    assert "未設定" in row["keyState"]
    assert row["keyValue"] == ""


# ----------------------------------------------------------------------
# 7. 顯示／隱藏
# ----------------------------------------------------------------------


def test_toggle_switches_the_input_type(views):
    row = views["顯示隱藏切換"]
    assert row["beforeType"] == "password"
    assert row["afterType"] == "text"
    assert row["backType"] == "password"


def test_toggle_label_follows_the_state(views):
    row = views["顯示隱藏切換"]
    assert row["labelAfterShow"] == "隱藏"
    assert row["labelAfterHide"] == "顯示"


def test_toggle_never_fetches_the_stored_key(views):
    """切換顯示不應該「把存的 key 叫回來」—— 那等於送到瀏覽器。"""
    source = (UI_DIR / "settings.js").read_text(encoding="utf-8")
    toggle = source.split('toggleBtn.addEventListener("click"', 1)[1].split("});", 1)[0]
    assert "fetch" not in toggle
    assert "api(" not in toggle
    assert "apiKeyInput.type" in toggle, "只切換輸入欄本身的型別"


# ----------------------------------------------------------------------
# 8. 原始碼層面的保險
# ----------------------------------------------------------------------


def test_settings_js_never_stores_the_key_outside_the_input():
    """key 只在「從輸入欄讀出來、送進 request body」這條路上出現。

    不准有 localStorage / sessionStorage / dataset / 隱藏欄位之類的副本。
    """
    source = (UI_DIR / "settings.js").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    body = re.sub(r'""".*?"""', "", body, flags=re.S)

    for store in ("localStorage", "sessionStorage", "dataset", "setAttribute"):
        assert store not in body, f"不該把 key 放進 {store}"

    # 讀 key 只從密碼欄取值；寫入欄位只會是清空（存完不留在 DOM 裡）
    touches = sorted({
        l.strip() for l in body.splitlines() if "apiKeyInput.value" in l
    })
    assert touches == [
        'apiKeyInput.value = "";',
        'const typed = apiKeyInput.value.trim();',
    ], touches

    # 送 key 的地方必須是 body.api_key（save 與 testApi 各一處，內容相同）
    sends = {l.strip() for l in body.splitlines() if "body.api_key" in l}
    assert sends == {"if (typed) body.api_key = typed;"}, sends


def test_settings_js_has_no_bulk_or_automatic_behaviour():
    source = (UI_DIR / "settings.js").read_text(encoding="utf-8")
    for forbidden in ("accept", "reject", "/api/items", "/api/inbox",
                      "fallback", "autoSave", "setInterval"):
        assert forbidden not in source, f"不該出現 {forbidden}"


def test_settings_html_has_no_bulk_accept_button():
    """這一頁不該有任何「接受建議」之類的按鈕。

    比對按鈕文字（>…<）而不是整個字：「要逐筆看過、按接受才會寫進商品資料」
    這種說明文字是正常的。
    """
    markup = (UI_DIR / "settings.html").read_text(encoding="utf-8")
    button_labels = re.findall(r">([^<>]{1,20})</button>", markup)
    for label in button_labels:
        for forbidden in ("接受", "刪除", "合併", "批次"):
            assert forbidden not in label, label
    assert "全部接受" not in markup
    assert not any("接受" in l for l in button_labels), button_labels


def test_settings_page_is_linked_from_every_page():
    for name in ("inbox.html", "items.html", "item.html"):
        markup = (UI_DIR / name).read_text(encoding="utf-8")
        assert 'href="/settings"' in markup, name


def test_password_input_is_a_password_field():
    markup = (UI_DIR / "settings.html").read_text(encoding="utf-8")
    assert 'id="api-key"' in markup
    line = next(l for l in markup.splitlines() if 'id="api-key"' in l)
    assert 'type="password"' in line
    assert "autocomplete" in line, "不要讓瀏覽器記住這把 key"
