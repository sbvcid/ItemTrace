"""列印後端：把「已經 render 完成的預覽 HTML」送進 Windows 印表機。

為什麼是這個順序（而不是 window.print()）
----------------------------------------
`window.print()` 只能印整個 document，會把商品資訊、按鈕、Template 選擇區
一起印出來。本模組改走：

    預覽 HTML
      → headless Chromium --print-to-pdf（真正的瀏覽器排版引擎）
      → 校正成精確 mm 的 PDF 頁面框
      → 光柵化（PyMuPDF）
      → GDI StretchDIBits 送進印表機 DC

關鍵設計
--------
1. **不重複實作資料填充**：呼叫端傳進來的 HTML 必須是
   `template_renderer.render_template_preview()` 的輸出。本模組只做
   「排版 → 列印」，完全不碰 data-bind，所以預覽與實印共用同一條
   template render pipeline。

2. **精確尺寸**。這裡有兩個容易出錯的地方，都必須處理：
   - Chromium 的 `@page size` 會被四捨五入到整數 CSS px，
     100mm 會變成 99.82mm。所以 PDF 產生後要把頁面框重新寫成精確的
     mm 值（`_normalize_page_size`），再把原始頁面貼進去。
   - 印表機驅動程式的 `HORZRES`/`VERTRES` 回報的是「驅動程式自以為的
     媒體大小」，標籤機常常夾成它自己的紙寬（實測 Xprinter XP-470E 回
     108mm，不是我們要的 100mm）。所以送出時的目標矩形必須由
     **LOGPIXELS + 請求的 mm** 算出來，而不是用 HORZRES/VERTRES。

   這樣「縮放」永遠是 1:1 的 mm→device unit 轉換，輸出物理尺寸就是
   Template 定義的尺寸。

3. **後端與 UI 解耦**：UI 只呼叫「列印這個 template + item」，
   實際送印表機是這裡的事。`print_html()` 回傳 `PrintResult`，
   不直接操作瀏覽器。

4. **依賴都是選用的**。pywin32 / PyMuPDF / Chromium 缺任何一個，
   都會丟出清楚的 `PrintUnavailableError`（→ 400），而不是讓 server 崩掉。
   這跟 shop/ai_client.py 對 Pillow 的處理同一個慣例。
"""

from __future__ import annotations

import base64
import ctypes
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ValidationError

#: 1 inch = 25.4 mm。列印全程用這組常數換算，不用任何近似值。
MM_PER_INCH = 25.4

#: 預設點陣化解析度。標籤機常見 203/300 dpi；300 是兩者的公倍數，
#: 在 203 dpi 機器上也不會產生破圖。
DEFAULT_DPI = 300

#: Windows 上依序尋找的 Chromium 瀏覽器。Edge 是 Windows 內建的，
#: 所以幾乎所有 Windows 機器都至少有 Edge。
BROWSER_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

#: 伺服器端產生給瀏覽器看的暫存 HTML 檔名前綴。這些檔案在列印前已經
#: render 完成，列印時不再重新填充資料。
TEMP_PREFIX = "itemtrace-print-"

#: `/files/` 是 shop.api 掛載點的前綴；renderer 產生的照片 URL 都是
#: `/files/{DATA_ROOT 相對路徑}`（見 TemplateViewModel.from_item）。
FILES_MOUNT = "/files/"

#: 只重寫這個屬性。renderer 唯一產生的 `/files/...` URL 就是 `src`。
_SRC_PATTERN = re.compile(r'src="(?P<quote>)(?P<value>/files/[^"]*)(?P=quote)')

#: 列印文件預設名稱前綴（會出現在 Windows 列印佇列裡）。
JOB_TITLE = "ItemTrace"


class PrintUnavailableError(ValidationError):
    """列印後端缺少必要依賴或環境不支援。

    繼承 ValidationError，所以 API 層會翻成 400（用者可處理的問題），
    而不是 500 —— 使用者看到的是「缺少印表機」而不是伺服器錯誤。
    """


