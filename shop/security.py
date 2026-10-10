"""SR-1 安全防護：Host／Origin 驗證與變更端點標頭（SECURITY-AUDIT F1/F3）。

信任模型：這是本機桌面應用，沒有登入系統。這一層防的不是「區網上的直接
用戶端」（那由 F5 的綁定 opt-in 與『信任區網』文件說明），而是**瀏覽器替
攻擊者送出的請求**：

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

`X-Requested-With` 的檢查是「不變式」：同源瀏覽器前端會帶、外部攻擊網頁
在沒有 CORS 的情況下無法帶。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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
    """綁定位址是否為 loopback（供 serve.py 的 opt-in 判斷）。"""
    value = (host or "").strip()
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_lan_opt_in(config, host: str) -> bool:
    """非 loopback 綁定且未設 allow_lan → 應該拒絕啟動（SR-1／F5）。

    沒有登入機制的服務不無聲開放區網；要開放必須是 config.json 的
    明示選擇。
    """
    return (not is_loopback_bind_host(host)) and not bool(
        getattr(config, "allow_lan", False)
    )


def build_allowed_hosts(cfg) -> frozenset[str]:
    """建立 Host 白名單。

    - 一律允許：`localhost`、`127.0.0.1`、`::1`。
    - `server_host` 是具體位址時允許該位址。
    - `server_host` 是 0.0.0.0／:: 時（區網 opt-in），以本機介面位址與
      主機名盡力補齊；打不到想要的別名時用 config 的 `allowed_hosts` 補。
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
