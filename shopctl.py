"""shopctl — 商品證據與歸檔工具的命令列介面。

用法：
    python shopctl.py init          建立 config.json 與資料庫
    python shopctl.py stats         顯示各表筆數
    python shopctl.py verify        完整性檢查
    python shopctl.py backup        完整快照（資料庫 + 檔案樹）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shop import config as config_mod  # noqa: E402
from shop import db as db_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shopctl",
        description="商品證據與歸檔工具",
    )
    parser.add_argument("--data-root", type=Path, help="覆寫資料根目錄")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="建立設定檔與資料庫")
    sub.add_parser("stats", help="顯示各表筆數")
    sub.add_parser("verify", help="完整性檢查")
    sub.add_parser("backup", help="完整快照")

    args = parser.parse_args(argv)
    config = config_mod.load(args.data_root)

    handlers = {
        "init": cmd_init,
        "stats": cmd_stats,
        "verify": cmd_verify,
        "backup": cmd_backup,
    }
    return handlers[args.command](config)


def cmd_init(config: config_mod.Config) -> int:
    written = config_mod.write_example(config.base_dir)
    fresh = db_mod.init(config)
    config_mod.ensure_dirs(config)

    print(f"設定檔    ：{written}")
    print(f"資料根目錄：{config.data_root}")
    print(f"資料庫    ：{config.database}")
    print(f"Schema    ：v{db_mod.version(config)}")
    print("建立完成。" if fresh else "資料庫已存在，schema 已確認。")
    return 0


def cmd_stats(config: config_mod.Config) -> int:
    counts = db_mod.stats(config)
    print(f"資料庫：{config.database}")
    for table, count in counts.items():
        print(f"  {table:<14} {count:>6}")
    return 0


def cmd_verify(config: config_mod.Config) -> int:
    report = db_mod.verify(config)
    print(f"資料庫      ：{report['database']}")
    print(f"完整性      ：{report['integrity']}")
    print(f"Schema 版本 ：{report['schema_version']}")
    missing = report["missing_original_photos"]
    print(f"原始照片    ：{len(missing)} 個檔案遺失")
    for name in missing[:10]:
        print(f"    遺失 {name}")
    print("檢查通過。" if report["ok"] else "檢查未通過。")
    return 0 if report["ok"] else 1


def cmd_backup(config: config_mod.Config) -> int:
    target = db_mod.backup(config)
    removed = db_mod.prune_backups(config)
    print(f"已備份：{target}")
    if removed:
        print(f"已清理 {removed} 份舊快照（保留 {config.backup_keep} 份）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())