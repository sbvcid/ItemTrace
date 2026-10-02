"""測試共用的暫存資料根目錄與照片檔案工具。

每個測試都拿到自己的 tmp_path，schema 由 shop.db.init() 套用，
所以測試不會碰到真正的 DATA_ROOT。
"""

from __future__ import annotations

import os
import struct
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shop import config as config_mod  # noqa: E402
from shop import db as db_mod  # noqa: E402
from shop.repo import Repository  # noqa: E402


@pytest.fixture()
def config(tmp_path: Path) -> config_mod.Config:
    """指向 tmp_path 的 Config，schema 已套用。"""
    cfg = config_mod.load(tmp_path)
    db_mod.init(cfg)
    config_mod.ensure_dirs(cfg)
    return cfg


@pytest.fixture()
def repo(config: config_mod.Config):
    with Repository.open(config) as repository:
        yield repository


@pytest.fixture()
def client(config: config_mod.Config):
    """指向 tmp DATA_ROOT 的 HTTP 測試客戶端。"""
    from fastapi.testclient import TestClient

    from shop.api import create_app

    with TestClient(create_app(config)) as test_client:
        yield test_client


# ----------------------------------------------------------------------
# 合成 JPEG
#
# 不引入 Pillow（專案只用標準函式庫），所以自己組一個結構正確的最小 JPEG：
# SOI +（選填）APP1/Exif + SOF0 + EOI。shop.photos 解析的就是這些標記。
# ----------------------------------------------------------------------


def _exif_tiff(datetime_original: str, ifd0_datetime: str | None) -> bytes:
    """組出小端 TIFF 區塊，ExifIFD 有 DateTimeOriginal，IFD0 可選 DateTime。"""
    stamp = datetime_original.encode("ascii") + b"\x00"
    ifd0_count = 2 if ifd0_datetime else 1
    ifd0_size = 2 + ifd0_count * 12 + 4
    header_size = 8
    data_start = header_size + ifd0_size
    exif_ifd_offset = data_start + len(stamp)
    exif_ifd_size = 2 + 12 + 4
    exif_data_start = exif_ifd_offset + exif_ifd_size

    out = bytearray(b"II" + struct.pack("<HI", 42, header_size))
    out += struct.pack("<H", ifd0_count)
    if ifd0_datetime:
        out += _entry(0x0132, 2, len(stamp), data_start)
    out += _entry(0x8769, 4, 1, exif_ifd_offset)
    out += struct.pack("<I", 0)  # next IFD
    out += stamp

    out += struct.pack("<H", 1)
    out += _entry(0x9003, 2, len(stamp), exif_data_start)
    out += struct.pack("<I", 0)
    out += stamp
    return bytes(out)


def _entry(tag: int, kind: int, count: int, value: int) -> bytes:
    return struct.pack("<HHII", tag, kind, count, value)


def make_jpeg(
    *, exif: str | None = None, ifd0_datetime: str | None = None,
    width: int = 4032, height: int = 3024, sof: int = 0xC0,
) -> bytes:
    """最小可解析的 JPEG。exif 傳 'YYYY:MM:DD HH:MM:SS'。"""
    out = bytearray(b"\xff\xd8")  # SOI
    if exif is not None or ifd0_datetime is not None:
        tiff = _exif_tiff(exif or "1970:01:01 00:00:00", ifd0_datetime)
        payload = b"Exif\x00\x00" + tiff
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    # SOF0：precision, height, width, 3 components
    segment = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    out += bytes((0xFF, sof)) + struct.pack(">H", len(segment) + 2) + segment
    out += b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"  # SOS
    out += b"\x00" * 32  # 假的掃描資料
    out += b"\xff\xd9"  # EOI
    return bytes(out)


def write_photo(path: Path, *, exif: str | None = None, **kwargs) -> Path:
    """在 inbox 寫一張合成照片，沒有 EXIF 時退回 mtime。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_jpeg(exif=exif, **kwargs))
    return path


def set_mtime(path: Path, when: datetime) -> Path:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
    return path
