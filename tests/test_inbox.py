"""inbox 掃描與入庫落盤（SPEC-v1 §10 階段 3）。"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from shop import config as config_mod
from shop import db as db_mod
from shop import inbox as inbox_mod
from shop import photos
from shop.errors import ValidationError
from shop.repo import Repository
from tests.conftest import make_jpeg, set_mtime, write_photo


def drop(config, name: str, **kwargs) -> Path:
    """把一張照片放進 inbox，回傳路徑。"""
    return write_photo(config.inbox_dir / name, **kwargs)


# ----------------------------------------------------------------------
# scan_inbox
# ----------------------------------------------------------------------


def test_scan_empty_inbox(config):
    assert inbox_mod.scan_inbox(config) == []


def test_scan_missing_inbox_dir_is_not_an_error(config):
    import shutil

    shutil.rmtree(config.inbox_dir)
    assert inbox_mod.scan_inbox(config) == []


def test_scan_lists_files_with_capture_time(config):
    write_photo(config.inbox_dir / "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    write_photo(config.inbox_dir / "IMG_4824.jpg", exif="2026:10:02 14:33:55")
    entries = inbox_mod.scan_inbox(config)

    assert [entry.path.name for entry in entries] == ["IMG_4821.jpg", "IMG_4824.jpg"]
    assert entries[0].captured_at == "2026-10-02T14:30:22"
    assert entries[0].captured_from == photos.EXIF_SOURCE
    assert entries[0].relative == "inbox/IMG_4821.jpg"


def test_scan_does_not_move_anything(config):
    path = drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    inbox_mod.scan_inbox(config)
    assert path.exists()


def test_scan_skips_directories_and_hidden_files(config):
    (config.inbox_dir / "sub").mkdir(parents=True)
    (config.inbox_dir / "sub" / "a.jpg").write_bytes(make_jpeg())
    (config.inbox_dir / ".DS_Store").write_bytes(b"junk")
    (config.inbox_dir / ".nomedia").write_bytes(b"")
    assert [entry.path.name for entry in inbox_mod.scan_inbox(config)] == ["a.jpg"]


def test_scan_is_recursive_by_default(config):
    write_photo(config.inbox_dir / "2026" / "10" / "IMG_4821.jpg")
    assert len(inbox_mod.scan_inbox(config)) == 1
    assert inbox_mod.scan_inbox(config, recursive=False) == []


# ----------------------------------------------------------------------
# intake：正常流程
# ----------------------------------------------------------------------


def test_intake_archives_photo_and_writes_row(config, repo):
    source = drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    original_bytes = source.read_bytes()
    result = inbox_mod.intake(config, repo)

    item = result.item
    assert item.id == "ITM-0001"
    assert result.observation.kind == "intake"
    assert result.observation.captured_at == "2026-10-02T14:30:22"

    archived = config.resolve(result.archived[0].photo.filename)
    assert archived.name == "20261002-143022_IMG_4821.jpg"
    assert archived.parent == config.files_dir / "ITM-0001" / "original"
    assert archived.exists()

    stored = repo.get_photo(result.archived[0].photo.id)
    assert stored.orig_name == "IMG_4821.jpg"
    assert stored.captured_at == "2026-10-02T14:30:22"
    assert stored.observation_id == result.observation.id
    assert stored.role == "original"
    assert (stored.width, stored.height) == (4032, 3024)
    assert len(stored.sha256) == 64
    assert stored.bytes == len(original_bytes)
    # 位元組一個都沒變
    assert archived.read_bytes() == original_bytes


def test_intake_saves_relative_path_only(config, repo):
    """資料庫不得綁定 DATA_ROOT 的絕對路徑（SPEC-v1 §3）。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    stored = repo.get_photo(result.archived[0].photo.id)

    assert stored.filename.startswith("files/ITM-0001/original/")
    assert not Path(stored.filename).is_absolute()
    assert ":" not in stored.filename
    assert str(config.data_root) not in stored.filename
    # 搬走後仍然能用相對路徑找回原檔
    assert config.resolve(stored.filename).exists()


def test_intake_empties_the_source_file(config, repo):
    path = drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    inbox_mod.intake(config, repo)
    assert not path.exists()
    assert inbox_mod.scan_inbox(config) == []


def test_intake_of_several_photos_makes_one_observation(config, repo):
    for index in range(8):
        drop(config, f"IMG_48{index}.jpg", exif=f"2026:10:02 14:3{index}:00")

    result = inbox_mod.intake(config, repo)

    assert len(result.archived) == 8
    assert len(repo.list_observations(result.item.id)) == 1
    assert len(repo.list_photos(item_id=result.item.id)) == 8
    # Observation 的時間取最早一張
    assert result.observation.captured_at == "2026-10-02T14:30:00"