class PrintFailedError(ValidationError):
    """列印流程執行失敗（瀏覽器不支援、印表機拒絕工作等）。"""


@dataclass(frozen=True)
class PrintResult:
    """一次列印的結果。給 UI 顯示用，也是測試斷言的依據。"""

    printer: str
    item_id: str
    template_id: str
    #: 實際輸出的物理尺寸（mm）。這是送進印表機的目標矩形換算回來的
    #: 值，不是「請求」值 —— 用來證明尺寸真的沒被縮放。
    width_mm: float
    height_mm: float
    #: 光柵化後送進 GDI 的點陣尺寸（像素）。
    pixel_width: int
    pixel_height: int
    #: 送進 GDI 的目標矩形（device units）。
    device_width: int
    device_height: int
    dpi: int
    #: PDF 頁面框的物理尺寸（mm），用於驗證 PDF 本身沒被縮放。
    pdf_width_mm: float
    pdf_height_mm: float


# ----------------------------------------------------------------------
# 尺寸換算
# ----------------------------------------------------------------------

#: 支援的 Template 尺寸單位 → 轉成 mm 的倍率。
UNIT_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "in": MM_PER_INCH,
}

#: mm → PostScript point（PDF 的 1/72 inch）。用 mm 直接算，避免來回
#: 換算累積誤差。
PT_PER_INCH = 72.0


def mm_to_pt(mm: float) -> float:
    """mm → PDF point。"""
    return mm / MM_PER_INCH * PT_PER_INCH


def pt_to_mm(pt: float) -> float:
    """PDF point → mm。"""
    return pt / PT_PER_INCH * MM_PER_INCH


def normalize_unit(unit: str | None) -> str:
    """把 Template 的 unit 正規化。

    repo._validate_template 只檢查 width/height > 0，unit 是自由文字
    （見 schema.sql 的 templates.unit 沒有 CHECK 約束），所以這裡
    做正規化並對未知單位給明確錯誤，而不是默默當 mm 處理。
    """
    if unit is None:
        return "mm"
    key = unit.strip().lower()
    if key not in UNIT_TO_MM:
        raise PrintUnavailableError(
            f"不支援的尺寸單位：{unit}（可用：{'、'.join(UNIT_TO_MM)}）"
        )
    return key


def resolve_page_mm(
    width: float | None,
    height: float | None,
    unit: str | None,
) -> tuple[float, float] | None:
    """把 Template 的寬高單位換算成 mm。

    回傳 None 代表 Template 沒有宣告尺寸 —— 呼叫端應該改用 Template
    自己 CSS 裡的 `@page size`，而不是猜一個尺寸。
    """
    if width is None or height is None:
        return None
    scale = UNIT_TO_MM[normalize_unit(unit)]
    return (float(width) * scale, float(height) * scale)


def mm_to_device(mm: float, dpi: int) -> int:
    """mm → 印表機 device units。

    這是「不縮放」的關鍵：目標矩形用請求的 mm 與 LOGPIXELS 算出，
    **不使用**驅動程式的 HORZRES/VERTRES。標籤機的 HORZRES 是紙寬，
    常常不是我們要的尺寸。
    """
    return round(mm / MM_PER_INCH * dpi)


def device_to_mm(device: int, dpi: int) -> float:
    """印表機 device units → mm（用來回報實際輸出尺寸）。"""
    return device / dpi * MM_PER_INCH


# ----------------------------------------------------------------------
# Chromium → PDF
# ----------------------------------------------------------------------


def find_browser() -> str:
    """找出可用的 Chromium 瀏覽器。

    為什麼需要瀏覽器：Template 是任意 HTML+CSS（flex、object-fit、
    print-color-adjust…）。要在伺服器端重現「預覽看到什麼」，
    就必須用跟預覽同一套排版引擎，也就是瀏覽器本身。手寫 HTML→PDF
    只會造成預覽與實印不一致 —— 那是這個功能最不能接受的失敗模式。
    """
    override = os.environ.get("ITEMTRACE_BROWSER")
    if override:
        if Path(override).is_file():
            return override
        raise PrintUnavailableError(
            f"ITEMTRACE_BROWSER 指向的瀏覽器不存在：{override}"
        )
    for candidate in BROWSER_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return found
    raise PrintUnavailableError(
        "找不到 Chromium 瀏覽器（Chrome 或 Edge）來排版列印內容。"
        "請安裝 Edge/Chrome，或設定 ITEMTRACE_BROWSER 指向瀏覽器路徑。"
    )


