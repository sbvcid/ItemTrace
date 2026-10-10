"""SR-2 資源上限（SECURITY-AUDIT F4）：明確、可設定、可離線測試的政策。

背景：本機應用沒有登入層，但可達來源（Loopback 上的網頁／區網裝置）能觸發
昂貴操作。失敗模式不是機密外洩，而是**資源耗盡**：把整個 body 讀進記憶體、
用小檔案展開出巨型像素矩陣、用重複的 analyze 呼叫燒 provider 費用、用超大
Template 尺寸讓列印光柵爆記憶體。

這一層的規則刻意放在一個地方，數值全部有名字、可被 config.json 覆寫
（見 shop/config.py 與 config.example.json）：

* **HTTP body 上限**（`MAX_REQUEST_BYTES`）：在路由前由 ASGI middleware
  依 Content-Length 拒絕；沒有 Content-Length 的 chunked 請求則在
  串流累計超過時拒絕 —— 兩條路都不會先把 body 讀進記憶體。
* **單檔上限**（`MAX_UPLOAD_BYTES`）：multipart 每個檔案邊讀邊累計，
  超過就 413，已存的檔案留在原處（不靜默丟掉合法證據）。
* **每請求檔數上限**（`MAX_UPLOAD_FILES`）：超過直接 400，不做任何落盤。
* **像素上限**（`MAX_IMAGE_PIXELS`）：JPEG／PNG 可由檔頭「零解碼」讀出
  寬高；超過上限在**上傳時**就 400。其他格式在 AI 縮圖時由 Pillow 的
  bomb 防護與同一個上限兜底（見 shop/ai_client.encode_photo）。
* **列印光柵上限**（`MAX_PRINT_PIXELS`）：送進瀏覽器前與量到 PDF 實際
  尺寸後各檢查一次，超過就 400 —— 不讓一個超大 Template 把
  PyMuPDF 光柵化吃爆記憶體。
* **AI 節流**（`ANALYZE_PER_MINUTE`）：analyze 與 provider 測試端點共用
  一條滑動視窗；超過回 429 並附 Retry-After。

**限制（誠實聲明）**：節流是**單一行程內**的計數器。本應用是 local-first
桌面服務，正常只有一個 uvicorn worker；若未來改用多 worker／多行程，
每個行程各有自己的視窗，實際允許量會是 N 倍 —— 屆時應改存共享狀態
（例如 SQLite）。這是刻意不引入 Redis 之類外部服務的取捨。
另外 `SlidingWindowLimiter` 的「檢查後記錄」不是嚴格原子（極端併發下
可能多放行 1 次）；它是一道資源／費用護欄，不是安全邊界。
"""

from __future__ import annotations

import math
import struct
import time
from collections import deque

from .errors import PayloadTooLargeError, ValidationError
from .photos import read_jpeg_size

#: 整個 HTTP 請求 body 的上限（32 MiB）。手機原圖一張 3~8 MB，
#: 一次 8 張也還在幾十 MB 內；32 MiB 留給 multipart 邊界與表單欄位。
MAX_REQUEST_BYTES = 32 * 1024 * 1024

#: 單一上傳檔案上限（24 MiB）。比 body 上限小，讓「一張壞檔塞爆整批」
#: 的錯誤訊息指向正確的檔案。
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

#: 一次請求最多幾個檔案。SPEC 的手機流程一次最多 8 張，20 是本機應用
#: 的合理寬鬆值。
MAX_UPLOAD_FILES = 20

#: 單張圖片的解碼像素上限（50 MP ≈ 8800x5700）。一般手機 12~48 MP，
#: 留一點餘裕；「小檔大像素」的 decompression bomb 會在這裡被擋下。
MAX_IMAGE_PIXELS = 50_000_000

#: 列印光柵化的像素上限（60 MP）。100x150mm @300dpi 只有約 2.1 MP，
#: 60 MP 足夠任何合理標籤；超過代表 Template 尺寸異常。
MAX_PRINT_PIXELS = 60_000_000

#: 每分鐘允許的 AI provider 呼叫次數（analyze＋設定頁測試共用）。
#: 0 代表停用節流（交由使用者自負風險；文件明示）。
ANALYZE_PER_MINUTE = 10

