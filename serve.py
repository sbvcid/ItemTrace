"""啟動本機 HTTP 服務。

    python serve.py                 用 config.json 的 host/port
    python serve.py --port 8732     覆寫
    python serve.py --reload        開發時自動重載

資料根目錄與資料庫位置全部來自 config.json，不接受命令列指定 DATA_ROOT ——
服務只服務它自己的那一份資料夾。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shop import config as config_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve", description="商品證據與歸檔工具 HTTP 服務"
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    config = config_mod.load()
    host = args.host or config.server_host
    port = args.port or config.server_port

    # SR-1（SECURITY-AUDIT F5）：沒有登入機制，非 loopback 綁定必須是
    # 明示的選擇（config.json 的 "allow_lan": true）——不無聲開放區網。
    from shop import security

    if security.require_lan_opt_in(config, host):
        print(
            f"拒絕啟動：server_host={host!r} 會讓這個**沒有登入機制**的服務"
            "暴露到區網，任何同網段裝置都能讀寫全部資料與 AI 設定。\n"
            "  - 只在本機使用（建議）：把 config.json 的 server_host 改成 "
            '"127.0.0.1"\n'
            "  - 確定只在受信任區網使用：把 config.json 加上 "
            '"allow_lan": true 再啟動\n'
            "  （信任模型：區網上的裝置一律視為可完整讀寫；請勿在公用／"
            "不可信網路開放）"
        )
        return 2
    if not security.is_loopback_bind_host(host):
        print("⚠️  區網模式（allow_lan=true）：服務將綁定 "
              f"{host}，任何可連線到此位址的裝置都能完整讀寫所有資料與設定。")
        print("⚠️  請只在家用等受信任網路使用；需要對外一律先關閉。")

    import uvicorn

    print(f"資料根目錄：{config.data_root}")
    print(f"資料庫     ：{config.database}")
    print(f"開啟       ：http://{host}:{port}/docs")
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