def _require_pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - 取決於環境
        raise PrintUnavailableError(
            "缺少 PyMuPDF（pip install pymupdf），無法產生列印 PDF。"
        ) from exc
    return pymupdf


def _require_win32() -> Any:
    try:
        import win32print
    except ImportError as exc:  # pragma: no cover - 取決於環境
        raise PrintUnavailableError(
            "缺少 pywin32（pip install pywin32），無法送出列印工作。"
        ) from exc
    return win32print


def inline_photos(html: str, reader: Callable[[str], bytes | None]) -> str:
    """把渲染結果裡的照片 URL 換成 inline data URI。

    為什麼必須做：renderer 產生的照片 `src` 是 `/files/...`，那是
    shop.api 的掛載路徑。預覽時瀏覽器在同一個 origin，所以抓得到；
    但列印時我們把 HTML 寫成暫存檔給 headless Chromium 開
    `file://.../preview.html`，`/files/...` 會被解析成
    `file:///files/...` 而找不到檔案 —— 照片在實印上直接消失。

    把 bytes 直接內嵌成 data URI 之後，列印完全不需要 HTTP server，
    也就不會出現「預覽有照片、實印沒照片」。讀取走 caller 提供的
    `reader`（API 層用與 /files 相同的 containment 規則），這裡不
    自己碰檔案系統。

    只有 `/files/` 開頭的 src 會被替換。Template 是不可信輸入，
    validator 已經擋掉外部 URL，所以這個前綴只會是本站照片。
    """
    if FILES_MOUNT not in html:
        return html

    def replace(match: "re.Match[str]") -> str:
        relative = match.group("value")[len(FILES_MOUNT):]
        try:
            payload = reader(relative)
        except Exception:
            # 讀不到照片時維持原樣 —— 與預覽的行為一致（img 抓不到
            # 就是空白），不因為列印而丟出錯誤。
            return match.group(0)
        if payload is None:
            return match.group(0)
        mime = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        encoded = base64.b64encode(payload).decode("ascii")
        return f'src="data:{mime};base64,{encoded}"'

    return _SRC_PATTERN.sub(replace, html)


def build_page_style(width_mm: float, height_mm: float) -> str:
    """產生強制頁面尺寸的列印 CSS。

    這段會覆蓋 Template 自己可能寫錯的 `@page`。Template 是不可信
    輸入，讓它自己決定紙張大小的話，一個沒寫 `@page` 的 Template 就會
    被印成 A4 —— 尺寸必須由 Template 的 width/height 欄位決定。
    """
    return (
        "<style id=\"itemtrace-print-page\">"
        "@page { size: "
        f"{width_mm:g}mm {height_mm:g}mm; margin: 0; "
        "}"
        "</style>"
    )


def inject_print_style(html: str, width_mm: float, height_mm: float) -> str:
    """把強制頁面尺寸的 CSS 插進渲染後的 HTML。

    插在 `</head>` 前；若 Template 沒有 `<head>`（HTML 容錯解析會自己
    補），就插在 `<body>` 開頭前。找不到任何插入點時附加在最後 ——
    樣式表放在文件結尾對 `@page` 依然有效。
    """
    style = build_page_style(width_mm, height_mm)
    for marker in ("</head>", "<body"):
        index = html.lower().find(marker)
        if index != -1:
            return html[:index] + style + html[index:]
    return html + style