#: 節流的視窗長度（秒）。
ANALYZE_WINDOW_SECONDS = 60.0

#: 上傳檔案的 MIME 白名單概念在 SR-1 已由 /files 的附件化處理；
#: 這裡只做「像素」這一層，不重複型別政策。

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """零解碼讀出 JPEG／PNG 的寬高；其他格式或讀不到回 None。

    JPEG 走 shop.photos 既有的 SOF 解析（只讀檔頭幾百 bytes）；
    PNG 讀 IHDR（固定位置）。兩者都不進 Pillow、不展開像素。
    """
    jpeg = read_jpeg_size(data)
    if jpeg:
        return jpeg
    if (
        data.startswith(_PNG_SIGNATURE)
        and len(data) >= 24
        and data[12:16] == b"IHDR"
    ):
        width, height = struct.unpack_from(">II", data, 16)
        if width and height:
            return (width, height)
    return None


def check_image_pixels(data: bytes, name: str, *, max_pixels: int = MAX_IMAGE_PIXELS) -> None:
    """上傳時檢查像素上限；讀不出寬高的格式放行（analyze 端另有兜底）。

    Raises:
        ValidationError: 寬高乘積超過 `max_pixels`（→ 400）。
    """
    dimensions = image_dimensions(data)
    if dimensions is None:
        return
    width, height = dimensions
    if width * height > max_pixels:
        raise ValidationError(
            f"照片像素過大：{name} 是 {width}x{height}"
            f"（{width * height / 1_000_000:.1f} MP），"
            f"上限 {max_pixels / 1_000_000:.0f} MP；"
            "請縮小後再上傳（原始檔未被接受，不會動到任何已存的資料）。"
        )


def check_print_pixels(
    width_mm: float,
    height_mm: float,
    dpi: int,
    *,
    max_pixels: int = MAX_PRINT_PIXELS,
) -> None:
    """列印前檢查光柵像素上限，避免超大頁面把記憶體吃爆。

    Raises:
        ValidationError: 目標解析度下的總像素超過 `max_pixels`（→ 400）。
    """
    pixels = (width_mm / 25.4 * dpi) * (height_mm / 25.4 * dpi)
    if pixels > max_pixels:
        raise ValidationError(
            f"列印尺寸過大：{width_mm:.1f} x {height_mm:.1f} mm @ {dpi} dpi "
            f"需要 {pixels / 1_000_000:.0f} MP 的光柵，"
            f"上限 {max_pixels / 1_000_000:.0f} MP。請調整 Template 尺寸。"
        )


class SlidingWindowLimiter:
    """單一行程內的滑動視窗限流器（見本模組 docstring 的限制聲明）。

    測試可注入 `clock` 取得決定性行為，不需要真的等待。
    `limit <= 0` 代表停用節流。
    """

    def __init__(self, limit: int, window_seconds: float, clock=None) -> None:
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self._clock = clock or time.monotonic
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_seconds:
            self._events.popleft()

    def consume(self) -> bool:
        """嘗試取得一次額度：允許回 True，超限回 False（不記錄）。"""
        if self.limit <= 0:
            return True
        now = self._clock()
        self._prune(now)
        if len(self._events) >= self.limit:
            return False
        self._events.append(now)
        return True

    def retry_after(self) -> int:
        """距離下一次額度釋放還需幾秒（給 Retry-After 標頭用）。"""
        if self.limit <= 0:
            return 0
        now = self._clock()
        self._prune(now)
        if len(self._events) < self.limit:
            return 0
        return max(1, math.ceil(self._events[0] + self.window_seconds - now))


async def read_upload_limited(upload, max_bytes: int):
    """把 UploadFile 讀進記憶體，但超過上限就中止（413）。

    逐塊讀取，因此即使某個檔案超出上限，也不會先把整檔展開；
    丟出的例外由 API 層翻成 413。先前已處理的檔案不受影響。
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(
                f"檔案超過單檔上限 {max_bytes // (1024 * 1024)} MB："
                f"{upload.filename or '（未命名）'!r}（已停止讀取，"
                "先前完成的檔案保持不變）"
            )
        chunks.append(chunk)
    return b"".join(chunks)
