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