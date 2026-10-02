"""設定檔載入與資料根目錄解析。

設定檔放在專案根目錄的 config.json。所有路徑一律解析成絕對路徑後
才寫進資料庫，資料庫內則只存相對於資料根目錄的路徑，確保整份資料夾可搬移。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "config.json"
DEFAULTS = {
    "data_root": ".",
    "database": "catalog.db",
    "backup_dir": "backups",
    "backup_keep": 30,
    "server_host": "127.0.0.1",
    "server_port": 8731,
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    base_dir: Path
    data_root: Path
    database: Path
    backup_dir: Path
    backup_keep: int
    server_host: str
    server_port: int

    @property
    def config_path(self) -> Path:
        return self.base_dir / CONFIG_NAME

    @property
    def files_dir(self) -> Path:
        return self.data_root / "files"

    @property
    def inbox_dir(self) -> Path:
        return self.data_root / "inbox"

    def relative(self, path: Path) -> str:
        """把絕對路徑轉成相對於資料根目錄的字串，供資料庫儲存。"""
        try:
            return path.resolve().relative_to(self.data_root).as_posix()
        except ValueError as exc:
            raise ConfigError(
                f"{path} 不在資料根目錄 {self.data_root} 內，無法轉為相對路徑"
            ) from exc

    def resolve(self, relative: str) -> Path:
        """把資料庫存的相對路徑還原成絕對路徑。"""
        return self.data_root / relative


def find_base_dir(start: Path | None = None) -> Path:
    """從 shop/ 往上找專案根目錄。

    以 shopctl.py 與 config.json 為定位依據，不依賴任何文件 ——
    搬移或刪掉文件都不該讓工具壞掉。
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / "shop").is_dir() and (
            (parent / "shopctl.py").exists() or (parent / CONFIG_NAME).exists()
        ):
            return parent
    return here.parent


def load(base_dir: Path | None = None) -> Config:
    base = (base_dir or find_base_dir()).resolve()
    path = base / CONFIG_NAME
    raw = dict(DEFAULTS)
    if path.exists():
        try:
            # utf-8-sig：Windows 用記事本存檔預設會加 BOM，帶 BOM 會讓
            # json.loads 直接失敗。兩邊都接受，只是把 BOM 當不存在。
            raw.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} 不是合法的 JSON：{exc}") from exc

    data_root = _resolve(base, raw["data_root"])
    return Config(
        base_dir=base,
        data_root=data_root,
        database=data_root / raw["database"],
        backup_dir=_resolve(base, raw["backup_dir"]),
        backup_keep=int(raw["backup_keep"]),
        server_host=str(raw["server_host"]),
        server_port=int(raw["server_port"]),
    )


def write_example(base_dir: Path | None = None) -> Path:
    """首次初始化時產生 config.json（若尚不存在）。"""
    base = base_dir or find_base_dir()
    target = base / CONFIG_NAME
    if target.exists():
        return target
    example = base / "config.example.json"
    source = example if example.exists() else base / "config.example.json"
    raw = json.loads(source.read_text(encoding="utf-8-sig")) if source.exists() else DEFAULTS
    target.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def ensure_dirs(config: Config) -> None:
    for path in (config.data_root, config.files_dir, config.inbox_dir, config.backup_dir):
        path.mkdir(parents=True, exist_ok=True)


def _resolve(base: Path, value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()