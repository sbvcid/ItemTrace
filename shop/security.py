"""安全防護：Host／Origin／CSRF 檢查與連線身分授權（三層模型）。

第一層是既有的瀏覽器攻擊防護（SECURITY-AUDIT F1/F3）：

1. **DNS rebinding**（F1）：惡意網頁把網域 rebind 到 127.0.0.1 後，瀏覽器
   送出的請求 Host 是攻擊者的網域 —— 這裡用 Host 白名單擋掉。
2. **CSRF**（F3）：跨站的「簡單請求」帶不了自訂標頭（要帶就得先過 CORS
   preflight，而本服務沒有 CORS）。變更類方法一律要求
   `X-Requested-With: ItemTrace`；瀏覽器端由 web/core/api.js 統一附加，
   非瀏覽器用戶端（curl、腳本、adapter）自行帶上即可。
3. **Origin 驗證**：請求有 Origin 時，其 host 必須在允許清單內、且 port 與
   請求的 Host 一致；`Origin: null`（file:// 等）一律拒絕。
   **缺少 Origin 不單獨構成信任** —— 非瀏覽器請求仍要通過 Host 檢查，
   變更類還要帶標頭。

第二層是**連線身分授權**（手機配對，見 shop/pairing.py）。服務預設綁定
區網，但授權分三級：

    admin    電腦本機（loopback）連線 —— 完整資料存取＋配對管理
             （產生 QR Code、列出／撤銷裝置）。
    device   已配對裝置（有效且未撤銷的裝置權杖；Authorization: Bearer
             或 HttpOnly cookie）—— 完整資料存取，不含配對管理。
    unpaired 區網上的其他連線 —— 只能載入前端殼、配對頁與完成配對所需的
             最小端點（claim／session／health）。

未配對連線**不會**因為「GET 是安全方法」「Host 檢查通過」或「帶了 CSRF
標頭」而取得任何資料存取權。`X-Requested-With` 的檢查是不變式；授權
判定看的是 socket 對端位址與裝置憑證，兩者都不是請求方可偽造的字串。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import db, pairing
from .repo import Repository

#: 瀏覽器變更類請求必須帶的自訂標頭（值固定）。
CLIENT_HEADER = "X-Requested-With"
CLIENT_HEADER_VALUE = "ItemTrace"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: SPA 的內容安全政策：零建置 ESM 只需要自身來源；縮圖用 blob:/data:。
APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


def host_name(header_value: str) -> str:
    """從 Host 標頭取出主機名（去掉埠、去括號、小寫）。"""
    value = (header_value or "").strip().lower()
    if not value:
        return ""
    if value.startswith("["):  # [::1]:8731
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") > 1:  # 裸 IPv6（無埠）
        return value
    return value.split(":", 1)[0]


def host_port(header_value: str) -> int:
    """從 Host 標頭取出埠；沒有埠時回 HTTP 預設 80。"""
    value = (header_value or "").strip()
    if value.startswith("["):
        end = value.find("]")
        rest = value[end + 1:] if end != -1 else ""
        if rest.startswith(":") and rest[1:].isdigit():
            return int(rest[1:])
        return 80
    if value.count(":") == 1:
        _, _, port = value.partition(":")
        if port.isdigit():
            return int(port)
    return 80


def is_loopback_bind_host(host: str) -> bool:
    """綁定位址是否為 loopback（serve.py 用來判斷手機是否連得到）。"""
    value = (host or "").strip()
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def build_allowed_hosts(cfg) -> frozenset[str]:
    """建立 Host 白名單。

    - 一律允許：`localhost`、`127.0.0.1`、`::1`。
    - `server_host` 是具體位址時允許該位址。
    - `server_host` 是 0.0.0.0／:: 時（預設值；手機配對需要），以本機介面
      位址、主機名與 shop.pairing 偵測到的區網位址盡力補齊；打不到的
      別名用 config 的 `allowed_hosts` 補。
    - `allowed_hosts` 設定的項目一律併入。
    """
    hosts = {"localhost", "127.0.0.1", "::1"}
    host = (cfg.server_host or "").strip().lower()
    if host in ("0.0.0.0", "::", ""):
        try:
            name, _, ips = socket.gethostbyname_ex(socket.gethostname())
            if name:
                hosts.add(name.lower())
            hosts.update(ip.strip().lower() for ip in ips if ip.strip())
        except OSError:
            pass
        # 手機掃 QR Code 時連的是偵測到的區網 IP，必須在白名單內。
        hosts.update(ip.lower() for ip in pairing.local_ipv4_addresses())
    else:
        hosts.add(host)
    hosts.update(
        str(extra).strip().lower() for extra in cfg.allowed_hosts if str(extra).strip()
    )
    return frozenset(hosts)


def check_request(request: Request, allowed_hosts: frozenset[str]) -> Response | None:
    """檢查一個請求；回傳 None＝放行，否則回 403 的 JSONResponse。"""
    raw_host = request.headers.get("host", "")
    request_host = host_name(raw_host)
    if request_host not in allowed_hosts:
        return JSONResponse(
            status_code=403,
            content={
                "detail": f"Host 不在允許清單：{raw_host!r}；"
                "需要的話可在 config.json 的 allowed_hosts 加入"
            },
        )

    origin = (request.headers.get("origin") or "").strip()
    if origin:
        parsed = urlsplit(origin)
        origin_host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in ("http", "https")
            or not origin_host
            or origin_host not in allowed_hosts
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Origin 不受信任：{origin!r}"},
            )
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if origin_port != host_port(raw_host):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Origin 與請求的埠不一致：{origin!r}"},
            )

    if request.method.upper() not in SAFE_METHODS:
        if request.headers.get(CLIENT_HEADER) != CLIENT_HEADER_VALUE:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "缺少或錯誤的 "
                    f"{CLIENT_HEADER}: {CLIENT_HEADER_VALUE} 標頭；"
                    "變更類請求必須帶上這個標頭（ItemTrace 網頁會自動附加）"
                },
            )
    return None


def enforce_ai_quota(request: Request) -> None:
    """SR-2（F4）：AI provider 呼叫端點共用的節流（analyze／settings 測試）。

    限流器掛在 `app.state.analyze_limiter`（單一行程；多 worker 的限制
    見 shop/limits.py docstring）。超限回 429 並附 Retry-After。
    """
    limiter = getattr(request.app.state, "analyze_limiter", None)
    if limiter is None:
        return
    if not limiter.consume():
        retry = limiter.retry_after() or 60
        raise HTTPException(
            status_code=429,
            detail=(
                f"AI 分析請求過於頻繁（每分鐘上限 {limiter.limit} 次）；"
                f"請在 {retry} 秒後再試。"
            ),
            headers={"Retry-After": str(retry)},
        )


# ----------------------------------------------------------------------
# 連線身分與授權（三層模型；流程與安全模型見 shop/pairing.py）
# ----------------------------------------------------------------------

SESSION_ADMIN = "admin"
SESSION_DEVICE = "device"
SESSION_UNPAIRED = "unpaired"

#: 未配對連線仍可存取的最小 API 集合（完成配對與前端啟動判斷所必需）。
#: /api/health 供連線自我檢查；/api/session 讓前端決定顯示配對引導頁；
#: /api/pairing/claim 是配對動作本身。
PUBLIC_API_PATHS = frozenset({"/api/health", "/api/session", "/api/pairing/claim"})

#: 配對管理 API：只有電腦本機（loopback）可以呼叫。
ADMIN_API_PREFIXES = (
    "/api/pairing/start",
    "/api/pairing/devices",
    "/api/pairing/sessions",
)


class SessionInfo:
    """一個請求的授權身分（guard_request 判定後放在 request.state.session）。"""

    __slots__ = ("role", "device_id", "device_name")

    def __init__(
        self, role: str, device_id: str | None = None, device_name: str | None = None
    ) -> None:
        self.role = role
        self.device_id = device_id
        self.device_name = device_name


def is_loopback_client(request: Request) -> bool:
    """請求是否來自電腦本機（只看 socket 對端位址，不看任何標頭）。"""
    client = request.client
    if client is None or not client.host:
        return False
    try:
        address = ipaddress.ip_address(client.host)
    except ValueError:
        # 測試用的 "testclient" 或非 IP 主機名一律視為非本機。
        return False
    if address.is_loopback:
        return True
    # dual-stack（IPv6 socket）上，本機連線可能呈現為 IPv4-mapped 位址。
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def extract_bearer_token(request: Request) -> str | None:
    """從 Authorization 標頭提取 Bearer 權杖。"""
    auth = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if auth.startswith(prefix):
        token = auth[len(prefix):].strip()
        return token or None
    return None


def extract_device_cookie(request: Request) -> str | None:
    """裝置 cookie。

    手機瀏覽器的 ``<img src="/files/...">`` 不會經過 fetch、不會帶
    Authorization 標頭，所以配對成功時伺服器另外下一個 HttpOnly cookie，
    讓媒體請求也能通過裝置認證（狀態改變端點另受 CSRF 標頭保護）。
    """
    value = request.cookies.get(pairing.COOKIE_NAME, "")
    return value.strip() or None


def request_device_token(request: Request) -> str | None:
    return extract_bearer_token(request) or extract_device_cookie(request)


def _lookup_device(cfg, token: str):
    with db.session(cfg) as conn:
        repo = Repository(conn, cfg)
        device = repo.find_paired_device_by_token(token)
        if device is not None:
            repo.touch_paired_device(device.id)  # 內部有 60 秒節流
        return device


def guard_request(
    request: Request, cfg, allowed_hosts: frozenset[str]
) -> Response | None:
    """單一入口：Host／Origin／CSRF 檢查 ＋ 三層授權。

    回傳 None＝放行（並在 ``request.state.session`` 放入 SessionInfo），
    否則回傳 JSONResponse。未配對連線只放行 PUBLIC_API_PATHS 與靜態前端；
    配對管理端點只放行電腦本機；其餘 /api/* 與 /files/* 需要 admin 或
    有效且未撤銷的裝置權杖。
    """
    rejection = check_request(request, allowed_hosts)
    if rejection is not None:
        return rejection

    path = request.url.path
    if not (path.startswith("/api/") or path.startswith("/files/")):
        # 前端殼、配對頁與靜態資源：任何連線都可載入（不含任何資料）。
        return None

    admin = is_loopback_client(request)
    device = None
    token = None
    if not admin:
        token = request_device_token(request)
        if token:
            device = _lookup_device(cfg, token)

    valid_device = device is not None and device.revoked_at is None
    if admin:
        info = SessionInfo(SESSION_ADMIN)
    elif valid_device:
        info = SessionInfo(SESSION_DEVICE, device.id, device.name)
    else:
        info = SessionInfo(SESSION_UNPAIRED)
    request.state.session = info

    if path in PUBLIC_API_PATHS:
        return None

    if path.startswith(ADMIN_API_PREFIXES) and not admin:
        return JSONResponse(
            status_code=403,
            content={
                "detail": "配對管理僅限電腦本機操作；請在電腦上開啟 ItemTrace 設定頁"
            },
        )

    if admin or valid_device:
        return None

    if token:
        # 帶了憑證但無效或已撤銷：明確告知授權失效（前端會清除本機權杖）。
        return JSONResponse(
            status_code=401,
            content={"detail": "裝置授權無效或已撤銷；請在電腦上重新配對"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return JSONResponse(
        status_code=403,
        content={
            "detail": "此裝置尚未配對，無法存取 ItemTrace 資料；"
            "請先在電腦上完成手機配對"
        },
    )