def html_to_pdf(html: str, page_mm: tuple[float, float] | None) -> bytes:
    """把預覽 HTML 轉成單頁 PDF。

    Args:
        html: render_template_preview 的輸出
        page_mm: 目標物理尺寸；None 代表沿用 Template 自己的 `@page`

    Returns:
        PDF bytes

    流程刻意分兩段：Chromium 負責排版（保證與預覽同一套引擎），
    之後再用 `_normalize_page_size` 把頁面框校正到精確 mm。
    """
    pymupdf = _require_pymupdf()
    browser = find_browser()
    width_mm, height_mm = page_mm if page_mm else (0.0, 0.0)

    with tempfile.TemporaryDirectory(prefix="itemtrace-print-") as workdir:
        work = Path(workdir)
        html_path = work / "preview.html"
        pdf_path = work / "raw.pdf"
        html_path.write_text(
            inject_print_style(html, width_mm, height_mm) if page_mm else html,
            encoding="utf-8",
        )

        command = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrintFailedError("瀏覽器排版逾時（60 秒）。") from exc
        except OSError as exc:
            raise PrintUnavailableError(f"無法啟動瀏覽器：{exc}") from exc

        if not pdf_path.is_file():
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise PrintFailedError(
                f"瀏覽器沒有產生 PDF。{detail[:400]}"
            )

        raw = pymupdf.open(pdf_path)
        with raw:
            pdf_bytes = _normalize_page_size(pymupdf, raw, page_mm)

    if not pdf_bytes.startswith(b"%PDF"):
        raise PrintFailedError("產生的檔案不是有效的 PDF。")
    return pdf_bytes


def _normalize_page_size(
    pymupdf: Any,
    source: Any,
    page_mm: tuple[float, float] | None,
) -> bytes:
    """把 PDF 頁面框校正成精確的 mm。

    Chromium 把 `@page size` 轉成整數 CSS px（1px = 1/96 inch），
    所以 `100mm` 會得到 99.822mm —— 每邊差 0.18mm。對標籤來說這已經
    是肉眼可見的偏移，而且會讓「輸出 = 100 x 150mm」這個條件失敗。

    做法：新建一個頁面框為精確 mm 的頁面，用 `show_pdf_page` 把原始
    頁面縮放貼滿。`show_pdf_page` 預設會等比縮放到目標矩形，而我們的
    目標矩形跟原始比例只差 0.18%，所以內容幾乎沒有變形，但頁面框是
    精確值。

    頁數 > 1 時只取第一頁：列印預覽的語意就是「一張」。
    """
    if not source.page_count:
        raise PrintFailedError("渲染結果沒有任何頁面。")

    if page_mm is None:
        # 沒有宣告尺寸就原樣輸出，不做任何縮放。
        output = pymupdf.open()
        output.insert_pdf(source, from_page=0, to_page=0)
        with output:
            return output.tobytes()

    target = pymupdf.Rect(
        0.0, 0.0, mm_to_pt(page_mm[0]), mm_to_pt(page_mm[1])
    )
    output = pymupdf.open()
    page = output.new_page(width=target.width, height=target.height)
    page.show_pdf_page(target, source, 0)
    with output:
        return output.tobytes()


def measure_pdf_mm(pdf_bytes: bytes) -> tuple[float, float]:
    """讀出 PDF 第一頁的物理尺寸（mm）。測試與列印結果回報都用它。"""
    pymupdf = _require_pymupdf()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        rect = document[0].rect
        return (pt_to_mm(rect.width), pt_to_mm(rect.height))


def rasterize(pdf_bytes: bytes, dpi: int = DEFAULT_DPI) -> Any:
    """把 PDF 光柵化成 RGB 點陣。

    用 PyMuPDF（MuPDF）而不是瀏覽器截圖，是因為列印必須在**離線**、
    與畫面無關的環境下產生：沒有視窗、沒有捲動、沒有 devicePixelRatio。
    """
    pymupdf = _require_pymupdf()
    zoom = dpi / PT_PER_INCH
    matrix = pymupdf.Matrix(zoom, zoom)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return document[0].get_pixmap(
            matrix=matrix, colorspace=pymupdf.csRGB, alpha=False
        )


