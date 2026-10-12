"""HEIC／HEIF 解碼（pillow-heif 軟性依賴）。

iPhone 預設的 HEIC／HEIF 在 Chrome／Edge／Firefox 無法直接顯示，Pillow
本身也解不開；這裡集中三種用途的伺服器端解碼：

* 選取後的前端預覽（POST /api/inbox/preview）：解碼成 JPEG。
* AI 分析輸入（shop/ai_client.encode_photo）：解碼成 JPEG data URL。
* 已存紀錄的詳情／縮圖預覽（GET /api/photos/{id}/preview）：
  解碼成 JPEG 並快取在該商品的 ``derived/``（不登記 photos 資料列）。

**原始檔永遠不會被這個模組碰觸** —— 所有函式只讀傳入的位元組並回傳
衍生資料；入庫、雜湊與副檔名全部維持原檔。

pillow-heif 是軟性依賴：沒有安裝時 `available()` 回 False、解碼函式
一律回 None，呼叫端必須誠實回報失敗（HEIC 預覽 400），其餘格式的
既有流程完全不受影響。Windows 官方有 cp310～cp313 的預建 wheel，
不需要本機編譯。

尺寸判讀（`heif_dimensions`）只讀 ISO BMFF 的 metadata（ispe），
不展開像素 —— 50 MP 上限必須在解碼之前擋下（見 shop/limits.py）。
"""

from __future__ import annotations

import io

#: ftyp 的 major brand 為這些值時視為 HEIC／HEIF。
#: avif／avis 是瀏覽器可原生顯示的格式，刻意排除。
HEIF_MAJOR_BRANDS = frozenset(
    {
        b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis",
        b"hevm", b"hevs", b"mif1", b"msf1",
    }
)

#: major brand 是 mif1／msf1 這類通用值時，再看相容 brand 清單裡
#: 有沒有實際的 HEVC 系 brand，避免把其他 ISO BMFF 格式誤收。
HEIF_COMPAT_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"}
)

_EXIF_PREFIX = b"Exif\x00\x00"


def _heif_module():
    """回傳 pillow_heif 模組；沒安裝回 None（軟性依賴）。"""
    try:
        import pillow_heif  # noqa: PLC0415 — 延後載入，缺套件時不影響其他功能
    except ImportError:
        return None
    return pillow_heif


def available() -> bool:
    """這台伺服器是否具備 HEIC／HEIF 解碼能力。"""
    return _heif_module() is not None


def is_heif(data: bytes | None) -> bool:
    """依 ISO BMFF 的 ftyp box 判斷是否為 HEIC／HEIF。

    這是保守的「容器類型」判斷，不是完整格式驗證；損毀的內容會由
    後續解碼函式回 None 誠實處理。
    """
    if not data or len(data) < 16:
        return False
    if data[4:8] != b"ftyp":
        return False
    major = data[8:12].lower()
    if major in (b"avif", b"avis"):
        return False
    if major in HEIF_MAJOR_BRANDS and major not in (b"mif1", b"msf1"):
        return True
    # mif1／msf1（或未知 major）→ 檢查相容 brand 清單。
    try:
        box_size = int.from_bytes(data[0:4], "big")
    except ValueError:  # pragma: no cover — int.from_bytes 不會拋，保留防禦
        return False
    end = min(box_size, len(data)) if box_size >= 16 else len(data)
    for offset in range(16, max(16, end - 3), 4):
        if data[offset:offset + 4].lower() in HEIF_COMPAT_BRANDS:
            return True
    return False


def _open_heif(data: bytes):
    """開一個 HeifFile（只讀 metadata）；失敗回 None。呼叫端負責 close()。"""
    module = _heif_module()
    if module is None:
        return None
    try:
        return module.open_heif(io.BytesIO(data))
    except Exception:
        # 損毀、截斷、不是 HEIF……一律視為「讀不到」。
        return None


def _close(handle) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # pragma: no cover — close 失敗不該影響結果
            pass


def heif_dimensions(data: bytes) -> tuple[int, int] | None:
    """零解碼讀出 HEIF 的寬高（metadata 的 ispe）。

    讀不到（損毀／缺 pillow-heif）回 None。50 MP 上限檢查靠這個
    函式，**不得**為了拿尺寸而先展開像素。
    """
    handle = _open_heif(data)
    if handle is None:
        return None
    try:
        width, height = handle.size
        return (int(width), int(height)) if width and height else None
    except Exception:
        return None
    finally:
        _close(handle)


def read_exif_tiff(data: bytes) -> bytes | None:
    """取出 HEIF 內嵌的 EXIF，回傳 TIFF 區塊（II/MM 開頭）。

    讀不到或沒有 EXIF 回 None —— 呼叫端據此決定要不要標示 EXIF 來源。
    """
    handle = _open_heif(data)
    if handle is None:
        return None
    try:
        blob = handle.info.get("exif")
    except Exception:
        return None
    finally:
        _close(handle)
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return None
    tiff = bytes(blob)
    if tiff.startswith(_EXIF_PREFIX):
        tiff = tiff[len(_EXIF_PREFIX):]
    if tiff[:2] not in (b"II", b"MM"):
        return None
    return tiff


def decode_to_jpeg(
    data: bytes,
    *,
    max_side: int,
    quality: int,
    max_pixels: int | None = None,
) -> bytes | None:
    """把 HEIF 解碼、依 EXIF 方向校正、縮到 max_side 並轉成 JPEG。

    解不開（損毀、缺 pillow-heif、超過 max_pixels）回 None；原始
    位元組不會被修改。呼叫端應先以 `heif_dimensions` 過像素上限，
    這裡的 max_pixels 是最後一道保險。
    """
    module = _heif_module()
    if module is None:
        return None
    try:
        module.register_heif_opener()
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover — pillow-heif 本身依賴 Pillow
        return None

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if max_pixels is not None and width * height > max_pixels:
                return None
            # pillow-heif 已在解碼時套用 irot/imir；EXIF 方向標籤若還在，
            # 這裡補正（無標籤時是 no-op）。
            transposed = ImageOps.exif_transpose(image)
            if transposed is not None:
                image = transposed
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)
            return buffer.getvalue()
    except Exception:
        # 損毀檔案、解碼器錯誤：一律回 None，由呼叫端誠實回報。
        return None