def test_intake_writes_events(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    types = [event.type for event in repo.item_history(result.item.id)]
    assert "item.created" in types
    assert "observation.created" in types
    assert "photo.created" in types


def test_intake_creates_item_with_empty_fields(config, repo):
    """Item 一建立就是 active，欄位留空等建議被接受。"""
    drop(config, "IMG_4821.jpg")
    result = inbox_mod.intake(config, repo)
    item = repo.get_item(result.item.id)
    assert item.status == "active"
    assert (item.name, item.brand, item.model) == ("", "", "")


def test_intake_into_existing_item_makes_recheck(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    first = inbox_mod.intake(config, repo)

    drop(config, "IMG_9000.jpg", exif="2026:10:20 11:00:00")
    second = inbox_mod.intake(
        config, repo, kind="recheck", item_id=first.item.id, note="退貨重拍"
    )

    assert second.item.id == first.item.id
    assert second.observation.kind == "recheck"
    assert second.observation.note == "退貨重拍"
    observations = repo.list_observations(first.item.id)
    assert [obs.kind for obs in observations] == ["intake", "recheck"]
    # 原始觀測與照片不受影響
    assert len(repo.list_photos(observation_id=observations[0].id)) == 1
    assert len(repo.list_photos(observation_id=observations[1].id)) == 1


def test_intake_keeps_original_and_derived_separate(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)

    original = inbox_mod.original_dir(config, result.item.id)
    derived = inbox_mod.derived_dir(config, result.item.id)
    assert original != derived
    assert [p.name for p in original.iterdir()] == ["20261002-143022_IMG_4821.jpg"]
    assert not derived.exists()


def test_intake_uses_mtime_when_no_exif(config, repo):
    path = drop(config, "IMG_4821.jpg")
    set_mtime(path, datetime(2026, 10, 2, 9, 8, 7))
    result = inbox_mod.intake(config, repo)

    assert result.archived[0].photo.captured_at.startswith("2026-10-02T09:08:07")
    assert result.archived[0].photo.filename.endswith(
        "original/20261002-090807_IMG_4821.jpg"
    )


def test_intake_uses_filename_timestamp_when_mtime_gone(config, repo, monkeypatch):
    """mtime 讀不到時才用檔名時間戳（SPEC-v1 §14.4 的順序）。"""
    monkeypatch.setattr(photos, "_mtime_iso", lambda path: None)
    drop(config, "20261002-143022_IMG_4821.jpg")
    result = inbox_mod.intake(config, repo)

    assert result.archived[0].photo.captured_at == "2026-10-02T14:30:22"
    assert result.archived[0].photo.filename.endswith(
        "original/20261002-143022_IMG_4821.jpg"
    )


def test_mtime_wins_over_filename(config, repo, monkeypatch):
    """兩者都拿得到時，依 SPEC 用 mtime。"""
    monkeypatch.setattr(photos, "_mtime_iso", lambda path: "2026-11-11T11:11:11")
    drop(config, "20260101-000000_IMG_4821.jpg")
    result = inbox_mod.intake(config, repo)
    assert result.archived[0].photo.captured_at == "2026-11-11T11:11:11"


def test_intake_without_any_timestamp_uses_current_time(config, repo, monkeypatch):
    """EXIF、mtime、檔名都沒有 → 時間留空，檔名用現在。"""
    monkeypatch.setattr(photos, "_mtime_iso", lambda path: None)
    drop(config, "IMG_4821.jpg")
    result = inbox_mod.intake(config, repo)

    name = config.resolve(result.archived[0].photo.filename).name
    assert name.endswith("_IMG_4821.jpg")
    assert len(name) == len("20261002-143022_") + len("IMG_4821.jpg")
    assert result.archived[0].photo.captured_at is None
    assert result.observation.captured_at is None


def test_intake_marks_source_and_angle(config, repo):
    drop(config, "IMG_4821.jpg")
    result = inbox_mod.intake(config, repo, angle="label", source="upload")
    stored = repo.get_photo(result.archived[0].photo.id)
    assert stored.angle == "label"
    assert stored.source == "upload"


# ----------------------------------------------------------------------
# 原始照片不可被覆蓋
# ----------------------------------------------------------------------


def test_second_intake_never_overwrites_the_first(config, repo):
    """兩批照片先後入庫，各自的資料夾分開，檔名也互不覆蓋。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    first = inbox_mod.intake(config, repo)

    drop(config, "IMG_4821.jpg", exif="2026:10:02 15:00:00")
    second = inbox_mod.intake(config, repo)

    assert first.item.id == "ITM-0001"
    assert second.item.id == "ITM-0002"
    assert first.archived[0].photo.filename != second.archived[0].photo.filename
    assert config.resolve(first.archived[0].photo.filename).exists()
    assert config.resolve(second.archived[0].photo.filename).exists()
    # 兩張的原始檔名都留著
    assert repo.get_photo(second.archived[0].photo.id).orig_name == "IMG_4821.jpg"


def test_same_item_never_overwrites_an_existing_original(config, repo):
    """同一件商品分兩次匯入同名照片 → 第二張加流水號而不是蓋掉。"""
    item = repo.create_item()
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    first = inbox_mod.intake(config, repo, item_id=item.id, kind="recheck")
    keeper = config.resolve(first.archived[0].photo.filename)

    # 同樣的檔名與時間戳，但位元組不同（換個尺寸），所以不會被去重擋掉
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22", width=1600, height=1200)
    second = inbox_mod.intake(config, repo, item_id=item.id, kind="recheck")

    assert sorted(p.name for p in inbox_mod.original_dir(config, item.id).iterdir()) == [
        "20261002-143022_IMG_4821-2.jpg",
        "20261002-143022_IMG_4821.jpg",
    ]
    assert keeper.read_bytes() == make_jpeg(exif="2026:10:02 14:30:22")
    assert second.archived[0].duplicate_of is None


def test_unique_target_suffixes_until_free(tmp_path: Path):
    directory = tmp_path / "original"
    directory.mkdir()
    (directory / "a.jpg").write_bytes(b"1")
    assert inbox_mod.unique_target(directory, "a.jpg").name == "a-2.jpg"
    (directory / "a-2.jpg").write_bytes(b"2")
    assert inbox_mod.unique_target(directory, "a.jpg").name == "a-3.jpg"
    assert inbox_mod.unique_target(directory, "b.jpg").name == "b.jpg"


def test_unique_target_without_extension(tmp_path: Path):
    directory = tmp_path / "original"
    directory.mkdir()
    (directory / "blob").write_bytes(b"1")
    assert inbox_mod.unique_target(directory, "blob").name == "blob-2"


def test_intake_leaves_existing_originals_untouched(config, repo):
    """先手動放一個同名檔在 original/，匯入不能踩掉它。"""
    target_dir = config.files_dir / "ITM-0001" / "original"
    target_dir.mkdir(parents=True)
    keeper = target_dir / "20261002-143022_IMG_4821.jpg"
    keeper.write_bytes(b"original evidence already here")

    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    inbox_mod.intake(config, repo)

    assert keeper.read_bytes() == b"original evidence already here"
    assert (target_dir / "20261002-143022_IMG_4821-2.jpg").exists()


# ----------------------------------------------------------------------
# sha256 去重
# ----------------------------------------------------------------------


def test_reimporting_the_same_item_is_a_noop(config, repo):
    """同一件商品重複匯入同一張照片：不多一份、不多一筆。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    first = inbox_mod.intake(config, repo)
    item_id = first.item.id

    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    second = inbox_mod.intake(config, repo, item_id=item_id)

    assert second.archived == []
    assert [entry.path.name for entry in second.skipped] == ["IMG_4821.jpg"]
    assert len(repo.list_photos(item_id=item_id)) == 1
    assert second.item.id == item_id
    assert second.observation is None
    # 檔案留在 inbox，因為沒有被搬走
    assert (config.inbox_dir / "IMG_4821.jpg").exists()


def test_duplicate_across_items_is_archived_and_flagged(config, repo):
    """別的商品有同樣位元組：照樣歸檔，但回報撞號讓人判斷。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    first = inbox_mod.intake(config, repo)

    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    second = inbox_mod.intake(config, repo)

    assert len(second.archived) == 1
    assert second.duplicates[0].duplicate_of == first.archived[0].photo.id
    assert second.item.id == "ITM-0002"
    assert len(repo.list_photos(item_id="ITM-0002")) == 1


def test_derived_photo_does_not_block_original_reimport(config, repo):
    item = repo.create_item()
    repo.add_photo(
        item.id, f"files/{item.id}/derived/a.thumb.webp",
        role="derived", sha256="0" * 64,
    )
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo, item_id=item.id)
    assert len(result.archived) == 1


def test_find_photos_by_sha256(repo):
    item = repo.create_item()
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", sha256="ab" * 32)
    assert [row.id for row in repo.find_photos_by_sha256("ab" * 32)] == [photo.id]
    assert repo.find_photos_by_sha256("cd" * 32) == []
    assert repo.find_photos_by_sha256("ab" * 32, item_id="ITM-9999") == []
    assert repo.find_photos_by_sha256("ab" * 32, role="derived") == []


# ----------------------------------------------------------------------
# 異常情況
# ----------------------------------------------------------------------


def test_intake_of_missing_file_raises(config, repo):
    with pytest.raises(ValidationError):
        inbox_mod.intake(config, repo, [config.inbox_dir / "nope.jpg"])


def test_intake_of_empty_inbox_raises(config, repo):
    with pytest.raises(ValidationError):
        inbox_mod.intake(config, repo)
    assert repo.list_items() == []


def test_intake_rejects_file_outside_data_root(config, repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "elsewhere.jpg"
    outside.write_bytes(make_jpeg())
    with pytest.raises(Exception) as excinfo:
        inbox_mod.intake(config, repo, [outside])
    assert "資料根目錄" in str(excinfo.value)
    assert outside.exists()


def test_intake_rejects_directory(config, repo):
    (config.inbox_dir / "sub").mkdir()
    with pytest.raises(ValidationError):
        inbox_mod.intake(config, repo, [config.inbox_dir / "sub"])


def test_intake_deduplicates_the_same_path(config, repo):
    path = drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo, [path, path, path])
    assert len(result.archived) == 1


def test_corrupt_photo_is_still_archived(config, repo):
    """壞掉的照片不能讓人整批卡住，也不能被丟掉。"""
    (config.inbox_dir / "broken.jpg").write_bytes(b"\xff\xd8\xff\xe1not really exif")
    result = inbox_mod.intake(config, repo)

    stored = repo.get_photo(result.archived[0].photo.id)
    assert stored.width is None and stored.height is None
    assert stored.captured_at is not None
    assert config.resolve(stored.filename).exists()


def test_zero_byte_photo_is_archived(config, repo):
    (config.inbox_dir / "empty.jpg").write_bytes(b"")
    result = inbox_mod.intake(config, repo)
    stored = repo.get_photo(result.archived[0].photo.id)
    assert stored.bytes == 0
    assert config.resolve(stored.filename).exists()


def test_failure_rolls_back_files_and_database(config, repo, monkeypatch):
    """第二張出錯時，第一張要搬回去、資料庫要整筆撤銷。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    keep = drop(config, "IMG_4824.jpg", exif="2026:10:02 14:33:55")

    from shop import repo as repo_mod

    original_add = repo_mod.Repository.add_photo
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("資料庫寫不進去")
        return original_add(self, *args, **kwargs)

    monkeypatch.setattr(repo_mod.Repository, "add_photo", flaky)
    with pytest.raises(RuntimeError):
        inbox_mod.intake(config, repo)

    assert repo.list_items() == []
    assert repo.list_photos() == []
    assert keep.exists()  # 檔案搬回 inbox
    assert (config.inbox_dir / "IMG_4821.jpg").exists()
    assert not (config.files_dir / "ITM-0001" / "original").exists() or not list(
        (config.files_dir / "ITM-0001" / "original").iterdir()
    )


def test_failure_after_moves_keeps_earlier_files(config, repo, monkeypatch):
    drop(config, "a.jpg", exif="2026:10:02 14:30:22")
    drop(config, "b.jpg", exif="2026:10:02 14:31:00")
    drop(config, "c.jpg", exif="2026:10:02 14:32:00")

    from shop import repo as repo_mod

    original_add = repo_mod.Repository.add_photo
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("爆了")
        return original_add(self, *args, **kwargs)

    monkeypatch.setattr(repo_mod.Repository, "add_photo", flaky)
    with pytest.raises(RuntimeError):
        inbox_mod.intake(config, repo)

    assert repo.list_photos() == []
    assert sorted(p.name for p in config.inbox_dir.iterdir()) == ["a.jpg", "b.jpg", "c.jpg"]
    archived = config.files_dir / "ITM-0001" / "original"
    assert not archived.exists() or list(archived.iterdir()) == []


def test_unicode_filename_survives(config, repo):
    drop(config, "商品-主機板-正面.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    stored = repo.get_photo(result.archived[0].photo.id)
    assert stored.orig_name == "商品-主機板-正面.jpg"
    assert config.resolve(stored.filename).exists()


def test_illegal_characters_are_replaced(config, repo):
    """Windows 上根本建不出這些檔名，所以端到端用可建立的名字，
    真正的置換規則由 test_safe_filename 逐項驗證。"""
    drop(config, "IMG 4821 (正面).jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    name = config.resolve(result.archived[0].photo.filename).name
    assert name == "20261002-143022_IMG 4821 (正面).jpg"
    assert repo.get_photo(result.archived[0].photo.id).orig_name == "IMG 4821 (正面).jpg"


def test_very_long_filename_is_truncated(config, repo):
    name = "很長的檔名" * 40 + ".jpg"
    drop(config, name, exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    target = config.resolve(result.archived[0].photo.filename)
    assert target.exists()
    assert len(target.name.encode("utf-8")) <= 255
    assert target.name.endswith(".jpg")


def test_missing_observation_item_is_rejected(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    with pytest.raises(Exception) as excinfo:
        inbox_mod.intake(config, repo, item_id="ITM-9999")
    assert "ITM-9999" in str(excinfo.value)
    # 檔案沒被搬走
    assert (config.inbox_dir / "IMG_4821.jpg").exists()


def test_bad_observation_kind_is_rejected(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    with pytest.raises(ValidationError):
        inbox_mod.intake(config, repo, kind="return")
    assert (config.inbox_dir / "IMG_4821.jpg").exists()
    assert repo.list_items() == []


# ----------------------------------------------------------------------
# 與 shopctl verify 的整合
# ----------------------------------------------------------------------


def test_verify_passes_after_intake(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    inbox_mod.intake(config, repo)
    report = db_mod.verify(config)
    assert report["missing_original_photos"] == []
    assert report["ok"] is True


def test_verify_detects_a_deleted_original(config, repo):
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    os.unlink(config.resolve(result.archived[0].photo.filename))

    report = db_mod.verify(config)
    assert report["ok"] is False
    assert report["missing_original_photos"] == [result.archived[0].photo.filename]


# ----------------------------------------------------------------------
# 資料夾可搬移（SPEC-v1 §1、§3、§11.7）
# ----------------------------------------------------------------------


def test_whole_data_root_can_be_moved(config, repo, tmp_path_factory):
    """整份資料夾搬到別的位置後照樣運作 —— 資料庫裡沒有絕對路徑。"""
    drop(config, "IMG_4821.jpg", exif="2026:10:02 14:30:22")
    result = inbox_mod.intake(config, repo)
    stored = repo.get_photo(result.archived[0].photo.id)

    moved = tmp_path_factory.mktemp("moved") / "shop"
    shutil.copytree(config.data_root, moved)

    new_config = config_mod.load(moved)
    with Repository.open(new_config) as new_repo:
        found = new_repo.get_photo(stored.id)
        assert found.filename == stored.filename
        assert new_repo.get_item(found.item_id).id == found.item_id
        # 相對路徑在新位置仍然指得到實體檔案
        assert new_config.resolve(found.filename).exists()
        assert db_mod.verify(new_config)["ok"] is True
    # 舊位置與新位置的檔案內容一致
    assert new_config.resolve(found.filename).read_bytes() == (
        config.resolve(stored.filename).read_bytes()
    )


# ----------------------------------------------------------------------
# safe_filename / unique_target 細節
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a.jpg", "20261002-143022_a.jpg"),
        ("a b.jpg", "20261002-143022_a b.jpg"),
        ("a<b>c.jpg", "20261002-143022_a_b_c.jpg"),
        ("a\\b.jpg", "20261002-143022_a_b.jpg"),
        ("...", "20261002-143022_photo"),
        ("", "20261002-143022_photo"),
        # 已經是時間戳開頭的檔名不重複加前綴
        ("20261002-143022_IMG.jpg", "20261002-143022_IMG.jpg"),
    ],
)
def test_safe_filename(raw, expected):
    assert inbox_mod.safe_filename(raw, "20261002-143022_") == expected


def test_safe_filename_keeps_extension_when_truncating():
    result = inbox_mod.safe_filename("x" * 400 + ".jpeg", "20261002-143022_")
    assert result.endswith(".jpeg")
    assert len(result.encode("utf-8")) <= 255


def test_safe_filename_never_exceeds_limit_with_multibyte():
    result = inbox_mod.safe_filename("測" * 200 + ".jpg", "20261002-143022_")
    assert len(result.encode("utf-8")) <= 255
    assert result.endswith(".jpg")
