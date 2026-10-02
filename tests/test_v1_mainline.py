"""SPEC-v1 §12.1 的唯一完成路徑，一次走完整條主線（階段 2 + 階段 3）。

    匯入 inbox → 建立 Item → 建立 Observation → 原始照片保存到
    files/ITM-xxxx/original/ → 建立 suggestions → 人工確認
    → Identifier 正式成立（帶 source_photo_id）→ 搜尋得到 → 歸檔完成

（模糊搜尋是階段 5，這裡用正規化後的比對示範可搜尋性。）
"""

from __future__ import annotations

from shop import db as db_mod
from shop import inbox as inbox_mod
from shop.ids import normalize_identifier
from tests.conftest import write_photo


def test_v1_mainline(repo):
    # 匯入：先開 Item 與 intake 觀測
    item = repo.create_item(name="ROG STRIX B650E-F", category="主機板", quantity=1)
    assert item.id == "ITM-0001"
    intake = repo.add_observation(
        item.id, kind="intake", note="出貨前拍攝", captured_at="2026-10-02T14:30:00"
    )

    # 原始照片入庫（檔名帶時間戳，原始檔名保留）
    label_photo = repo.add_photo(
        item.id,
        f"files/{item.id}/original/20261002-143355_IMG_4824.jpg",
        orig_name="IMG_4824.jpg",
        sha256="9f" * 32,
        bytes=3_120_000,
        width=4032,
        height=3024,
        captured_at="2026-10-02T14:33:55",
        angle="label",
        observation_id=intake.id,
    )

    # 外部工具寫建議 —— 主表還沒動
    brand = repo.add_suggestion(
        item.id, "brand", "ASUS", confidence=0.9, model_name="claude-opus-4",
        source_photo_id=label_photo.id,
    )
    serial = repo.add_suggestion(
        item.id, "identifier:serial", "BX-807 06_1234", confidence=0.77,
        model_name="claude-opus-4", source_photo_id=label_photo.id,
    )
    assert repo.get_item(item.id).brand == ""

    # 人工確認
    repo.accept_suggestion(brand.id)
    repo.accept_suggestion(serial.id)
    assert repo.get_item(item.id).brand == "ASUS"

    # Identifier 正式成立，且可追溯來源照片
    identifiers = repo.list_identifiers(item_id=item.id)
    assert len(identifiers) == 1
    assert identifiers[0].value == "BX-807 06_1234"
    assert identifiers[0].normalized == "BX807061234"
    assert identifiers[0].source == "accepted_suggestion"
    assert identifiers[0].source_photo_id == label_photo.id

    # 找得到：正規化後可以對上（階段 5 會補上模糊比對）
    half = normalize_identifier("807061234")
    found = repo.conn.execute(
        "SELECT i.id FROM identifiers i JOIN items t ON t.id = i.item_id"
        " WHERE i.normalized LIKE ?",
        (f"%{half}%",),
    ).fetchall()
    assert [row["id"] for row in found] == [identifiers[0].id]

    # 歸檔：歷史可回答「這筆資料為什麼長這樣」
    history = repo.item_history(item.id)
    assert [event.type for event in history].count("item.created") == 1
    assert "suggestion.accepted" in [event.type for event in history]
    assert sum(1 for event in history if event.type == "field.changed") == 1


def test_recheck_observation_keeps_intake_intact(repo):
    """SPEC-v1 §4.2：重新觀測不影響原始觀測。"""
    item = repo.create_item()
    intake = repo.add_observation(item.id, kind="intake", captured_at="2026-10-02T14:30:00")
    repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", observation_id=intake.id)

    recheck = repo.add_observation(item.id, kind="recheck", captured_at="2026-10-20T11:00:00")
    repo.add_photo(item.id, f"files/{item.id}/original/b.jpg", observation_id=recheck.id)

    observations = repo.list_observations(item.id)
    assert [obs.kind for obs in observations] == ["intake", "recheck"]
    assert len(repo.list_photos(observation_id=intake.id)) == 1
    assert len(repo.list_photos(observation_id=recheck.id)) == 1
    assert len(repo.list_photos(item_id=item.id)) == 2


def test_v1_mainline_through_files(config, repo):
    """階段 3 接手：照片真的從 inbox 落到 files/<item-id>/original/。"""
    for index in range(3):
        write_photo(
            config.inbox_dir / f"IMG_482{index}.jpg",
            exif=f"2026:10:02 14:3{index}:00",
        )

    result = inbox_mod.intake(config, repo, kind="intake", note="出貨前拍攝")
    item = repo.get_item(result.item.id)

    # Item 建立後就是 active，欄位留空等建議被接受
    assert item.status == "active"
    assert (item.brand, item.model) == ("", "")

    # 原始照片在磁碟上，檔名帶時間戳且原始檔名保留
    on_disk = sorted(p.name for p in inbox_mod.original_dir(config, item.id).iterdir())
    assert on_disk == [
        "20261002-143000_IMG_4820.jpg",
        "20261002-143100_IMG_4821.jpg",
        "20261002-143200_IMG_4822.jpg",
    ]
    assert not list(config.inbox_dir.iterdir())

    # 資料庫只存相對路徑，而且找得回檔案
    photos = repo.list_photos(item_id=item.id)
    assert len(photos) == 3
    for photo in photos:
        assert photo.filename.startswith(f"files/{item.id}/original/")
        assert config.resolve(photo.filename).exists()
        assert photo.observation_id == result.observation.id
        assert photo.sha256 and photo.bytes

    # 外部工具寫建議 → 人工接受 → Identifier 帶著來源照片成立
    label = next(photo for photo in photos if photo.orig_name == "IMG_4821.jpg")
    serial = repo.add_suggestion(
        item.id,
        "identifier:serial",
        "BX-807 06_1234",
        confidence=0.77,
        model_name="claude-opus-4",
        source_photo_id=label.id,
    )
    repo.accept_suggestion(serial.id)

    identifier = repo.list_identifiers(item_id=item.id)[0]
    assert identifier.source_photo_id == label.id
    assert identifier.normalized == "BX807061234"
    # 序號旁看得到「這是從哪張照片來的」
    source = repo.get_photo(identifier.source_photo_id)
    assert config.resolve(source.filename).name == "20261002-143100_IMG_4821.jpg"

    # 手輸後半段能找到（正規化後比對；模糊 LIKE 搜尋是階段 5）
    half = normalize_identifier("807061234")
    found = repo.conn.execute(
        "SELECT item_id FROM identifiers WHERE normalized LIKE ?", (f"%{half}%",)
    ).fetchall()
    assert [row["item_id"] for row in found] == [item.id]

    # 關掉再開資料都在，verify 也通過
    assert inbox_mod.scan_inbox(config) == []
    assert db_mod.verify(config)["ok"] is True
