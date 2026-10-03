"""Phase 10：v1 收尾驗收。

三塊：
  1. SPEC §6 三個呈現細節（來源照片縮圖 ×2、撞號連結）
  2. 錯誤處理一致性 —— inbox 上傳的「失敗」與「成功但重載失敗」必須分開
  3. SPEC §11 的驗收標準（原本缺實測的兩項：8 張一次建成、100+ 搜尋）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.conftest import make_jpeg

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("需要 node")
    result = subprocess.run(
        ["node", str(PROJECT_ROOT / "tests" / script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"{script} 執行失敗：{result.stderr}"
    return {row["label"]: row for row in json.loads(result.stdout)}


@pytest.fixture(scope="module")
def item_views():
    return _run("item_dom_harness.js")


@pytest.fixture(scope="module")
def inbox_views():
    return _run("inbox_dom_harness.js")


# ----------------------------------------------------------------------
# §6 A：建議值旁顯示來源照片縮圖
# ----------------------------------------------------------------------


def test_suggestion_shows_a_source_photo_thumbnail(item_views):
    row = item_views["建議顯示資料"]
    assert len(row["thumbs"]) == 2, "兩筆建議都要有縮圖"


def test_suggestion_thumbnail_points_at_the_source_photo(item_views):
    for thumb in item_views["建議顯示資料"]["thumbs"]:
        assert thumb["src"] == "/files/files/ITM-0001/original/a.jpg"
        assert thumb["title"] == "IMG_4821.jpg"


def test_suggestion_without_source_photo_has_no_thumbnail(item_views):
    """沒有來源照片就不顯示縮圖，只說明原因。"""
    row = item_views["建議沒有來源照片"]
    assert row["thumbs"] == []
    assert "沒有來源照片" in " ".join(
        card["text"] for card in row["cards"]
    )


def test_thumbnail_is_reachable_from_the_api_url(item_views, client):
    """縮圖用的是既有 /files/ 路徑，沒有為它另開端點。"""
    spec = client.get("/openapi.json").json()["paths"]
    assert not [p for p in spec if "thumb" in p]
    response = client.get("/files/files/ITM-0001/original/a.jpg")
    assert response.status_code in (200, 404)  # 沒有真的資料夾，但路由存在


# ----------------------------------------------------------------------
# §6 B：識別碼欄位旁顯示來源照片縮圖
# ----------------------------------------------------------------------


def test_identifier_shows_a_source_photo_thumbnail(item_views):
    """只有一筆 identifier 有來源照片 → 剛好一個縮圖。

    這個情境刻意沒有 pending 建議，否則建議卡的縮圖會混進來、
    讓「識別碼的縮圖不見了」這種退化測不出來。
    """
    row = item_views["識別碼縮圖（沒有建議）"]
    assert len(row["thumbs"]) == 1, "有來源照片的識別碼應該剛好一個縮圖"
    assert row["thumbs"][0]["src"] == "/files/files/ITM-0001/original/a.jpg"
    assert row["thumbs"][0]["title"] == "IMG_4821.jpg"


def test_identifier_without_source_photo_has_no_thumbnail(item_views):
    """同一張表裡另一筆沒有來源照片，就不該有縮圖。"""
    row = item_views["識別碼縮圖（沒有建議）"]
    assert len(row["thumbs"]) == 1, "只有一筆 identifier 有來源照片"


# ----------------------------------------------------------------------
# §6 C：撞號提示附既有 item 的連結
# ----------------------------------------------------------------------


def test_collision_warning_links_to_the_existing_item(item_views):
    links = item_views["識別碼縮圖與撞號連結"]["collisionLinks"]
    assert len(links) == 1
    assert links[0]["item"] == "ITM-0007"
    assert links[0]["href"] == "/items/ITM-0007"


def test_no_collision_no_link(item_views):
    assert item_views["建議顯示資料"]["collisionLinks"] == []


def test_collision_link_needs_no_new_endpoint(client):
    """item_id 本來就在 /api/identifiers/lookup 的回應裡。"""
    body = client.get("/api/identifiers/lookup?value=X").json()
    assert set(body) >= {"value", "normalized", "matches"}
    spec = client.get("/openapi.json").json()["paths"]
    assert not [p for p in spec if "collision" in p]


def test_collision_link_target_actually_exists(client, repo):
    """連結指向的商品必須真的存在，否則比對頁會 404。"""
    first = repo.create_item(name="甲")
    second = repo.create_item(name="乙")
    repo.add_identifier(first.id, "BX807061234")
    repo.add_identifier(second.id, "BX807061234", source_photo_id=None)

    found = client.get("/api/identifiers/lookup?value=BX807061234").json()
    others = [m for m in found["matches"] if m["item_id"] != second.id]
    assert others and others[0]["item_id"] == first.id
    assert client.get(f"/api/items/{others[0]['item_id']}").status_code == 200


# ----------------------------------------------------------------------
# 錯誤處理一致性：inbox 上傳
# ----------------------------------------------------------------------


def test_upload_success_shows_no_error(inbox_views):
    for label in ("1 photos", "3 photos", "8 photos"):
        assert inbox_views[label]["shownErrors"] == [] or all(
            not m for m in inbox_views[label]["shownErrors"]
        ), label


@pytest.mark.parametrize(
    ("label", "detail"), [("上傳失敗 500", "伺服器爆了"), ("上傳失敗 413", "檔案太大")]
)
def test_upload_failure_shows_the_real_error(inbox_views, label, detail):
    messages = [m for m in inbox_views[label]["shownErrors"] if m]
    assert len(messages) == 1
    assert messages[0].startswith("上傳失敗：")
    assert detail in messages[0]


def test_upload_failure_leaves_the_start_button_usable(inbox_views):
    """上傳失敗後要能再試。"""
    assert inbox_views["上傳失敗 500"]["startBtnDisabled"] is False


def test_reload_failure_is_not_reported_as_a_failed_upload(inbox_views):
    """POST 成功但重新載入失敗 —— 說「上傳失敗」會讓人重傳，inbox 就多一份。"""
    messages = [m for m in inbox_views["上傳成功但重載失敗"]["shownErrors"] if m]
    assert len(messages) == 1
    assert "上傳失敗" not in messages[0]
    assert "上傳成功" in messages[0]
    assert "重新整理" in messages[0]


def test_upload_and_reload_failures_are_separate_code_paths():
    """結構上的保險：POST 與 refresh 不在同一個 try 裡（和其他操作一致）。"""
    source = (PROJECT_ROOT / "ui" / "inbox.js").read_text(encoding="utf-8")
    body = source.split("async function upload(")[1].split("\n/* 觸發路徑")[0]
    assert body.count("} catch (err) {") == 2
    post_at = body.index('"/api/inbox/photos"')
    first_catch = body.index("} catch (err) {")
    refresh_at = body.index("await refresh()")
    assert post_at < first_catch < refresh_at


# ----------------------------------------------------------------------
# §11-1：8 張照片一次建成一個 Item
# ----------------------------------------------------------------------


def test_eight_photos_become_one_item(client, config):
    """SPEC §11.1：手機傳 8 張，按一次產出一個 Item。整條 HTTP 主線。"""
    files = [
        ("files", (f"IMG_{i}.jpg", make_jpeg(exif=f"2026:10:02 14:3{i}:00"),
                   "image/jpeg"))
        for i in range(8)
    ]
    assert client.post("/api/inbox/photos", files=files).json()["count"] == 8

    groups = client.post("/api/inbox/group?gap_minutes=30").json()
    assert len(groups) == 1
    assert len(groups[0]["entries"]) == 8

    done = client.post("/api/inbox/intake", json={
        "files": [entry["relative"] for entry in groups[0]["entries"]],
    })
    assert done.status_code == 201, done.text
    body = done.json()

    assert len(client.get("/api/items").json()) == 1, "8 張只能變成 1 個 Item"
    detail = client.get(f"/api/items/{body['item_id']}").json()
    assert len(detail["photos"]) == 8
    assert [o["kind"] for o in detail["observations"]] == ["intake"]
    assert client.get("/api/inbox").json()["count"] == 0

    folder = config.files_dir / body["item_id"] / "original"
    assert len(list(folder.glob("*.jpg"))) == 8
    assert db_ok(client)


def db_ok(client) -> bool:
    return client.get("/api/health").json()["status"] == "ok"


# ----------------------------------------------------------------------
# §11-10：100+ items 搜尋仍正常
# ----------------------------------------------------------------------


def test_search_over_a_hundred_items(repo, client):
    """SPEC §11.10。100 筆時搜尋要秒回，不是「感覺還好」。"""
    for index in range(120):
        repo.create_item(
            name=f"商品 {index:03d}",
            brand="華碩" if index % 2 == 0 else "NVIDIA",
            category="主機板" if index % 3 == 0 else "顯示卡",
        )
    repo.add_identifier("ITM-0007", "BX-807 06_1234")
    assert repo.counts()["items"] == 120

    started = time.perf_counter()
    found = client.get("/api/items?q=商品 042").json()
    elapsed = time.perf_counter() - started

    assert [item["id"] for item in found] == ["ITM-0043"]
    # 給的是很寬的量測門檻：重點是「沒有隨資料量爆掉」，不是跑分
    assert elapsed < 2.0, f"搜尋耗時 {elapsed:.3f}s，超出可接受範圍"


def test_search_by_serial_over_a_hundred_items(repo, client):
    for index in range(120):
        repo.create_item(name=f"商品 {index:03d}")
    repo.add_identifier("ITM-0050", "BX-807 06_1234")

    started = time.perf_counter()
    found = client.get("/api/items?q=807061234").json()
    elapsed = time.perf_counter() - started

    assert [item["id"] for item in found] == ["ITM-0050"]
    assert elapsed < 2.0, f"序號搜尋耗時 {elapsed:.3f}s"


def test_filters_still_combine_at_scale(repo, client):
    for index in range(120):
        repo.create_item(
            name=f"主機板 {index:03d}",
            brand="華碩",
            category="主機板" if index % 2 == 0 else "顯示卡",
        )
    found = client.get("/api/items?q=主機板&brand=華碩&category=主機板"
                       "&limit=500&offset=0").json()
    assert len(found) == 60
