"""Phase 10：v1 後端驗收標準。

SPEC §11 的驗收標準：
- 8 張照片一次建成一個 Item
- 100+ items 搜尋仍正常
"""

from __future__ import annotations

import time


from tests.conftest import make_jpeg


def db_ok(client) -> bool:
    return client.get("/api/health").json()["status"] == "ok"


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
