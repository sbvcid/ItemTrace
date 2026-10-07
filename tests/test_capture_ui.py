"""連續拍照（/capture）：取得多張照片這一步變成連續拍。

設計上刻意「不新做 anything」：

    * 照片取得沿用既有的 <input type="file" capture="environment">
      相機入口（手機直接進相機，不用選相機/相簿）
    * 批次只在記憶體累積，按「建檔」才一次走既有流程：
        POST /api/inbox/photos → 前後差集 → POST /api/inbox/intake
    * 導向商品頁時帶 ?ai=1，商品頁沿用既有的 AI 自動填入

所以這裡要驗證的是：
    1. 連續拍照頁存在、相機直接開（capture 屬性、單一觸發路徑）
    2. 可以連續拍 2 / 5 / 10 張，張數、正確累積、input 可重用
    3. 預覽本批、刪單張、繼續拍攝
    4. 取消整批：沒有 POST、沒有半成品
    5. 建檔後整批進入既有多照片流程（upload → intake → item）
    6. 這批照片可以被既有的 AI 端點分析，結果是待確認建議
    7. 原本的單張/多張選照片流程不受影響
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import make_jpeg

ROOT = Path(__file__).resolve().parents[1]


def ui(name: str) -> str:
    return (ROOT / "ui" / name).read_text(encoding="utf-8")


def upload_batch(client, names, *, start_minute=30):
    """模擬 capture.js「整批上傳」：multipart 欄位名 files。"""
    files = [
        ("files", (name, make_jpeg(exif=f"2026:10:02 14:{start_minute:02d}:00"),
                   "image/jpeg"))
        for name in names
    ]
    response = client.post("/api/inbox/photos", files=files)
    assert response.status_code == 201, response.text


def inbox_relatives(client):
    return [e["relative"] for e in client.get("/api/inbox").json()["entries"]]


# ----------------------------------------------------------------------
# 頁面與相機入口
# ----------------------------------------------------------------------


def test_capture_page_is_served(client):
    response = client.get("/capture")
    assert response.status_code == 200
    markup = response.text
    assert 'id="camera-input"' in markup
    assert 'id="shutter"' in markup
    assert 'id="count"' in markup
    assert 'id="finish"' in markup
    assert 'id="build"' in markup


def test_camera_input_opens_the_camera_directly(client):
    """capture="environment"：手機直接進相機，不用在相機/相簿之間選。"""
    markup = ui("capture.html")
    line = next(l for l in markup.splitlines() if 'id="camera-input"' in l)
    assert 'type="file"' in line
    assert 'accept="image/*"' in line
    assert 'capture="environment"' in line
    assert "hidden" in line
    # 刻意沒有 multiple：手機相機一次回一張，批次由 JS 累積
    assert "multiple" not in line


def test_capture_entry_is_on_the_home_page(client):
    """首頁（inbox）有連續拍照入口。"""
    markup = ui("inbox.html")
    assert 'href="/capture"' in markup
    assert "連續拍照" in markup


def test_shutter_is_the_only_camera_trigger():
    """cameraInput.click() 只能從快門 handler 呼叫一次。

    和 inbox 同理：#shutter 是 button 不是 label，label 包 input
    會雙重觸發讓 picker 被開兩次又關掉。
    """
    source = ui("capture.js")
    assert source.count("cameraInput.click()") == 1
    handler = source.split('shutter.addEventListener("click"')[1].split("});")[0]
    assert "cameraInput.click()" in handler
    markup = ui("capture.html")
    assert not markup.startswith("<label")
    assert "<label" not in markup.split("</header>")[1].split("<script")[0]


def test_change_handler_copies_the_filelist_before_clearing():
    """先把 FileList 複製成 Array 再清 input（inbox.js 踩過的坑）。"""
    source = ui("capture.js")
    change = source.split('cameraInput.addEventListener("change"')[1].split("});")[0]
    assert "Array.from(cameraInput.files" in change
    copy_at = change.index("Array.from(cameraInput.files")
    clear_at = change.index('cameraInput.value = ""')
    assert copy_at < clear_at, "必須先複製 FileList 再清 input"


def test_capture_reuses_the_existing_endpoints_only():
    """前端只能用既有的 inbox 端點，不另打一套 item/AI API。"""
    source = ui("capture.js")
    for required in ('"/api/inbox"', '"/api/inbox/photos"', '"/api/inbox/intake"'):
        assert required in source, f"缺少 {required}"
    # 不直接建立商品、不直接叫 AI
    for forbidden in ('api("/api/items",', '"/api/items/" +', "ai/analyze",
                      "openai", "getUserMedia"):
        assert forbidden not in source, f"capture.js 不該有 {forbidden}"
    # 批次只存在記憶體：取消時沒有任何上傳
    assert "batch = []" in source


def test_item_page_auto_analyzes_when_asked():
    """?ai=1 讓商品頁沿用同一條 AI 流程（analyzeWithAi）。"""
    source = ui("item.js")
    assert 'URLSearchParams(window.location.search).get("ai") === "1"' in source
    assert "analyzeWithAi()" in source


# ----------------------------------------------------------------------
# 行為測試：在假的 DOM 上真的跑 capture.js
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def harness():
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能做行為測試")
    script = Path(__file__).resolve().parent / "capture_dom_harness.js"
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


def test_entering_capture_starts_an_empty_batch(harness):
    row = harness["進入連續拍照"]
    assert row["countText"] == "已拍 0 張"
    assert row["finishDisabled"] is True
    assert row["previewHidden"] is True
    assert row["stripLength"] == 0


def test_shutter_opens_the_camera(harness):
    assert harness["快門開相機"]["cameraClicks"] == 1


def test_can_shoot_two_five_and_ten_photos(harness):
    assert harness["連續拍 2 張"]["countText"] == "已拍 2 張"
    assert harness["連續拍 2 張"]["stripLength"] == 2
    assert harness["連續拍 2 張"]["inputCleared"] is True

    assert harness["連續拍 5 張"]["countText"] == "已拍 5 張"
    assert harness["連續拍 5 張"]["stripLength"] == 5

    row = harness["連續拍 10 張"]
    assert row["countText"] == "已拍 10 張"
    assert row["finishDisabled"] is False
    # 拍攝區只顯示最近 8 張 + 一個「+N」
    assert row["stripLength"] == 9


def test_preview_shows_the_batch_and_delete_works(harness):
    row = harness["預覽本批"]
    assert row["previewHidden"] is False
    assert row["gridLength"] == 3
    assert row["previewCount"] == "（3 張）"
    assert row["buildDisabled"] is False
    # 刪一張 → 批次與畫面都少一張
    assert row["afterDelete"]["gridLength"] == 2
    assert row["afterDelete"]["countText"] == "已拍 2 張"
    # 繼續拍攝 → 回到快門畫面
    assert row["backToCapture"] is True


def test_cancel_discards_the_batch_without_any_post(harness):
    for label in ("取消整批", "預覽畫面取消整批"):
        row = harness[label]
        assert row["posts"] == 0, "取消時什麼都不該上傳"
        assert row["href"] == "/", "取消應該回首頁"


def test_build_posts_the_whole_batch_through_the_existing_flow(harness):
    row = harness["建檔"]
    calls = row["calls"]
    # 既有流程的四步：前後清單 + 上傳 + intake
    assert [c["method"] for c in calls] == ["GET", "POST", "GET", "POST"]
    assert calls[0]["path"] == "/api/inbox"
    assert calls[1]["path"] == "/api/inbox/photos"
    assert calls[1]["files"] == ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"]
    assert calls[2]["path"] == "/api/inbox"
    assert calls[3]["path"] == "/api/inbox/intake"
    # intake 只拿到「這一批」的差集，不含既有的 old.jpg
    assert row["intakeFiles"] == ["inbox/IMG_1.jpg", "inbox/IMG_2.jpg",
                                  "inbox/IMG_3.jpg"]
    assert row["intakeKind"] == "intake"
    # 導向商品頁，帶 ?ai=1 讓商品頁自動 AI 分析
    assert row["href"] == "/items/ITM-0001?ai=1"


def test_build_failure_keeps_the_photos_in_the_inbox(harness):
    row = harness["建檔失敗"]
    assert "建檔失敗" in row["errorText"]
    assert "Inbox" in row["errorText"]
    assert row["href"] == "", "失敗不該導向"
    # 上傳與 intake 都試過了（照片已進 inbox，等使用者回去收）
    assert row["posts"] == 2


def test_empty_batch_cannot_build(harness):
    row = harness["空批次"]
    assert row["buildDisabled"] is True
    assert row["posts"] == 0


# ----------------------------------------------------------------------
# 後端流程：capture.js 做的四步，用真正的 HTTP 走一遍
# ----------------------------------------------------------------------


def test_the_four_step_flow_creates_one_item_with_the_whole_batch(client, config):
    """capture.js 的「前後差集」流程，端到端驗證。"""
    before = set(inbox_relatives(client))
    assert before == set()

    upload_batch(client, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg",
                          "IMG_4.jpg", "IMG_5.jpg"])

    after = inbox_relatives(client)
    fresh = [relative for relative in after if relative not in before]
    assert len(fresh) == 5

    response = client.post("/api/inbox/intake",
                           json={"files": fresh, "kind": "intake"})
    assert response.status_code == 201, response.text
    done = response.json()

    assert done["item_id"] == "ITM-0001"
    assert done["observation_id"].startswith("OBS-")
    assert len(done["archived"]) == 5

    detail = client.get("/api/items/ITM-0001").json()
    assert len(detail["photos"]) == 5
    assert [o["kind"] for o in detail["observations"]] == ["intake"]
    # 欄位留空，等 AI 建議被接受
    assert detail["item"]["name"] == ""

    # 照片正確保存：files/<item>/original/，inbox 已清空
    folder = config.files_dir / "ITM-0001" / "original"
    assert len(list(folder.iterdir())) == 5
    assert client.get("/api/inbox").json() == {"entries": [], "count": 0}
    for photo in detail["photos"]:
        assert photo["filename"].startswith("files/ITM-0001/original/")
        assert config.resolve(photo["filename"]).exists()


def test_same_filename_collisions_are_all_caught_by_the_diff(client, config):
    """手機常常拍出同名檔案：後端加流水號，差集要全部抓到。"""
    before = set(inbox_relatives(client))
    upload_batch(client, ["IMG_1.jpg", "IMG_1.jpg"])

    after = inbox_relatives(client)
    fresh = [relative for relative in after if relative not in before]
    assert len(fresh) == 2
    assert "inbox/IMG_1.jpg" in fresh
    assert "inbox/IMG_1-2.jpg" in fresh

    done = client.post("/api/inbox/intake",
                       json={"files": fresh, "kind": "intake"}).json()
    assert len(done["archived"]) == 2
    assert len(list((config.files_dir / "ITM-0001" / "original").iterdir())) == 2


def test_upload_only_creates_no_item(client):
    """只上傳（還沒按建檔，或建檔前取消）：沒有 Item、沒有照片列。

    取消整批在前端就攔下了（記憶體批次丟掉）；這裡驗證「即使
    上傳了、沒有 intake」也不會有半成品。
    """
    upload_batch(client, ["A.jpg", "B.jpg"])
    assert client.get("/api/items").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0


def test_intake_failure_leaves_the_batch_in_the_inbox(client):
    """intake 失敗：照片留在 inbox，使用者回去用既有流程收。"""
    upload_batch(client, ["A.jpg"])
    relatives = inbox_relatives(client)
    response = client.post("/api/inbox/intake",
                           json={"files": relatives, "kind": "return"})
    assert response.status_code == 400
    assert client.get("/api/items").json() == []
    assert inbox_relatives(client) == relatives


def test_the_batch_is_analyzable_by_the_existing_ai_endpoint(
        client, config, monkeypatch):
    """整批照片走既有的 POST /api/items/{id}/ai/analyze：
    結果是 pending 建議，商品欄位不動；接受才寫入。"""
    from shop import ai_client, ai_config
    from shop.ai_config import AiConfig

    upload_batch(client, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"])
    fresh = inbox_relatives(client)
    done = client.post("/api/inbox/intake",
                       json={"files": fresh, "kind": "intake"}).json()
    item_id = done["item_id"]
    assert len(done["archived"]) == 3

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-0000000000",
                                  model="test/model:free"),
    )

    def fake_provider(api_key, model, data_urls, *,
                      provider=None, base_url=None, timeout=None):
        fake_provider.seen = {"data_urls": len(data_urls),
                               "provider": provider}
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({"suggestions": [
                        {"field": "brand", "value": "ASUS",
                         "confidence": 0.9, "source_photo_index": 0},
                        {"field": "model", "value": "RTX4060",
                         "confidence": 0.8, "source_photo_index": 1},
                    ]}),
                },
            }],
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_provider)

    response = client.post(f"/api/items/{item_id}/ai/analyze")
    assert response.status_code == 201, response.text
    suggestions = response.json()
    assert [s["field"] for s in suggestions] == ["brand", "model"]
    assert all(s["status"] == "pending" for s in suggestions)
    # 三張照片都送進去了
    assert fake_provider.seen["data_urls"] == 3

    # AI 永不直接改商品
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == ""

    # 接受一筆 → 欄位才寫入
    accept = client.post(
        f"/api/suggestions/{suggestions[0]['id']}/accept")
    assert accept.status_code == 200, accept.text
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["brand"] == "ASUS"


def test_single_photo_flow_still_works(client):
    """原本一張一張拍的流程（選照片 → 分組 → 建檔）不受影響。"""
    files = [("files", ("only.jpg",
                        make_jpeg(exif="2026:10:02 14:30:00"),
                        "image/jpeg"))]
    assert client.post("/api/inbox/photos", files=files).status_code == 201

    groups = client.post("/api/inbox/group?gap_minutes=30").json()
    assert len(groups) == 1
    chosen = [e["relative"] for e in groups[0]["entries"]]

    done = client.post("/api/inbox/intake",
                       json={"files": chosen, "kind": "intake"}).json()
    assert done["item_id"] == "ITM-0001"
    assert len(done["archived"]) == 1
    detail = client.get("/api/items/ITM-0001").json()
    assert len(detail["photos"]) == 1