# ----------------------------------------------------------------------
# 列印佇列 / GDI
# ----------------------------------------------------------------------


def list_printers() -> list[str]:
    """列出可用印表機名稱。給 UI 選單與錯誤訊息用。"""
    win32print = _require_win32()
    names: list[str] = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for entry in win32print.EnumPrinters(flags):
        names.append(entry[2])
    return sorted(set(names))


def default_printer() -> str | None:
    """Windows 預設印表機；沒有設定則回 None。"""
    win32print = _require_win32()
    try:
        return win32print.GetDefaultPrinter()
    except Exception:  # pragma: no cover - 取決於環境有沒有預設印表機
        return None


def resolve_printer(name: str | None) -> str:
    """決定要送到哪一台印表機。

    沒指定就用 Windows 預設印表機。兩者都沒有就報錯 —— 靜默挑一台
    會印到不該印的地方。
    """
    available = list_printers()
    if name:
        if name not in available:
            raise PrintUnavailableError(
                f"找不到印表機：{name}（可用：{'、'.join(available) or '無'}）"
            )
        return name
    fallback = default_printer()
    if not fallback:
        raise PrintUnavailableError(
            "沒有指定印表機，而且 Windows 也沒有設定預設印表機。"
        )
    if fallback not in available:
        raise PrintUnavailableError(f"預設印表機不可用：{fallback}")
    return fallback


class _DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("lpszDocName", ctypes.c_wchar_p),
        ("lpszOutput", ctypes.c_wchar_p),
        ("lpszDatatype", ctypes.c_wchar_p),
        ("fType", ctypes.c_ushort),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _gdi() -> Any:
    return ctypes.WinDLL("gdi32", use_last_error=True)


def _kernel32() -> Any:
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetLastError.restype = ctypes.c_uint32
    return library


def _pack_bitmap(pixmap: Any) -> ctypes.Array:
    """把 PyMuPDF 的點陣轉成 GDI 需要的 24bpp BGR、每列 4-byte 對齊。

    三個細節都不能省：
    - PyMuPDF 給的是 **RGB**；GDI 的 BI_RGB 24bpp 要 **BGR**（不換的話
      紅藍會對調）。
    - 每列必須補齊到 4-byte 邊界，否則 GDI 讀到錯位資料，實測會讓
      StretchDIBits 回傳 0 scanlines。
    - 以負的 biHeight 表示由上而下，就不需要把資料上下翻轉。
    """
    width, height, samples = pixmap.width, pixmap.height, pixmap.samples
    row_bytes = width * 3
    stride = (row_bytes + 3) & ~3
    buffer = (ctypes.c_ubyte * (stride * height))()
    for y in range(height):
        start = y * row_bytes
        original = samples[start:start + row_bytes]
        row = bytearray(row_bytes)
        row[0::3] = original[2::3]  # B
        row[1::3] = original[1::3]  # G
        row[2::3] = original[0::3]  # R
        buffer[y * stride:y * stride + row_bytes] = row
    return buffer


