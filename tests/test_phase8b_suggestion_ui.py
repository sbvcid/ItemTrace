"""Phase 8B：商品頁的建議 accept / reject UI。

純 UI 測試。API、Repository、schema、suggestion 語意全部不動 —— 這裡驗的是
按下去之後畫面有沒有反應、講錯話時會不會假裝成功。

用 node 的 vm 在假 DOM 上跑真正的 ui/item.js，真的去點「接受」/「拒絕」，
並且讓 fetch 回各種狀態（包含 identifier 撞號的 409）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "item_dom_harness.js"


@pytest.fixture(scope="module")
def views():
    """跑一次 harness，回傳每個情境的結果。"""
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能點按鈕")
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    import json

    return {row["label"]: row for row in json.loads(result.stdout)}


def _card(views, label, index=0):
    return views[label]["cards"][index]


# ----------------------------------------------------------------------
# 1. pending 建議顯示正確資料
# ----------------------------------------------------------------------


def test_pending_suggestion_shows_field_and_value(views):
    card = _card(views, "建議顯示資料")
    assert "品牌" in card["text"]
    assert "華碩" in card["text"]


def test_identifier_field_gets_a_readable_label(views):
    """identifier:serial 顯示成「序號」，不是原始欄位名。"""
    card = _card(views, "建議顯示資料", 1)
    assert "序號" in card["text"]
    assert "identifier:serial" not in card["text"]
    assert "XXXX-123456" in card["text"]


def test_confidence_and_model_name_are_shown(views):
    card = _card(views, "建議顯示資料")
    assert "信心 0.94" in card["text"]
    assert "vision-x" in card["text"]


def test_source_photo_link_points_at_the_right_file(views):
    card = _card(views, "建議顯示資料")
    assert card["sourceHref"] == "/files/files/ITM-0001/original/a.jpg"
    assert "看來源照片" in card["text"]


def test_missing_source_photo_is_stated_not_faked(views):
    """沒有（或指不到）來源照片要明講，不能顯示成一條死掉的連結。"""
    row = views["建議沒有來源照片"]
    assert row["cardCount"] == 2
    for card in row["cards"]:
        assert card["sourceHref"] is None
        assert "沒有來源照片" in card["text"]
    assert "看來源照片" not in row["cards"][0]["text"]


def test_card_offers_both_actions(views):
    card = _card(views, "建議顯示資料")
    assert sorted(card["actions"]) == ["accept", "reject"]


# ----------------------------------------------------------------------
# 2-3. Accept / Reject 一般欄位
# ----------------------------------------------------------------------


def test_accept_posts_to_the_accept_endpoint(views):
    row = views["接受一般欄位"]
    assert row["clicked"]["clicked"] is True
    assert "POST /api/suggestions/S1/accept" in row["calls"]


def test_accept_reloads_detail_and_the_field_shows_the_new_value(views):
    row = views["接受一般欄位"]
    # 不需要整頁手動刷新：refresh() 之後表單欄位直接是新值
    assert row["afterBrand"] == "華碩"
    # 已接受的建議不再是 pending，卡片消失
    assert row["afterCardCount"] == 0
    assert row["afterSectionShown"] is False


def test_accept_does_not_create_an_identifier_for_a_normal_field(views):
    assert views["接受一般欄位"]["afterIdentifierRows"] == 0


def test_reject_posts_to_the_reject_endpoint(views):
    row = views["拒絕一般欄位"]
    assert "POST /api/suggestions/S1/reject" in row["calls"]


def test_reject_leaves_the_field_untouched(views):
    row = views["拒絕一般欄位"]
    assert row["afterBrand"] == ""
    assert row["afterCardCount"] == 0


# ----------------------------------------------------------------------
# 4. Accept identifier
# ----------------------------------------------------------------------


def test_accept_identifier_posts_and_creates_the_identifier(views):
    row = views["接受 identifier"]
    assert "POST /api/suggestions/S1/accept" in row["calls"]
    # 序號是「另建 identifier」，不是改 items 的欄位
    assert row["afterIdentifierRows"] == 1
    assert row["afterBrand"] == ""
    assert row["afterCardCount"] == 0


def test_identifier_suggestion_is_marked_as_creating_an_identifier(views):
    card = _card(views, "建議顯示資料", 1)
    assert "接受後會建立識別碼" in card["text"]


# ----------------------------------------------------------------------
# 5. 已決定的不再提供操作
# ----------------------------------------------------------------------


def test_accepted_or_rejected_suggestions_have_no_buttons(views):
    """section 只列 pending，所以已決定的建議不會出現在列表裡。"""
    row = views["沒有 pending 建議"]
    assert row["sectionShown"] is False
    assert row["cardCount"] == 0


def test_after_accepting_the_card_is_gone(views):
    """點下去之後卡片消失 → 不可能對同一筆建議按第二次。"""
    assert views["接受一般欄位"]["afterCardCount"] == 0
    assert views["拒絕一般欄位"]["afterCardCount"] == 0
    assert views["接受 identifier"]["afterCardCount"] == 0


# ----------------------------------------------------------------------
# 6. 失敗時不可假裝成功 —— 這是重點
# ----------------------------------------------------------------------


def test_accept_409_shows_the_real_error(views):
    row = views["accept 回 409"]
    assert "接受失敗" in row["afterErrorText"]
    assert "其他商品已有正規化後相同的識別碼" in row["afterErrorText"]


def test_accept_409_does_not_remove_the_card(views):
    """伺服器沒動 → 建議仍是 pending → 卡片要留在畫面上。"""
    row = views["accept 回 409"]
    assert row["afterCardCount"] == 1
    assert row["afterSectionShown"] is True


def test_accept_409_keeps_the_buttons_usable(views):
    row = views["accept 回 409"]
    assert sorted(row["afterActions"]) == ["accept", "reject"]
    assert row["afterDisabled"] == [False, False]


def test_accept_409_does_not_touch_the_item(views):
    row = views["accept 回 409"]
    assert row["afterBrand"] == ""
    assert row["afterIdentifierRows"] == 0


def test_accept_409_error_slot_is_visible(views):
    assert views["accept 回 409"]["afterErrorHidden"] is False


def test_other_errors_are_shown_too(views):
    """不只是 409：任何非 2xx 都要講出來。"""
    row = views["accept 回 500"]
    assert "接受失敗" in row["afterErrorText"]
    assert "boom" in row["afterErrorText"]
    assert row["afterCardCount"] == 1


def test_no_page_level_false_success(views):
    """失敗不該讓整頁變成「找不到這件商品」。"""
    for label in ("accept 回 409", "accept 回 500"):
        assert views[label]["notFoundShown"] is False, label


# ----------------------------------------------------------------------
# 7. 互動細節
# ----------------------------------------------------------------------


def test_buttons_are_disabled_while_the_request_is_in_flight(views):
    """避免連按。decide() 在第一個 await 之前就鎖上。"""
    for label in ("接受一般欄位", "拒絕一般欄位", "接受 identifier",
                  "accept 回 409", "accept 回 500"):
        assert views[label]["clicked"]["busyDuring"] is True, label


def test_each_suggestion_can_be_decided_on_its_own(views):
    """一頁多筆建議，每張卡各自有按鈕。"""
    row = views["建議顯示資料"]
    assert row["cardCount"] == 2
    assert all(sorted(card["actions"]) == ["accept", "reject"] for card in row["cards"])
    assert row["cards"][0]["id"] != row["cards"][1]["id"]


def test_no_bulk_accept_button(views):
    """不新增「全部接受」—— 每筆都要人自己看過。"""
    card_text = " ".join(c["text"] for c in views["建議顯示資料"]["cards"])
    assert "全部接受" not in card_text


def test_unsaved_form_edits_survive_a_decision(views):
    """接受建議會重載資料，但不能蓋掉還沒存檔的輸入。

    否則使用者在備註欄打到一半、順手點了接受，內容就消失了。
    """
    row = views["先打字再接受"]
    assert row["afterNotes"] == "我還沒存檔的備註"
    # 同時接受本身還是生效了
    assert row["afterBrand"] == "華碩"
    assert row["afterCardCount"] == 0


def test_source_text_has_no_ai_client_and_no_bulk_action():
    """8B 不碰 AI client，也不做批次接受。"""
    source = (Path(__file__).resolve().parents[1] / "ui" / "item.js").read_text(
        encoding="utf-8"
    )
    for forbidden in ("全部接受", "acceptAll", "autoAccept", "/api/inbox",
                      "Ollama", "openai", "OpenRouter"):
        assert forbidden not in source, f"不該出現 {forbidden}"


def test_decisions_use_the_existing_endpoints(client):
    """只用既有的 accept / reject 端點，沒有為 UI 開新 API。"""
    source = (Path(__file__).resolve().parents[1] / "ui" / "item.js").read_text(
        encoding="utf-8"
    )
    assert '"/api/suggestions/"' in source
    assert '+ "/" + action' in source

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/suggestions/{suggestion_id}/accept" in paths
    assert "/api/suggestions/{suggestion_id}/reject" in paths
    # Phase 8B 沒有動到其他端點的形狀
    assert "/api/items/{item_id}/suggestions" in paths
    assert "/api/items/{item_id}/{rest}" not in paths
