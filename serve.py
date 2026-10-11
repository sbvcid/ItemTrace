"""啟動本機 HTTP 服務。

    python serve.py                 用 config.json 的 host/port（預設 0.0.0.0）
    python serve.py --port 8732     覆寫
    python serve.py --reload        開發時自動重載

資料根目錄與資料庫位置全部來自 config.json，不接受命令列指定 DATA_ROOT ——
服務只服務它自己的那一份資料夾。

手機配對（免設定檔）需要服務綁定區網位址，所以預設 host 是 0.0.0.0。
這不是「開放區網」：未配對的區網裝置只能載入前端殼、配對頁與完成配對
所需的最小端點；所有資料 API 與照片都需要電腦本機（loopback）或已配對
裝置的權杖（三層信任模型見 shop/security.py）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shop import config as config_mod  # noqa: E402


def resolve_bind_host(config: config_mod.Config, override: str | None = None) -> str:
    """決定綁定位址：命令列 > config.json > 預設 0.0.0.0。"""
    return (override if override is not None else config.server_host) or "0.0.0.0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve", description="商品證據與歸檔工具 HTTP 服務"
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    config = config_mod.load()
    host = resolve_bind_host(config, args.host)
    port = args.port or config.server_port

    from shop import pairing, security

    print(f"資料根目錄：{config.data_root}")
    print(f"資料庫     ：{config.database}")
    print(f"本機開啟   ：http://localhost:{port}/")
    if security.is_loopback_bind_host(host):
        if config.local_only:
            print(
                "純本機模式（config.json 的 local_only）：服務只綁 127.0.0.1，"
                "手機無法連線。要使用手機配對，請把 local_only 設為 false "
                "或移除後重新啟動。"
            )
        else:
            print(
                "注意：server_host 目前是 loopback，手機無法連線。"
                "要使用手機配對，請把 config.json 的 server_host 設為 "
                '"0.0.0.0"（預設值）後重新啟動。'
            )
    else:
        for address in pairing.local_ipv4_addresses():
            print(f"區網位址   ：http://{address}:{port}/")
        print(
            "手機配對：在電腦的「設定」頁「手機配對」區塊點選「開始配對」，"
            "用手機掃描 QR Code。\n"
            "未配對的裝置只能看到配對頁；資料與照片需要配對後的裝置權杖。"
        )
    if config.enable_docs:
        print(f"API 文件   ：http://127.0.0.1:{port}/docs（enable_docs=true）")
    else:
        print(
            '             API 文件預設關閉；開發時可在 config.json 設 '
            '"enable_docs": true'
        )

    import uvicorn

    uvicorn.run(
        "shop.api:create_app",
        factory=True,
        host=host,
        port=port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
