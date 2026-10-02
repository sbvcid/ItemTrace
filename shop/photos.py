"""照片檔案的 metadata 讀取：EXIF、影像尺寸、SHA-256、時間退路。

只用標準函式庫。專案從頭到尾都不要求 pip install（SPEC-v1 §9），
所以 JPEG 的 APP1/Exif 與 SOF 標記在這裡自己解析。

解析失敗一律不丟例外，只回傳 None —— 手機上傳常丟 EXIF，不能因此中斷
整條入庫流程（SPEC-v1 §14.4）。時間退路依序為：

    EXIF DateTimeOriginal → DateTimeDigitized → IFD0 DateTime
    → 檔案 mtime → 檔名開頭的時間戳 → 留空

所有時間一律轉成 ISO8601 秒精度（與 db.now() 同格式），因為
photos.captured_at 與 observations.captured_at 都是 ISO8601。
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 只讀檔案開頭這麼多 bytes 就足以涵蓋 EXIF 與 SOF（都在第一段 APP1 附近）。
HEADER_BYTES = 128 * 1024

#: SOF0..SOF15 中真正帶影像尺寸的，排除 DHT(0xC4) / JPG(0xC8) / DAC(0xCC)。
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)

#: 檔名時間戳前綴 YYYYMMDD-HHMMSS（SPEC-v1 §3 的命名格式）。
FILENAME_STAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")

_TAG_DATETIME = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004

_TYPE_ASCII = 2
_TYPE_LONG = 4
_TIFF_MAGIC = 42

EXIF_SOURCE = "exif"
MTIME_SOURCE = "mtime"
FILENAME_SOURCE = "filename"
NO_SOURCE = "none"

#: EXIF 的時間是本機時間且不帶時區（OffsetTimeOriginal 不在 v1 採用的解析範圍），
#: 與 SPEC-v1 §3 的檔名格式一致，所以保持 naive。
_EXIF_LAYOUTS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M")


@dataclass(frozen=True, slots=True)
class PhotoMetadata:
    """一個檔案的讀取結果。captured_from 記錄時間是從哪裡來的，可觀測。"""

    sha256: str
    bytes: int
    width: int | None
    height: int | None
    captured_at: str | None
    captured_from: str


def read_metadata(path: Path) -> PhotoMetadata:
    head = _read_head(path)
    captured_at, captured_from = _resolve_captured_at(path, head)
    size = read_jpeg_size(head)
    return PhotoMetadata(
        sha256=sha256_of(path),
        bytes=path.stat().st_size,
        width=size[0] if size else None,
        height=size[1] if size else None,
        captured_at=captured_at,
        captured_from=captured_from,
    )


def parse_metadata(data: bytes, name: str) -> PhotoMetadata:
    """從記憶體裡的位元組解析（HTTP 上傳用，不需要先落盤）。

    沒有 mtime 可退，所以退路是 EXIF → 檔名時間戳 → 留空。
    """
    captured = read_exif_captured_at(data)
    if captured:
        captured_at, captured_from = captured, EXIF_SOURCE
    else:
        from_name = parse_filename_timestamp(name)
        captured_at = from_name
        captured_from = FILENAME_SOURCE if from_name else NO_SOURCE
    size = read_jpeg_size(data)
    return PhotoMetadata(
        sha256=sha256_bytes(data),
        bytes=len(data),
        width=size[0] if size else None,
        height=size[1] if size else None,
        captured_at=captured_at,
        captured_from=captured_from,
    )


def read_captured_at(path: Path) -> tuple[str | None, str]:
    """只取拍攝時間，不做整檔雜湊。掃描 inbox 用這個。"""
    return _resolve_captured_at(path, _read_head(path))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def timestamp_for_filename(captured_at: str | None) -> str:
    """SPEC-v1 §3 的檔名前綴 YYYYMMDD-HHMMSS；沒有時間就用現在。"""
    if captured_at:
        try:
            return datetime.fromisoformat(captured_at).strftime("%Y%m%d-%H%M%S")
        except ValueError:
            pass
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def parse_filename_timestamp(name: str) -> str | None:
    """檔名開頭的 YYYYMMDD-HHMMSS → ISO8601。無法解析回 None。"""
    match = FILENAME_STAMP.match(name)
    if not match:
        return None
    return _to_iso(*match.groups())


def read_jpeg_size(data: bytes) -> tuple[int, int] | None:
    """回傳 (width, height)。不是 JPEG 或讀不到就 None。"""
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in _SOF_MARKERS:
            if pos + 9 > len(data):
                return None
            height, width = struct.unpack_from(">HH", data, pos + 5)
            return (width, height) if width and height else None
        if marker == 0xDA:  # SOS：之後是壓縮影像資料，不會再出現 SOF
            return None
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
            pos += 2
            continue
        (length,) = struct.unpack_from(">H", data, pos + 2)
        pos += 2 + length
    return None


def read_exif_captured_at(data: bytes) -> str | None:
    """從 JPEG 的 APP1/Exif 取出拍攝時間，轉成 ISO8601。"""
    tiff = _find_exif_tiff(data)
    if tiff is None:
        return None
    try:
        order = "<" if tiff[:2] == b"II" else ">" if tiff[:2] == b"MM" else ""
        if not order:
            return None
        if struct.unpack_from(order + "H", tiff, 2)[0] != _TIFF_MAGIC:
            return None
        (ifd0_offset,) = struct.unpack_from(order + "I", tiff, 4)
        ifd0 = _read_ifd(tiff, ifd0_offset, order)

        pointer = ifd0.get(_TAG_EXIF_IFD)
        if isinstance(pointer, int):
            exif_ifd = _read_ifd(tiff, pointer, order)
            for tag in (_TAG_DATETIME_ORIGINAL, _TAG_DATETIME_DIGITIZED):
                found = iso_from_exif(exif_ifd.get(tag))
                if found:
                    return found
        return iso_from_exif(ifd0.get(_TAG_DATETIME))
    except (struct.error, IndexError, ValueError):
        return None


def iso_from_exif(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().strip("\x00").strip()
    if not text:
        return None
    for layout in _EXIF_LAYOUTS:
        try:
            return datetime.strptime(text, layout).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def _resolve_captured_at(path: Path, head: bytes) -> tuple[str | None, str]:
    """SPEC-v1 §14.4 的退路順序：EXIF → mtime → 檔名 → 留空。"""
    captured = read_exif_captured_at(head)
    if captured:
        return captured, EXIF_SOURCE
    mtime = _mtime_iso(path)
    if mtime:
        return mtime, MTIME_SOURCE
    captured = parse_filename_timestamp(path.name)
    if captured:
        return captured, FILENAME_SOURCE
    return None, NO_SOURCE


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        # 檔案在掃描之後被移走或沒有可讀的 mtime —— 這就是「退回檔名」的時機。
        return None


def _read_head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(HEADER_BYTES)


def _find_exif_tiff(data: bytes) -> bytes | None:
    """走 JPEG 段結構，找出 APP1 裡的 Exif 標頭並回傳其後的 TIFF 區塊。"""
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    end = min(len(data), HEADER_BYTES)
    while pos + 4 <= end:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xD9 or marker == 0xDA:
            return None
        (length,) = struct.unpack_from(">H", data, pos + 2)
        segment = data[pos + 4: pos + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return segment[6:]
        pos += 2 + length
    return None


def _read_ifd(tiff: bytes, offset: int, order: str) -> dict[int, object]:
    """讀一個 IFD。ASCII tag 回字串，LONG tag 回整數（供 ExifIFD 指標用）。"""
    (count,) = struct.unpack_from(order + "H", tiff, offset)
    values: dict[int, object] = {}
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag, kind, size = struct.unpack_from(order + "HHI", tiff, pos)
        (raw,) = struct.unpack_from(order + "I", tiff, pos + 8)
        pos += 12
        if kind == _TYPE_ASCII:
            # 值超過 4 bytes 時 raw 是偏移；否則就擺在欄位本身的前幾個 byte。
            start = raw if size > 4 else pos - 12 + 8
            values[tag] = tiff[start: start + size].split(b"\x00", 1)[0].decode(
                "ascii", "replace"
            )
        elif kind == _TYPE_LONG:
            values[tag] = raw
    return values


def _to_iso(year: str, month: str, day: str, hour: str, minute: str, second: str) -> str | None:
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second)
        ).isoformat(timespec="seconds")
    except ValueError:
        return None
