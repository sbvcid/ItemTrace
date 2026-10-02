"""EXIF / 尺寸 / 時間退路的解析（SPEC-v1 §14.4、§3）。"""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

import pytest

from shop import photos
from tests.conftest import make_jpeg


def test_reads_exif_datetime_original(tmp_path: Path):
    path = tmp_path / "a.jpg"
    path.write_bytes(make_jpeg(exif="2026:10:02 14:33:55"))
    captured, source = photos.read_captured_at(path)
    assert captured == "2026-10-02T14:33:55"
    assert source == photos.EXIF_SOURCE


def test_falls_back_to_ifd0_datetime(tmp_path: Path):
    """有些相機只寫 IFD0 的 DateTime，沒有 ExifIFD。"""
    path = tmp_path / "a.jpg"
    path.write_bytes(make_jpeg(exif="2026:10:02 14:33:55", ifd0_datetime="2020:01:02 03:04:05"))
    captured, source = photos.read_captured_at(path)
    assert captured == "2026-10-02T14:33:55"
    assert source == photos.EXIF_SOURCE


def test_reads_ifd0_datetime_when_exif_ifd_absent():
    from tests.conftest import _entry

    # 手工組一個只有 IFD0 DateTime 的 TIFF
    stamp = b"2026:10:02 14:33:55\x00"
    ifd0_size = 2 + 12 + 4
    out = bytearray(b"II" + struct.pack("<HI", 42, 8))
    out += struct.pack("<H", 1)
    out += _entry(0x0132, 2, len(stamp), 8 + ifd0_size)
    out += struct.pack("<I", 0)
    out += stamp
    data = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(out) + 2 + 6) + b"Exif\x00\x00" + bytes(out)
    assert photos.read_exif_captured_at(data) == "2026-10-02T14:33:55"


def test_falls_back_to_mtime_when_exif_missing(tmp_path: Path):
    path = tmp_path / "IMG_4821.jpg"
    path.write_bytes(make_jpeg())
    from tests.conftest import set_mtime

    set_mtime(path, datetime(2026, 10, 2, 9, 8, 7))
    captured, source = photos.read_captured_at(path)
    assert source == photos.MTIME_SOURCE
    assert captured == datetime.fromtimestamp(path.stat().st_mtime).isoformat(
        timespec="seconds"
    )


def test_falls_back_to_filename_when_mtime_unavailable(tmp_path: Path, monkeypatch):
    """mtime 讀不到時才用檔名時間戳（SPEC-v1 §14.4 的順序）。"""
    path = tmp_path / "20261002-143022_IMG_4821.jpg"
    path.write_bytes(make_jpeg())

    def no_stat(self, *args, **kwargs):
        raise OSError("檔案不見了")

    monkeypatch.setattr(Path, "stat", no_stat)
    captured, source = photos.read_captured_at(path)
    assert captured == "2026-10-02T14:30:22"
    assert source == photos.FILENAME_SOURCE


def test_captured_at_is_empty_when_nothing_works(tmp_path: Path, monkeypatch):
    path = tmp_path / "no-timestamp.jpg"
    path.write_bytes(make_jpeg())

    def no_stat(self, *args, **kwargs):
        raise OSError("檔案不見了")

    monkeypatch.setattr(Path, "stat", no_stat)
    captured, source = photos.read_captured_at(path)
    assert captured is None
    assert source == photos.NO_SOURCE


def test_corrupt_exif_does_not_raise(tmp_path: Path):
    """EXIF 壞掉不能中斷流程（§14.4 的整個理由）。"""
    path = tmp_path / "a.jpg"
    payload = b"Exif\x00\x00" + b"II" + b"\xff" * 40
    path.write_bytes(
        b"\xff\xd8\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
    )
    captured, source = photos.read_captured_at(path)
    assert source == photos.MTIME_SOURCE
    assert captured is not None


def test_not_a_jpeg_returns_no_exif():
    assert photos.read_exif_captured_at(b"PNG\r\n\x1a\n") is None
    assert photos.read_exif_captured_at(b"") is None


def test_broken_tiff_magic_is_ignored():
    payload = b"Exif\x00\x00" + b"II" + struct.pack("<HI", 43, 8) + b"\x00" * 16
    data = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    assert photos.read_exif_captured_at(data) is None


def test_garbage_exif_date_falls_through_to_next_source(tmp_path: Path):
    path = tmp_path / "a.jpg"
    path.write_bytes(make_jpeg(exif="0000:00:00 00:00:00"))
    captured, source = photos.read_captured_at(path)
    assert source == photos.MTIME_SOURCE
    assert captured is not None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20261002-143022_IMG_4821.jpg", "2026-10-02T14:30:22"),
        ("20261002-143022", "2026-10-02T14:30:22"),
        ("2026-10-02-143022.jpg", None),
        ("IMG_4821.jpg", None),
        ("99999999-999999_whatever.jpg", None),
        ("20261301-000000.jpg", None),
    ],
)
def test_parse_filename_timestamp(name, expected):
    assert photos.parse_filename_timestamp(name) == expected


def test_reads_jpeg_size(tmp_path: Path):
    path = tmp_path / "a.jpg"
    path.write_bytes(make_jpeg(width=4032, height=3024))
    assert photos.read_jpeg_size(path.read_bytes()) == (4032, 3024)


def test_size_of_non_jpeg_is_none():
    assert photos.read_jpeg_size(b"GIF89a") is None
    assert photos.read_jpeg_size(b"\xff\xd8") is None  # 只有 SOI


def test_progressive_jpeg_size(tmp_path: Path):
    """SOF2（C2）也是 SOF，尺寸一樣要讀得到。"""
    path = tmp_path / "a.jpg"
    path.write_bytes(make_jpeg(sof=0xC2))
    assert photos.read_jpeg_size(path.read_bytes()) == (4032, 3024)


def test_read_metadata_reports_everything(tmp_path: Path):
    path = tmp_path / "a.jpg"
    payload = make_jpeg(exif="2026:10:02 14:33:55")
    path.write_bytes(payload)

    metadata = photos.read_metadata(path)
    assert metadata.bytes == len(payload)
    assert (metadata.width, metadata.height) == (4032, 3024)
    assert metadata.captured_at == "2026-10-02T14:33:55"
    assert metadata.captured_from == photos.EXIF_SOURCE
    assert metadata.sha256 == photos.sha256_of(path)
    assert len(metadata.sha256) == 64


def test_sha256_is_the_real_hash(tmp_path: Path):
    import hashlib

    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert photos.sha256_of(path) == hashlib.sha256(b"abc").hexdigest()


def test_sha256_handles_large_file(tmp_path: Path):
    path = tmp_path / "big.bin"
    payload = b"x" * (3 * 1024 * 1024)
    path.write_bytes(payload)
    import hashlib

    assert photos.sha256_of(path) == hashlib.sha256(payload).hexdigest()


def test_empty_file_is_not_jpeg_but_is_hashed(tmp_path: Path):
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")
    metadata = photos.read_metadata(path)
    assert metadata.bytes == 0
    assert metadata.width is None and metadata.height is None
    assert metadata.captured_from == photos.MTIME_SOURCE


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        ("2026-10-02T14:30:22", "20261002-143022"),
        (None, None),
        ("", None),
        ("not-a-date", None),
    ],
)
def test_timestamp_for_filename(captured, expected):
    result = photos.timestamp_for_filename(captured)
    if expected is None:
        assert len(result) == 15 and result[8] == "-"
    else:
        assert result == expected
