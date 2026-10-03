"""Phase 7 Inbox UI 與 POST /api/inbox/intake。

主線：
    上傳到 inbox → 顯示待處理 → 依 EXIF 時間分組 → 選一組
    → 開始建檔 → 建立 Item + Observation(kind=intake) → 照片歸檔
    → 導向 /items/<item-id>
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import make_jpeg


def ui(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "ui" / name).read_text(
        encoding="utf-8"
    )


def upload_to_inbox(client, count=1, *, start_minute=30, tag="IMG"):
    """把照片丟進 inbox，回傳相對路徑清單。"""
    files = [
        ("files", (f"{tag}_{index}.jpg",
                   make_jpeg(exif=f"2026:10:02 14:{start_minute + index:02d}:00"),
                   "image/jpeg"))
        for index in range(count)
    ]
    response = client.post("/api/inbox/photos", files=files)
    assert response.status_code == 201, response.text
    return [f"inbox/{tag}_{index}.jpg" for index in range(count)]


def group_files(client, gap_minutes=30):
    response = client.post(f"/api/inbox/group?gap_minutes={gap_minutes}")
    assert response.status_code == 200, response.text
    return response.json()


# ----------------------------------------------------------------------
# 空 inbox
# ----------------------------------------------------------------------


def test_inbox_starts_empty(client):
    assert client.get("/api/inbox").json() == {"entries": [], "count": 0}
    assert group_files(client) == []


def test_empty_inbox_renders_the_page(client):
    body = client.get("/").text
    assert "/static/inbox.js" in body
    assert 'id="file-input"' in body
    assert "multiple" in body


# ----------------------------------------------------------------------
# 上傳
# ----------------------------------------------------------------------


def test_upload_single_photo(client, config):
    relatives = upload_to_inbox(client, 1)
    listing = client.get("/api/inbox").json()
    assert listing["count"] == 1
    assert listing["entries"][0]["relative"] == relatives[0]
    assert listing["entries"][0]["captured_at"] == "2026-10-02T14:30:00"
    assert (config.inbox_dir / "IMG_0.jpg").exists()


def test_upload_several_photos(client, config):
    relatives = upload_to_inbox(client, 5)
    listing = client.get("/api/inbox").json()
    assert listing["count"] == 5
    assert sorted(e["relative"] for e in listing["entries"]) == sorted(relatives)
    assert len(list(config.inbox_dir.glob("*.jpg"))) == 5


def test_upload_never_overwrites_an_existing_inbox_file(client, config):
    (config.inbox_dir / "IMG_4821.jpg").write_bytes(b"already here")
    client.post("/api/inbox/photos",
                files=[("files", ("IMG_4821.jpg", make_jpeg(), "image/jpeg"))])
    assert (config.inbox_dir / "IMG_4821.jpg").read_bytes() == b"already here"
    assert (config.inbox_dir / "IMG_4821-2.jpg").exists()


def test_upload_without_files_is_400(client):
    assert client.post("/api/inbox/photos").status_code == 400


def test_uploaded_photo_has_no_database_row_yet(client):
    """inbox 是待處理，還不知道屬於哪件商品。"""
    upload_to_inbox(client, 1)
    assert client.get("/api/items").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0


# ----------------------------------------------------------------------
# 預覽
# ----------------------------------------------------------------------


def test_inbox_photo_preview_is_servable(client):
    relatives = upload_to_inbox(client, 1)
    response = client.get(f"/files/{relatives[0]}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")


def test_inbox_preview_does_not_expose_other_data_root_files(client, config):
    upload_to_inbox(client, 1)
    for path in ("catalog.db", "config.json", "inbox/../catalog.db",
                 "%2e%2e/catalog.db"):
        assert client.get(f"/files/{path}").status_code == 404
    assert config.database.exists()


def test_files_route_still_serves_archived_originals(client):
    """擴充 inbox 後，已歸檔照片仍然取得到。"""
    upload_to_inbox(client, 1)
    done = client.post("/api/inbox/intake", json={"files": upload_to_inbox(client, 1)})
    assert done.status_code == 201
    photo = done.json()["archived"][0]
    assert client.get(f"/files/{photo['filename']}").status_code == 200


# ----------------------------------------------------------------------
# 分組
# ----------------------------------------------------------------------


def test_group_by_capture_time(client):
    upload_to_inbox(client, 3, start_minute=30)
    groups = group_files(client, gap_minutes=30)
    assert len(groups) == 1
    assert len(groups[0]["entries"]) == 3
    assert groups[0]["entries"][0]["captured_at"] == "2026-10-02T14:30:00"


def test_groups_split_when_the_gap_is_exceeded(client):
    upload_to_inbox(client, 2, start_minute=30, tag="A")
    upload_to_inbox(client, 2, start_minute=33, tag="B")
    assert len(group_files(client, gap_minutes=1)) == 2
    assert len(group_files(client, gap_minutes=30)) == 1


def test_group_honours_the_gap_parameter(client):
    upload_to_inbox(client, 1, start_minute=30, tag="A")
    upload_to_inbox(client, 1, start_minute=33, tag="B")
    upload_to_inbox(client, 1, start_minute=40, tag="C")
    assert [len(g["entries"]) for g in group_files(client, gap_minutes=30)] == [3]
    assert [len(g["entries"]) for g in group_files(client, gap_minutes=2)] == [1, 1, 1]


def test_group_indexes_are_sequential(client):
    upload_to_inbox(client, 1, start_minute=10, tag="A")
    upload_to_inbox(client, 1, start_minute=20, tag="B")
    groups = group_files(client, gap_minutes=5)
    assert [g["index"] for g in groups] == [0, 1]
    assert groups[0]["captured_at"] < groups[1]["captured_at"]


def test_group_carries_enough_for_the_card(client):
    upload_to_inbox(client, 2, start_minute=30)
    group = group_files(client)[0]
    assert group["captured_from"] == "exif"
    assert all(e["relative"].startswith("inbox/") for e in group["entries"])
    assert all(e["bytes"] > 0 for e in group["entries"])


def test_frontend_does_not_reimplement_grouping(client):
    """分組交給後端，前端不自己讀 EXIF、不自己切時間。"""
    source = ui("inbox.js")
    assert "/api/inbox/group" in source
    assert "gap_minutes" in source
    for forbidden in ("DateTimeOriginal", "exif", "Date.parse"):
        assert forbidden not in source, f"前端不該自己做 {forbidden}"


def test_frontend_shows_the_gap_in_use(client):
    source = ui("inbox.js")
    assert "gapSelect.value" in source
    markup = ui("inbox.html")
    assert 'id="gap"' in markup
    # 預設 30 分鐘，且和後端常數一致
    from shop.api import DEFAULT_GROUP_GAP_MINUTES

    assert f'value="{DEFAULT_GROUP_GAP_MINUTES}" selected' in markup


# ----------------------------------------------------------------------
# 一鍵建立 Item
# ----------------------------------------------------------------------


def test_start_intake_creates_item_observation_and_photos(client, config):
    relatives = upload_to_inbox(client, 3)
    assert group_files(client)

    response = client.post("/api/inbox/intake", json={"files": relatives})
    assert response.status_code == 201, response.text
    done = response.json()

    assert done["item_id"] == "ITM-0001"
    assert done["observation_id"].startswith("OBS-")
    assert len(done["archived"]) == 3

    item = client.get(f"/api/items/{done['item_id']}").json()
    assert item["item"]["status"] == "active"
    # 欄位留空，後續到 detail page 再補
    assert item["item"]["name"] == "" and item["item"]["brand"] == ""
    assert [o["kind"] for o in item["observations"]] == ["intake"]
    assert len(item["photos"]) == 3


def test_archived_photos_land_in_the_right_folder(client, config):
    relatives = upload_to_inbox(client, 2)
    done = client.post("/api/inbox/intake", json={"files": relatives}).json()

    folder = config.files_dir / done["item_id"] / "original"
    assert folder.is_dir()
    assert sorted(p.name for p in folder.iterdir()) == [
        "20261002-143000_IMG_0.jpg",
        "20261002-143100_IMG_1.jpg",
    ]
    for photo in done["archived"]:
        assert photo["filename"].startswith(
            f"files/{done['item_id']}/original/")
        assert config.resolve(photo["filename"]).exists()
        assert photo["role"] == "original"
        assert photo["observation_id"] == done["observation_id"]


def test_intake_empties_the_batch_from_the_inbox(client, config):
    relatives = upload_to_inbox(client, 3)
    client.post("/api/inbox/intake", json={"files": relatives})

    assert client.get("/api/inbox").json() == {"entries": [], "count": 0}
    assert list(config.inbox_dir.glob("*.jpg")) == []
    assert group_files(client) == []


def test_intake_only_takes_the_selected_group(client, config):
    """只選一組建檔 → 其他組留在 inbox 等下一次處理。"""
    upload_to_inbox(client, 2, start_minute=30, tag="A")
    upload_to_inbox(client, 2, start_minute=20, tag="B")
    groups = group_files(client, gap_minutes=1)
    assert len(groups) == 2

    chosen = [e["relative"] for e in groups[0]["entries"]]
    done = client.post("/api/inbox/intake", json={"files": chosen}).json()

    assert len(done["archived"]) == 2
    remaining = client.get("/api/inbox").json()
    assert remaining["count"] == 2
    assert chosen[0].split("/")[-1] not in [
        e["relative"].split("/")[-1] for e in remaining["entries"]
    ]


def test_intake_writes_events(client):
    relatives = upload_to_inbox(client, 1)
    done = client.post("/api/inbox/intake", json={"files": relatives}).json()
    types = [e["type"] for e in
             client.get(f"/api/items/{done['item_id']}/events").json()]
    assert "item.created" in types
    assert "observation.created" in types
    assert "photo.created" in types


def test_reupload_to_the_same_item_is_a_noop(client):
    """同一件商品重複匯入同一張照片：不多一份、不多一筆。"""
    relatives = upload_to_inbox(client, 1)
    first = client.post("/api/inbox/intake", json={"files": relatives}).json()
    item_id = first["item_id"]
    source = client.get(f"/files/{first['archived'][0]['filename']}").content

    client.post("/api/inbox/photos",
                files=[("files", ("again.jpg", source, "image/jpeg"))])
    second = client.post("/api/inbox/intake",
                         json={"files": ["inbox/again.jpg"], "item_id": item_id}).json()

    assert second["item_id"] == item_id
    assert second["observation_id"] is None
    assert second["archived"] == []
    assert second["skipped"] == [{"relative": "inbox/again.jpg"}]
    detail = client.get(f"/api/items/{item_id}").json()
    assert len(detail["photos"]) == 1
    assert [o["kind"] for o in detail["observations"]] == ["intake"]


def test_identical_bytes_for_a_new_item_are_archived_not_stolen(client):
    """位元組相同但沒指定商品：照樣歸檔，不搶走另一件商品的證據。

    這和 identifiers 的撞號哲學一致 —— 回報得出來讓人判斷，而不是擋下來
    或默默合併。
    """
    relatives = upload_to_inbox(client, 1)
    first = client.post("/api/inbox/intake", json={"files": relatives}).json()
    source = client.get(f"/files/{first['archived'][0]['filename']}").content

    client.post("/api/inbox/photos",
                files=[("files", ("copy.jpg", source, "image/jpeg"))])
    second = client.post("/api/inbox/intake", json={"files": ["inbox/copy.jpg"]}).json()

    assert second["item_id"] == "ITM-0002"
    assert len(second["archived"]) == 1
    assert len(client.get("/api/items").json()) == 2
    # 兩邊的檔案都還在
    assert client.get(f"/files/{first['archived'][0]['filename']}").status_code == 200
    assert client.get(f"/files/{second['archived'][0]['filename']}").status_code == 200


def test_intake_can_add_to_an_existing_item(client):
    relatives = upload_to_inbox(client, 1)
    first = client.post("/api/inbox/intake", json={"files": relatives}).json()

    upload_to_inbox(client, 1, start_minute=45, tag="SECOND")
    again = client.post("/api/inbox/intake",
                        json={"files": ["inbox/SECOND_0.jpg"],
                              "item_id": first["item_id"], "kind": "recheck"}).json()

    assert again["item_id"] == first["item_id"]
    detail = client.get(f"/api/items/{first['item_id']}").json()
    assert [o["kind"] for o in detail["observations"]] == ["intake", "recheck"]
    assert len(detail["photos"]) == 2


# ----------------------------------------------------------------------
# 沒有拍攝時間的照片：不能自動分組，但一定要能建檔
# ----------------------------------------------------------------------


def test_photo_without_capture_time_lands_ungrouped(client, config, monkeypatch):
    """SPEC §14.4 的最後一階：EXIF、mtime、檔名都沒有 → 留空。"""
    from shop import photos as photos_mod

    monkeypatch.setattr(photos_mod, "_mtime_iso", lambda path: None)
    (config.inbox_dir / "untimed.jpg").write_bytes(make_jpeg())

    listing = client.get("/api/inbox").json()
    assert listing["count"] == 1
    assert listing["entries"][0]["captured_at"] is None
    assert listing["entries"][0]["captured_from"] == "none"
    # 後端刻意不把它放進任何 group
    assert group_files(client) == []


def test_untimed_photo_has_a_preview(client, config, monkeypatch):
    from shop import photos as photos_mod

    monkeypatch.setattr(photos_mod, "_mtime_iso", lambda path: None)
    (config.inbox_dir / "untimed.jpg").write_bytes(make_jpeg())
    relative = client.get("/api/inbox").json()["entries"][0]["relative"]
    assert client.get(f"/files/{relative}").status_code == 200


def test_untimed_photo_can_be_built_into_an_item(client, config, monkeypatch):
    """缺口修補：沒有時間的照片也要走同一條 /api/inbox/intake。"""
    from shop import photos as photos_mod

    monkeypatch.setattr(photos_mod, "_mtime_iso", lambda path: None)
    for index in range(2):
        (config.inbox_dir / f"untimed{index}.jpg").write_bytes(
            make_jpeg(width=1600 + index, height=1200)
        )
    relatives = [e["relative"] for e in client.get("/api/inbox").json()["entries"]]
    assert relatives

    response = client.post("/api/inbox/intake", json={"files": relatives})
    assert response.status_code == 201, response.text
    done = response.json()
    assert done["item_id"] == "ITM-0001"
    assert len(done["archived"]) == 2

    detail = client.get(f"/api/items/{done['item_id']}").json()
    assert [o["kind"] for o in detail["observations"]] == ["intake"]
    # 時間留空，而不是填一個假時間
    assert detail["observations"][0]["captured_at"] is None
    assert all(p["captured_at"] is None for p in detail["photos"])
    assert all(p["filename"].startswith(f"files/{done['item_id']}/original/")
               for p in detail["photos"])
    # 檔名沒有時間前綴，改用現在的時間戳
    for photo in detail["photos"]:
        assert len(config.resolve(photo["filename"]).name.split("_", 1)[0]) == 15

    assert client.get("/api/inbox").json()["count"] == 0


def test_untimed_and_timed_photos_are_separated(client, config, monkeypatch):
    """有時間的自動分組，沒時間的另外一組，兩邊都能各自建檔。"""
    from shop import photos as photos_mod

    # 整段保持 mtime 不可用：EXIF 優先，所以有 EXIF 的那兩張不受影響
    monkeypatch.setattr(photos_mod, "_mtime_iso", lambda path: None)
    (config.inbox_dir / "untimed.jpg").write_bytes(make_jpeg())
    upload_to_inbox(client, 2, tag="TIMED")

    listing = client.get("/api/inbox").json()
    timed = [e["relative"] for e in listing["entries"] if e["captured_at"]]
    untimed = [e["relative"] for e in listing["entries"] if not e["captured_at"]]
    assert len(timed) == 2 and len(untimed) == 1

    groups = group_files(client)
    assert [len(g["entries"]) for g in groups] == [2]

    first = client.post("/api/inbox/intake", json={"files": timed}).json()
    second = client.post("/api/inbox/intake", json={"files": untimed}).json()
    assert first["item_id"] != second["item_id"]
    assert client.get("/api/inbox").json()["count"] == 0


def test_frontend_offers_to_build_the_untimed_group(client):
    """未分組不能只是「顯示出來而已」，必須可選、可建檔。"""
    markup = ui("inbox.html")
    assert 'id="ungrouped"' in markup
    assert "沒有拍攝時間" in markup
    assert "時間讀不出來" in markup

    source = ui("inbox.js")
    # 未分組被當成一個可選的組合，走同一條 intake 路徑
    assert "LOOSE_KEY" in source
    assert "function choices()" in source
    assert "groupCard(loose)" in source
    assert "choices().find" in source
    # 前端只有一條建檔路徑，不管有沒有時間都走它
    assert source.count('api("/api/inbox/intake"') == 1


def test_frontend_untimed_card_is_selectable_like_the_others(client):
    source = ui("inbox.js")
    assert "selectGroup(group.index)" in source
    assert "group.captured_at ? timeRange(group)" in source


def test_unknown_file_is_rejected_and_changes_nothing(client):
    response = client.post("/api/inbox/intake", json={"files": ["inbox/nope.jpg"]})
    assert response.status_code == 404
    assert client.get("/api/items").json() == []


def test_empty_file_list_is_400(client):
    assert client.post("/api/inbox/intake", json={"files": []}).status_code == 400


def test_missing_body_is_400(client):
    assert client.post("/api/inbox/intake", json={}).status_code == 400


def test_path_traversal_is_refused(client, config):
    """不能藉 intake 搬走 DATA_ROOT 裡的任意檔案。"""
    secret = config.data_root / "secret.txt"
    secret.write_text("must not move", encoding="utf-8")
    for attempt in ("secret.txt", "files/../secret.txt",
                    "files/ITM-0001/original/x.jpg", "inbox/../secret.txt"):
        response = client.post("/api/inbox/intake", json={"files": [attempt]})
        assert response.status_code in (400, 404), attempt
    assert secret.exists()
    assert client.get("/api/items").json() == []


def test_cannot_reingest_an_already_archived_original(client):
    """已歸檔的 original 不會被第二次 intake 搬走。"""
    relatives = upload_to_inbox(client, 1)
    done = client.post("/api/inbox/intake", json={"files": relatives}).json()
    archived = done["archived"][0]["filename"]
    before = client.get(f"/files/{archived}").content

    response = client.post("/api/inbox/intake", json={"files": [archived]})
    assert response.status_code == 400
    assert client.get(f"/files/{archived}").content == before
    assert len(client.get("/api/items").json()) == 1


def test_missing_target_item_is_404_and_keeps_files(client, config):
    relatives = upload_to_inbox(client, 2)
    response = client.post("/api/inbox/intake",
                           json={"files": relatives, "item_id": "ITM-9999"})
    assert response.status_code == 404
    # 檔案還在 inbox，沒有被搬走
    assert client.get("/api/inbox").json()["count"] == 2


def test_bad_observation_kind_rolls_everything_back(client, config):
    """整批撤銷：沒有半套的 Item，也不留半套檔案。"""
    relatives = upload_to_inbox(client, 3)
    response = client.post("/api/inbox/intake",
                           json={"files": relatives, "kind": "return"})
    assert response.status_code == 400

    assert client.get("/api/items").json() == []
    assert client.get("/api/inbox").json()["count"] == 3
    assert sorted(p.name for p in config.inbox_dir.glob("*.jpg")) == [
        "IMG_0.jpg", "IMG_1.jpg", "IMG_2.jpg"
    ]
    assert client.get("/api/stats").json()["counts"]["photos"] == 0


def test_intake_never_overwrites_an_existing_original(client, config):
    """目標檔名撞到既有照片時加流水號，不覆蓋。"""
    # 先手動放一個同名檔在 ITM-0001/original/
    keeper = config.files_dir / "ITM-0001" / "original" / "20261002-143000_IMG_0.jpg"
    keeper.parent.mkdir(parents=True)
    keeper.write_bytes(b"original evidence already here")

    relatives = upload_to_inbox(client, 1)
    client.post("/api/inbox/intake", json={"files": relatives})

    assert keeper.read_bytes() == b"original evidence already here"
    assert (keeper.parent / "20261002-143000_IMG_0-2.jpg").exists()


def test_partial_failure_returns_files_to_the_inbox(client, config, monkeypatch):
    """搬檔搬到一半出錯 → 已搬走的檔案全部搬回去。"""
    relatives = upload_to_inbox(client, 3)

    from shop import repo as repo_mod

    original = repo_mod.Repository.add_photo
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("資料庫寫不進去")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(repo_mod.Repository, "add_photo", flaky)
    with pytest.raises(RuntimeError):
        client.post("/api/inbox/intake", json={"files": relatives})

    assert client.get("/api/items").json() == []
    assert sorted(p.name for p in config.inbox_dir.glob("*.jpg")) == [
        "IMG_0.jpg", "IMG_1.jpg", "IMG_2.jpg"
    ]
    archived = config.files_dir / "ITM-0001" / "original"
    assert not archived.exists() or list(archived.iterdir()) == []


# ----------------------------------------------------------------------
# 前端行為
# ----------------------------------------------------------------------


def test_frontend_navigates_to_the_item_after_intake(client):
    source = ui("inbox.js")
    assert 'window.location.href = "/items/"' in source
    assert "done.item_id" in source


def test_frontend_selects_a_group_before_building(client):
    source = ui("inbox.js")
    assert "selectGroup" in source
    assert "selected === null" in source
    assert "/api/inbox/intake" in source


def test_frontend_uploads_with_the_files_field(client):
    """multipart 欄位名要是 files，和後端一致。"""
    source = ui("inbox.js")
    assert 'body.append("files", file, file.name)' in source


def test_frontend_does_not_upload_existing_inbox_files_again(client):
    """檔案已經在 inbox 上了，前端不該重新上傳它們。"""
    source = ui("inbox.js")
    assert "group.entries.map((entry) => entry.relative)" in source
    assert "/api/observations" not in source


def test_upload_area_is_large_enough_for_thumbs(client):
    """手機優先：上傳區與建檔按鈕都要夠大。"""
    markup = ui("inbox.html")
    assert 'type="file"' in markup and "multiple" in markup
    assert "點這裡選照片" in markup
    css = ui("app.css")
    assert "button.big" in css
    assert ".dropzone" in css


# ----------------------------------------------------------------------
# 選照片的觸發鏈
#
# 實機踩過的坑：#dropzone 原本是 <label> 包住 file input，點下去時
# 瀏覽器原生觸發 input，JS 又呼叫一次 fileInput.click() → 雙重觸發 →
# file picker 被開兩次又立刻收掉，change 沒發生，
# POST /api/inbox/photos 從來沒送出。
# ----------------------------------------------------------------------


def test_dropzone_is_not_a_label(client):
    """上傳區不能是 label：label 會原生觸發內部的 input。"""
    markup = ui("inbox.html")
    assert not re.search(r'<label[^>]*id="dropzone"', markup), (
        "dropzone 必須是 div，不是 label"
    )
    assert '<div class="dropzone" id="dropzone">' in markup
    # 整個上傳區裡不該還有別的 label 包 input
    assert not re.search(r"<label[^>]*>\s*<input", markup)


def test_file_input_is_still_hidden_inside_the_dropzone(client):
    markup = ui("inbox.html")
    block = markup.split('id="dropzone"')[1].split("</div>")[0]
    assert 'id="file-input"' in block
    assert 'type="file"' in block
    assert "multiple" in block
    assert "hidden" in block
    assert 'accept="image/*"' in block


def test_dropzone_click_is_the_only_trigger(client):
    """fileInput.click() 只能被呼叫一次，且只在 dropzone 的 click handler 裡。"""
    source = ui("inbox.js")
    # 總數 1 就擋掉「任何地方多開一次 picker」
    assert source.count("fileInput.click()") == 1

    handler = source.split('dropzone.addEventListener("click"')[1].split("});")[0]
    assert "fileInput.click()" in handler


def test_change_handler_copies_the_filelist_before_clearing(client):
    """先把 FileList 複製成 Array，再清 input —— 順序反過來會拿到 0 張。

    input.files 是活的 FileList：value = "" 會清空 selected files，
    getter 又回傳同一個物件。所以先取參照再清空，那個參照會跟著變空，
    upload() 的 `if (!files.length) return` 直接早退，一張都沒上傳。
    """
    source = ui("inbox.js")
    change = source.split('fileInput.addEventListener("change"')[1].split("});")[0]
    copy_at = change.index("Array.from(fileInput.files)")
    clear_at = change.index('fileInput.value = ""')
    assert copy_at < clear_at, "必須先複製 FileList 再清 input"
    assert "upload(picked)" in change


def test_upload_sends_multipart_field_named_files(client):
    """multipart 欄位名必須是 files，和後端 /api/inbox/photos 一致。"""
    source = ui("inbox.js")
    assert 'body.append("files", file, file.name)' in source
    assert 'api("/api/inbox/photos", { method: "POST", body })' in source


def test_upload_does_not_leave_the_start_button_enabled_by_accident(client):
    """上傳進行中要鎖住建檔按鈕，避免同時跑兩條流程。"""
    source = ui("inbox.js")
    upload_body = source.split("async function upload(")[1].split("\nasync function")[0]
    assert "startBtn.disabled = true" in upload_body
    assert "if (!files || !files.length) return" in upload_body


# ----------------------------------------------------------------------
# 行為測試：在假的 DOM 上真的派發 change，看 upload 收到什麼
#
# 上面那些是原始碼比對，擋得住「忘了清 value」，擋不住「清 value 之後
# FileList 被清空」。這組用 node 的 vm 跑真正的 ui/inbox.js，假造的 file
# input 照 HTML Standard 建模（value="" 會清空 selected files、files
# getter 回傳同一個活物件），所以真的會重現那個 bug。
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def harness():
    """跑一次 tests/inbox_dom_harness.js，回傳每個張數情境的結果。"""
    if shutil.which("node") is None:
        pytest.skip("需要 node 才能做行為測試")
    script = Path(__file__).resolve().parent / "inbox_dom_harness.js"
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"harness 執行失敗：{result.stderr}"
    return {row["requested"]: row for row in json.loads(result.stdout)}


def test_picking_photos_actually_posts_them(harness):
    """重點：選完照片要真的送出，不是安靜地什麼都沒做。"""
    for count in (1, 3, 8):
        row = harness[count]
        assert row["posted"] is True, f"選 {count} 張卻沒有 POST"
        assert row["method"] == "POST"
        assert row["fieldNames"] == ["files"]
        assert row["sentCount"] == count, f"選 {count} 張只送出 {row['sentCount']} 張"
        assert row["sentNames"] == [f"IMG_{i}.jpg" for i in range(count)]


def test_clearing_the_input_does_not_empty_the_upload(harness):
    """input 被清空（為了讓同一批能再選一次）不影響已經抓到的檔案。"""
    for count in (1, 3, 8):
        row = harness[count]
        assert row["fileInputCleared"] is True, "input 沒有被清空"
        assert row["sentCount"] == count, "清空 input 把檔案清掉了"


def test_multiple_photos_are_not_reduced_to_zero(harness):
    """多張不會因為清 value 變成 0 張 —— 這正是 8d2d2b9 的症狀。"""
    assert harness[8]["sentCount"] == 8
    assert harness[3]["sentCount"] == 3


def test_single_photo_upload_posts_one_file(harness):
    assert harness[1]["sentNames"] == ["IMG_0.jpg"]
    assert harness[1]["sentCount"] == 1


def test_selecting_nothing_sends_no_request(harness):
    """取消選取不該送出空請求。"""
    assert harness[0]["posted"] is False
    assert harness[0]["sentCount"] == 0


def test_inbox_page_has_no_form_fields_before_building(client):
    """不要求使用者先填很多欄位：inbox 上只有檔案選擇。"""
    markup = ui("inbox.html")
    assert markup.count("<input") == 1  # 只有檔案選擇；分組 radio 由 JS 產生
    assert "開始建檔" in markup


def test_no_ai_or_suggestion_automation_in_the_inbox(client):
    joined = ui("inbox.html") + ui("inbox.js")
    for forbidden in ("/api/suggestions", "/accept", "/reject", "/api/ai", "openai", "ocr"):
        assert forbidden not in joined