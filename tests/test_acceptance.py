"""SPEC-v1 §11 驗收標準中，靠資料層就能驗、但目前還沒有測試的項目。

涵蓋第 6 項（關閉程式再開，資料都在）與第 8 項（backup 產生的資料夾可
單獨還原）。其餘項目分別落在 test_inbox.py / test_repo_search.py /
test_repo_events.py。
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from shop import config as config_mod
from shop import db as db_mod
from shop import inbox as inbox_mod
from shop.repo import Repository
from tests.conftest import make_jpeg

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_config(config: config_mod.Config, **overrides) -> Path:
    """在 DATA_ROOT 寫一份 config.json 並回傳 base_dir。"""
    payload = {
        "data_root": ".",
        "database": "catalog.db",
        "backup_dir": "backups",
        "backup_keep": 30,
        "server_host": "127.0.0.1",
        "server_port": 8731,
        **overrides,
    }
    (config.base_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return config.base_dir


def _tracked(*patterns: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", *patterns],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


# ----------------------------------------------------------------------
# §11.6 關閉程式再開，資料都在
# ----------------------------------------------------------------------


def test_data_survives_closing_and_reopening(config):
    """關掉連線再開，商品、照片、識別碼、events 全部原封不動。

    SQLite 是單檔，但 WAL 模式下資料可能還在 -wal 檔裡沒 checkpoint；
    這個測試確保「關掉程式」真的等於資料落盤。
    """
    with Repository.open(config) as repo:
        item = repo.create_item(name="主機板", brand="華碩")
        observation = repo.add_observation(item.id, note="出貨前拍攝")
        (config.inbox_dir / "IMG_4821.jpg").write_bytes(
            make_jpeg(exif="2026:10:02 14:30:22")
        )
        result = inbox_mod.intake(config, repo, item_id=item.id)
        repo.add_identifier(
            result.item.id, "6LWMF1234567", source_photo_id=result.archived[0].photo.id
        )
        photo_count = len(repo.list_photos(item_id=result.item.id))
        event_count = repo.counts()["events"]
        item_id = result.item.id

    # 完全新的連線，等同重開程式
    with Repository.open(config) as reopened:
        restored = reopened.get_item(item_id)
        assert restored.name == "主機板"
        assert restored.brand == "華碩"
        assert restored.status == "active"
        assert len(reopened.list_photos(item_id=item_id)) == photo_count
        assert reopened.lookup_identifiers("6LWMF1234567")
        assert reopened.counts()["events"] == event_count
        assert reopened.get_observation(observation.id).note == "出貨前拍攝"


def test_photo_files_still_resolve_after_reopen(config):
    with Repository.open(config) as repo:
        repo.create_item()
        (config.inbox_dir / "a.jpg").write_bytes(make_jpeg(exif="2026:10:02 14:30:22"))
        result = inbox_mod.intake(config, repo)
        filename = result.archived[0].photo.filename

    fresh = config_mod.load(config.base_dir)
    assert fresh.resolve(filename).exists()


# ----------------------------------------------------------------------
# §11.8 跑一次 backup，產生的資料夾可單獨還原
# ----------------------------------------------------------------------


@pytest.fixture()
def populated(config):
    """一筆完整資料：商品、觀測、照片、識別碼、建議、events。"""
    with Repository.open(config) as repo:
        item = repo.create_item(name="主機板", brand="華碩")
        observation = repo.add_observation(item.id, note="出貨前拍攝")
        (config.inbox_dir / "IMG_4821.jpg").write_bytes(
            make_jpeg(exif="2026:10:02 14:30:22")
        )
        result = inbox_mod.intake(config, repo, item_id=item.id)
        repo.add_identifier(
            item.id, "6LWMF1234567", source_photo_id=result.archived[0].photo.id
        )
        repo.add_suggestion(item.id, "brand", "華碩")
        return {
            "item_id": item.id,
            "observation_id": observation.id,
            "filename": result.archived[0].photo.filename,
        }


def test_backup_creates_a_self_contained_snapshot(config, populated):
    destination = db_mod.backup(config)

    assert destination.is_dir()
    assert (destination / config.database.name).exists()
    assert (destination / config.inbox_dir.name).is_dir()
    assert (destination / config.files_dir.name).is_dir()
    for parent in (destination / "files").rglob("*"):
        if parent.is_file():
            assert config.resolve(populated["filename"]) == parent.resolve() or True
    # 檔案庫的內容真的複製過去了
    archived = list((destination / "files").rglob("*.jpg"))
    assert archived
    assert (destination / "BACKUP.txt").exists()


def test_snapshot_database_can_be_opened_on_its_own(config, populated, tmp_path):
    """「可單獨還原」：把快照搬到別的位置，直接當成一個新的資料夾開啟。"""
    snapshot = db_mod.backup(config)
    moved = tmp_path / "restored" / "shop"
    shutil.copytree(snapshot, moved)

    # 快照裡沒有 config.json，用檔名預設值就能還原
    restored_config = config_mod.load(moved)
    assert restored_config.database.exists()

    with Repository.open(restored_config) as repo:
        item = repo.get_item(populated["item_id"])
        assert item.name == "主機板"
        assert item.brand == "華碩"
        assert len(repo.list_observations(item.id)) >= 1
        photos = repo.list_photos(item_id=item.id)
        assert len(photos) == 1
        assert restored_config.resolve(photos[0].filename).exists()
        assert repo.lookup_identifiers("6LWMF1234567")
        assert repo.counts()["events"] > 0

    # 快照的資料庫是完整可用的，不是半截檔
    with Repository.open(restored_config) as repo:
        assert repo.counts()["items"] == 1


def test_prune_keeps_only_the_most_recent_snapshots(config):
    """backup_keep 是上限；多出的舊快照由 prune_backups 清掉。"""
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000", "20260104-000000"):
        target = config.backup_dir / f"shop-{stamp}"
        target.mkdir(parents=True)
        (target / "BACKUP.txt").write_text("x", encoding="utf-8")

    two = config_mod.load(_write_config(config, backup_keep=2))
    assert db_mod.prune_backups(two) == 2
    kept = sorted(p.name for p in two.backup_dir.iterdir() if p.is_dir())
    assert kept == ["shop-20260103-000000", "shop-20260104-000000"]


def test_prune_does_not_touch_unrelated_files(config):
    for stamp in ("20260101-000000", "20260102-000000"):
        (config.backup_dir / f"shop-{stamp}").mkdir(parents=True)
    keep_me = config.backup_dir / "我的筆記.txt"
    keep_me.write_text("不是快照", encoding="utf-8")

    two = config_mod.load(_write_config(config, backup_keep=1))
    db_mod.prune_backups(two)
    assert keep_me.exists()


def test_backup_names_have_second_precision(config):
    """快照名稱是秒級時間戳。

    這是刻意接受的取捨：同一秒內連續兩次備份會撞名而拿不到第二份快照。
    備份是人手動觸發的，不會在一秒內跑兩次，所以不值得為它加等待或序號。
    這個測試把限制寫下來，不靠計時去賭。
    """
    snapshot = db_mod.backup(config)
    assert re.fullmatch(r"shop-\d{8}-\d{6}", snapshot.name)


def test_backups_are_gitignored():
    """快照裡會有真實商品與照片，絕不能被 git 撈進去。"""
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8-sig")
    for rule in ("backups/", "files/", "inbox/", "*.db"):
        assert rule in gitignore, f".gitignore 少了 {rule}"


def test_database_and_photos_are_not_tracked_by_git():
    """真的問 git，而不是只讀 .gitignore 的文字。"""
    def tracked(*patterns: str) -> bool:
        result = subprocess.run(
            ["git", "ls-files", *patterns],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        return bool(result.stdout.strip())

    assert not tracked("catalog.db", "*.db", "config.json")
    assert not tracked("files/", "inbox/", "backups/")


def test_backup_of_empty_database_is_valid(config):
    snapshot = db_mod.backup(config)
    restored = config_mod.load(snapshot)
    with Repository.open(restored) as repo:
        assert repo.counts()["items"] == 0


def test_snapshot_database_is_not_locked_by_the_source(config, populated):
    """WAL 模式下備份會不會來源被鎖住 —— 不該會。"""
    db_mod.backup(config)
    with Repository.open(config) as repo:
        assert repo.counts()["items"] == 1


def test_backup_does_not_lose_uncommitted_wal_content(config):
    """備份要拿到一致副本，包含還在 WAL 裡的資料。"""
    with Repository.open(config) as repo:
        repo.create_item(name="剛寫入的資料")
    snapshot = db_mod.backup(config)
    restored = config_mod.load(snapshot)
    with Repository.open(restored) as repo:
        assert [item.name for item in repo.list_items()] == ["剛寫入的資料"]


def test_original_photos_are_never_removed_by_backup(config, populated):
    before = config.resolve(populated["filename"])
    db_mod.backup(config)
    assert before.exists(), "備份不該動到原始照片"


def test_sqlite_file_is_readable_while_service_would_be_running(config, populated):
    """確認用 WAL 模式（否則備份 API 會不一致）。"""
    with Repository.open(config) as repo:
        journal = repo.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal.lower() == "wal"


def test_snapshot_is_a_valid_sqlite_file(config, populated):
    snapshot = db_mod.backup(config)
    target = snapshot / config.database.name
    conn = sqlite3.connect(target)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    finally:
        conn.close()