def _send_to_printer(
    printer: str,
    pixmap: Any,
    width_mm: float,
    height_mm: float,
    dpi: int,
) -> tuple[int, int]:
    """把點陣送到印表機，回傳實際使用的目標矩形（device units）。

    這裡是整個功能最關鍵的一段。兩個容易錯的地方：

    1. **不能用 HORZRES/VERTRES 當目標矩形。** 那個值是驅動程式自以為
       的媒體大小，標籤機會夾成自己的紙寬。實測 Xprinter XP-470E 回報
       108mm x 1016mm（連續紙捲），跟請求的 100mm x 150mm 完全無關。
    2. **要用 DM_PAPERSIZE = DMPAPER_USER 搭配 DM_PAPERWIDTH/
       DM_PAPERLENGTH**（單位是 0.1 mm）要求自訂紙張。DEVMODE 的
       Width/Length 欄位是 signed short，所以上限 3276.7 mm 足夠。

    送出時以 `mm_to_device()` 從 mm 與 LOGPIXELS 算出矩形。圖片本身是
    以 requests DPI 光柵化的，所以落到這個矩形時是 1:1，沒有縮放。
    """
    import win32con
    import win32gui

    win32print = _require_win32()
    gdi32, kernel32 = _gdi(), _kernel32()

    gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.StartDocW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.StartDocW.restype = ctypes.c_long
    gdi32.StartPage.argtypes = [ctypes.c_void_p]
    gdi32.StartPage.restype = ctypes.c_long
    gdi32.EndPage.argtypes = [ctypes.c_void_p]
    gdi32.EndPage.restype = ctypes.c_long
    gdi32.EndDoc.argtypes = [ctypes.c_void_p]
    gdi32.EndDoc.restype = ctypes.c_long
    gdi32.StretchDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_ulong,
    ]
    gdi32.StretchDIBits.restype = ctypes.c_int
    gdi32.PatBlt.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_ulong,
    ]
    gdi32.PatBlt.restype = ctypes.c_int
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.restype = ctypes.c_int

    handle = win32print.OpenPrinter(printer)
    try:
        devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
        devmode.PaperSize = 256  # DMPAPER_USER
        devmode.PaperWidth = round(width_mm * 10)
        devmode.PaperLength = round(height_mm * 10)
        devmode.Orientation = 1  # DMPORTRAIT
        devmode.Copies = 1
        devmode.Fields = (
            0x1  # DM_ORIENTATION
            | 0x2  # DM_PAPERSIZE
            | 0x4  # DM_PAPERLENGTH
            | 0x8  # DM_PAPERWIDTH
            | 0x100  # DM_COPIES
        )
        hdc = win32gui.CreateDC("WINSPOOL", printer, devmode)
        if not hdc:
            raise PrintFailedError(
                f"無法開啟印表機 {printer} 的裝置內容（錯誤 "
                f"{kernel32.GetLastError()}）。驅動程式可能不支援 "
                f"{width_mm:g} x {height_mm:g} mm 的自訂紙張。"
            )
        device = ctypes.c_void_p(hdc)
        try:
            logdpi_x = gdi32.GetDeviceCaps(device, 88)  # LOGPIXELSX
            if logdpi_x <= 0:
                raise PrintFailedError("印表機回報無效的 DPI。")

            dest_width = mm_to_device(width_mm, logdpi_x)
            dest_height = mm_to_device(height_mm, logdpi_x)
            if dest_width <= 0 or dest_height <= 0:
                raise PrintFailedError(
                    f"目標尺寸無效：{width_mm} x {height_mm} mm"
                )

            header = _BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            header.biWidth = pixmap.width
            header.biHeight = -pixmap.height  # 負值 = 由上而下，不需翻轉
            header.biPlanes = 1
            header.biBitCount = 24
            header.biCompression = 0  # BI_RGB

            pixels = _pack_bitmap(pixmap)
            bitmap_info = ctypes.cast(ctypes.byref(header), ctypes.c_void_p)
            bits = ctypes.cast(pixels, ctypes.c_void_p)

            docinfo = _DOCINFOW()
            docinfo.cbSize = ctypes.sizeof(_DOCINFOW)
            docinfo.lpszDocName = JOB_TITLE

            started = gdi32.StartDocW(device, ctypes.byref(docinfo))
            if started <= 0:
                raise PrintFailedError(
                    f"印表機 {printer} 拒絕開始列印工作（錯誤 "
                    f"{kernel32.GetLastError()}）。"
                )
            try:
                if gdi32.StartPage(device) <= 0:
                    raise PrintFailedError("無法開始列印頁面。")
                # 先塗白：標籤機的邊界有時不會把整張紙送出來，
                # 沒塗白會印出上一張的殘留或驅動程式的黑邊。
                gdi32.PatBlt(
                    device, 0, 0, dest_width, dest_height, win32con.WHITENESS
                )
                scanlines = gdi32.StretchDIBits(
                    device,
                    0, 0, dest_width, dest_height,
                    0, 0, pixmap.width, pixmap.height,
                    bits, bitmap_info,
                    0,  # DIB_RGB_COLORS
                    win32con.SRCCOPY,
                )
                if scanlines != pixmap.height:
                    raise PrintFailedError(
                        f"寫入印表機失敗：只送出 {scanlines}/"
                        f"{pixmap.height} 列（錯誤 "
                        f"{kernel32.GetLastError()}）。"
                    )
                if gdi32.EndPage(device) <= 0:
                    raise PrintFailedError("列印頁面結束失敗。")
            except Exception:
                gdi32.AbortDoc.argtypes = [ctypes.c_void_p]
                gdi32.AbortDoc.restype = ctypes.c_long
                gdi32.AbortDoc(device)
                raise
            if gdi32.EndDoc(device) <= 0:
                raise PrintFailedError("列印工作結束失敗。")
            return dest_width, dest_height
        finally:
            gdi32.DeleteDC(device)
    finally:
        win32print.ClosePrinter(handle)


