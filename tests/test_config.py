"""config 的兩條硬約束：資料夾可搬移、根目錄不依賴文件（SPEC-v1 §1、§3）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shop import config as config_mod
from shop.config import ConfigError


def test_paths_are_relative_to_data_root(tmp_path: Path):
    cfg = config_mod.load(tmp_path)
    assert cfg.data_root == tmp_path.resolve()
    assert cfg.database == cfg.data_root / "catalog.db"
    assert cfg.files_dir == cfg.data_root / "files"
    assert cfg.inbox_dir == cfg.data_root / "inbox"


def test_database_stores_relative_paths_only(tmp_path: Path):
    cfg = config_mod.load(tmp_path)
    stored = cfg.relative(tmp_path / "files" / "ITM-0001" / "original" / "a.jpg")
    assert stored == "files/ITM-0001/original/a.jpg"
    assert cfg.resolve(stored) == tmp_path / "files" / "ITM-0001" / "original" / "a.jpg"


def test_relative_rejects_path_outside_data_root(tmp_path: Path):
    cfg = config_mod.load(tmp_path)
    with pytest.raises(ConfigError):
        cfg.relative(Path("C:/somewhere/else/a.jpg"))


def test_data_root_can_be_pointed_elsewhere(tmp_path: Path):
    (tmp_path / "config.json").write_text(
        json.dumps({"data_root": "D:/shop-data"}), encoding="utf-8"
    )
    cfg = config_mod.load(tmp_path)
    assert cfg.data_root == Path("D:/shop-data")


def test_find_base_dir_uses_code_not_documents(tmp_path: Path):
    """刪掉 SPEC-v1.md 與 README 仍要能找到專案根目錄。"""
    (tmp_path / "shop").mkdir()
    (tmp_path / "shopctl.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    assert config_mod.find_base_dir(tmp_path / "shop" / "db.py") == tmp_path.resolve()


def test_find_base_dir_accepts_config_json_only(tmp_path: Path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert config_mod.find_base_dir(tmp_path / "shop") == tmp_path.resolve()


def test_load_without_config_file_uses_defaults(tmp_path: Path):
    cfg = config_mod.load(tmp_path)
    assert cfg.backup_keep == 30
    assert cfg.server_port == 8731


def test_broken_config_reports_the_file(tmp_path: Path):
    (tmp_path / "config.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        config_mod.load(tmp_path)
    assert "config.json" in str(excinfo.value)


def test_config_with_utf8_bom_is_accepted(tmp_path: Path):
    """Windows 用記事本存 JSON 會加 BOM，不能因此讀不進來。"""
    (tmp_path / "config.json").write_text(
        json.dumps({"data_root": "D:/shop-data", "server_port": 9000}),
        encoding="utf-8-sig",
    )
    cfg = config_mod.load(tmp_path)
    assert cfg.data_root == Path("D:/shop-data")
    assert cfg.server_port == 9000


def test_config_without_bom_still_works(tmp_path: Path):
    (tmp_path / "config.json").write_text(
        json.dumps({"server_port": 9001}), encoding="utf-8"
    )
    assert config_mod.load(tmp_path).server_port == 9001


def test_write_example_copies_from_config_example(tmp_path: Path):
    """init 產生 config.json 這條路徑也要吃得住 BOM。"""
    (tmp_path / "config.example.json").write_text(
        json.dumps({"data_root": ".", "server_port": 9123}), encoding="utf-8-sig"
    )
    written = config_mod.write_example(tmp_path)
    assert config_mod.load(tmp_path).server_port == 9123
    # 寫出來的是乾淨的 utf-8（沒有 BOM）
    assert not written.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_example_does_not_overwrite_existing(tmp_path: Path):
    (tmp_path / "config.json").write_text(json.dumps({"server_port": 1}), encoding="utf-8")
    config_mod.write_example(tmp_path)
    assert config_mod.load(tmp_path).server_port == 1
