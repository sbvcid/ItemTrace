"""手機配對的核心規則：短效工作階段、裝置權杖、區網位址與本機 QR 產生。

**為什麼不用手機端瀏覽器密碼學（Web Crypto）**

最初設計想讓手機用 `crypto.subtle` 生成金鑰對、簽名 challenge。查證後
不可行：`crypto.subtle` 只在 **secure context**（HTTPS 或 localhost）存在，
而本機區網服務是 `http://192.168.x.x:8731`，不是 secure context ——
Android Chrome、iOS Safari 在這種網址上 `window.crypto.subtle` 是
`undefined`，配對會在手機端直接失敗。要求使用者替內網架 HTTPS 憑證
並不合理（自簽憑證還有另外的警告流程）。

可行且實際被 LAN 產品採用的做法（本模組實作）：

1. 電腦端建立 **短效、一次性** 的配對工作階段（6 位數字碼 + 工作階段 ID）。
2. QR Code 內容是手機瀏覽器可直接開啟的 URL：``/pair?id=...&code=...``。
3. 手機開啟後由 ItemTrace 自己的前端把 `id` + `code` POST 回 ``/api/pairing/claim``。
4. 伺服器驗證（存在、未過期、未使用、嘗試次數內、碼正確）後，發給手機一組
   高熵裝置權杖；伺服器只存 **SHA-256 雜湊**，原文只在配對回應出現一次。
5. 手機把權杖存進 localStorage（`fetch` 自動帶 `Authorization: Bearer`），
   同時伺服器對「手機瀏覽器」下一個 HttpOnly cookie —— 讓 ``<img src="/files/...">``
   這類**不經過 fetch、不會帶標頭**的請求也能通過裝置認證。

傳輸安全模型：工作階段碼本身不是長期秘密（5 分鐘、一次性、有限嘗試），
真正的憑證是配對後才發出的裝置權杖；兩者都不寫入日誌、不出現在公開回應中
（裝置清單只有名稱與時間）。

QR Code 一律用本機依賴 segno 在伺服器端產生（純 Python、無網路），
不把配對碼或 URL 送往任何第三方 QR 服務。
"""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket

#: 配對工作階段有效秒數（過期即失效，需重新產生 QR Code）。
PAIRING_TTL_SECONDS = 300

#: 同一個工作階段允許的錯誤嘗試次數；超過後連正確的碼也不再受理。
PAIRING_MAX_ATTEMPTS = 5

#: 配對碼位數（僅用於一次性工作階段，不是長期憑證）。
PAIRING_CODE_DIGITS = 6

#: 裝置權杖的 cookie 名稱（HttpOnly；讓媒體 <img> 請求也能通過認證）。
COOKIE_NAME = "itemtrace_device"

#: 裝置 cookie 保存期限（180 天；手機重開瀏覽器仍可續用，撤銷即失效）。
COOKIE_MAX_AGE_SECONDS = 180 * 24 * 3600


def generate_pairing_code() -> str:
    """6 位數字配對碼。"""
    limit = 10 ** PAIRING_CODE_DIGITS
    return f"{secrets.randbelow(limit):0{PAIRING_CODE_DIGITS}d}"


def generate_device_token() -> str:
    """高熵裝置權杖（32 bytes → 43 字元 URL-safe）。"""
    return secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    """裝置權杖入庫前一律雜湊；資料庫只存雜湊值。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def local_ipv4_addresses() -> list[str]:
    """本機可對外連線的 IPv4 位址清單（私有位址優先）。

    作法：
    1. UDP「連線」到保留位址（不會實際送包）取得預設路由的來源 IP。
    2. 以 socket.gethostbyname_ex 補齊其他介面位址（多網卡／VPN 情境）。

    永遠不會回傳 loopback、link-local 或未指定位址；完全找不到時回空清單，
    呼叫端必須自行處理（例如提示使用者電腦目前沒有區網連線）。
    """
    found: list[str] = []

    def _add(candidate: str) -> None:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return
        if (
            address.version == 4
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_unspecified
            and candidate not in found
        ):
            found.append(candidate)

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            _add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        addresses = []
    for candidate in addresses:
        _add(candidate)

    # 私有位址（192.168/10/172.16-31）優先，符合家用 Wi-Fi 的常見情境。
    found.sort(key=lambda ip: not ipaddress.ip_address(ip).is_private)
    return found


def build_pairing_url(host: str, port: int, session_id: str, code: str) -> str:
    """QR Code 內含的配對網址：手機瀏覽器可直接開啟。"""
    return f"http://{host}:{port}/pair?id={session_id}&code={code}"


def render_qr_svg(data: str) -> bytes:
    """把配對網址渲染成 SVG（本機產生，不連外）。

    segno 是純 Python 實作，不依賴 Pillow；SVG 由瀏覽器直接顯示。
    """
    import segno

    return segno.make(data, error="m").svg_inline().encode("utf-8")