# ----------------------------------------------------------------------
# 對外主流程
# ----------------------------------------------------------------------


def print_html(
    html: str,
    *,
    template_id: str,
    item_id: str,
    width_mm: float | None,
    height_mm: float | None,
    unit: str | None = None,
    printer: str | None = None,
    dpi: int = DEFAULT_DPI,
    photo_reader: Callable[[str], bytes | None] | None = None,
) -> PrintResult:
    """把預覽 HTML 送到印表機。預設列印 1 份。

    Args:
        html: **必須**是 `render_template_preview()` 的輸出。本函式
            不做 data-bind 處理 —— 預覽與列印因此共用同一條 render
            pipeline，不存在第二套資料填充邏輯。
        width_mm / height_mm / unit: Template 宣告的尺寸（原始值）。
            為 None 時沿用 Template 自己 CSS 的 `@page size`。
        printer: 印表機名稱；None 代表 Windows 預設印表機。
        dpi: 光柵化解析度。
        photo_reader: 讀取 DATA_ROOT 相對路徑照片 bytes 的 callable。
            提供時照片會 inline 成 data URI（見 `inline_photos`）。
    """
    if photo_reader is not None:
        html = inline_photos(html, photo_reader)
    page_mm = resolve_page_mm(width_mm, height_mm, unit)
    pdf_bytes = html_to_pdf(html, page_mm)
    pdf_width_mm, pdf_height_mm = measure_pdf_mm(pdf_bytes)

    target = page_mm if page_mm else (pdf_width_mm, pdf_height_mm)
    pixmap = rasterize(pdf_bytes, dpi)
    printer_name = resolve_printer(printer)
    dest_width, dest_height = _send_to_printer(
        printer_name, pixmap, target[0], target[1], dpi
    )

    return PrintResult(
        printer=printer_name,
        item_id=item_id,
        template_id=template_id,
        width_mm=round(device_to_mm(dest_width, dpi), 3),
        height_mm=round(device_to_mm(dest_height, dpi), 3),
        pixel_width=pixmap.width,
        pixel_height=pixmap.height,
        device_width=dest_width,
        device_height=dest_height,
        dpi=dpi,
        pdf_width_mm=round(pdf_width_mm, 3),
        pdf_height_mm=round(pdf_height_mm, 3),
    )


def build_pdf(
    html: str,
    *,
    width_mm: float | None,
    height_mm: float | None,
    unit: str | None = None,
    photo_reader: Callable[[str], bytes | None] | None = None,
) -> tuple[bytes, float, float]:
    """只產生 PDF、不送印表機。回傳 (bytes, 寬mm, 高mm)。

    給測試與「先預覽列印輸出」使用；正式列印走 `print_html`。
    """
    if photo_reader is not None:
        html = inline_photos(html, photo_reader)
    page_mm = resolve_page_mm(width_mm, height_mm, unit)
    pdf_bytes = html_to_pdf(html, page_mm)
    pdf_width_mm, pdf_height_mm = measure_pdf_mm(pdf_bytes)
    return pdf_bytes, pdf_width_mm, pdf_height_mm