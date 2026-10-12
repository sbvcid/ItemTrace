"""資料庫連線、schema 套用與備份。

注意：資料庫跑在 WAL 模式，未寫回的資料會留在 catalog.db-wal。
**絕不可用 shutil.copy 備份**，必須用 Connection.backup()，否則會漏掉最近幾筆紀錄。
這是本專案實際踩過的坑，見 SPEC-v1 §8。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .config import Config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "3"


def connect(config: Config) -> sqlite3.Connection:
    config.database.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：HTTP 服務會在 threadpool 建立連線、在 event loop
    # 執行路由，兩者不是同一個執行緒。安全的前提是「一請求一連線」，
    # 連線不跨請求共用；併發寫入由 WAL + busy_timeout 序列化。
    conn = sqlite3.connect(config.database, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def session(config: Config) -> Iterator[sqlite3.Connection]:
    conn = connect(config)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """把一組寫入包成單一交易。

    connect() 用 isolation_level=None（autocommit），所以交易要自己下指令。
    已在交易中就沿用外層，避免巢狀 BEGIN 讓復原操作提早結束交易。

    資料與 events 必須在同一個交易裡寫入 —— 這是 SPEC-v1 §1「一切有來源」的
    底線：不可能出現「資料改了但沒紀錄」或反過來的狀態。

    刻意用 BEGIN IMMEDIATE（不是 deferred BEGIN）：寫入方法幾乎都是
    「先讀後寫」（例如 accept 先讀 suggestion 再 UPDATE）。多條連線併發時，
    deferred 交易先讀會取到 WAL 快照，等另一條連線提交後再寫 →
    SQLITE_BUSY_SNAPSHOT（busy handler 救不了，直接噴 database is locked）。
    IMMEDIATE 在交易開頭就取得寫鎖，connect() 的 busy_timeout=5000 才能
    讓第二個 writer 排隊等待 —— 本地單寫入者情境下，也就是「先到先做」。
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init(config: Config) -> bool:
    """建立 schema。回傳 True 代表這是首次建立。"""
    fresh = not config.database.exists()
    with session(config) as conn:
        _migrate_pairing_tables(conn)
        _migrate_phase4_folders(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('created_at', ?)",
            (now(),),
        )
    return fresh


def _migrate_pairing_tables(conn: sqlite3.Connection) -> None:
    """配對表的最小遷移。

    手機配對尚未正式發行，但開發中的資料庫可能已存在舊形狀的
    paired_devices（公鑰模型）。該表只保存配對憑證、沒有使用者資料，
    偵測到舊形狀時直接重建 —— 代價是舊裝置需要重新配對，不會動到
    物品、照片或事件。
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paired_devices'"
    ).fetchone()
    if row is None:
        return
    columns = {info[1] for info in conn.execute("PRAGMA table_info(paired_devices)")}
    if "token_hash" not in columns:
        conn.execute("DROP TABLE paired_devices")


def _migrate_phase4_folders(conn: sqlite3.Connection) -> None:
    """Phase 4 資料夾遷移。

    - 若 items 表中尚無 folder_id 欄位，執行建表（STRICT 不支援 ALTER TABLE，
      所以只能透過 CREATE TABLE AS SELECT 搭配 DROP/RENAME）
    - 既有紀錄的 folder_id 預設為 NULL（未分類）
    - 新表（folders/folder_rules/folder_classifications）在主 schema.sql 創建
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
    ).fetchone()
    if row is None:
        # 首次建立，schema.sql 會處理
        return
    
    columns = {info[1] for info in conn.execute("PRAGMA table_info(items)")}
    if "folder_id" in columns:
        # 已升級，無需動作
        return
    
    # items 表需要添加 folder_id，但 STRICT 表不支援 ALTER TABLE ADD COLUMN
    # 改用重建表的方式（SQLite 標準做法）
    conn.execute("""
        CREATE TABLE items_new (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL DEFAULT '',
            brand       TEXT NOT NULL DEFAULT '',
            model       TEXT NOT NULL DEFAULT '',
            category    TEXT NOT NULL DEFAULT '',
            quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
            condition   TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            attributes  TEXT NOT NULL DEFAULT '{}',
            folder_id   TEXT,
            status      TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','archived','void')),
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        ) STRICT
    """)
    
    # 複製既有資料（folder_id 為 NULL）
    conn.execute("""
        INSERT INTO items_new 
        (id, name, brand, model, category, quantity, condition, notes, 
         attributes, folder_id, status, created_at, updated_at)
        SELECT 
        id, name, brand, model, category, quantity, condition, notes, 
        attributes, NULL, status, created_at, updated_at
        FROM items
    """)
    
    # 移除舊表、重命名新表
    conn.execute("DROP TABLE items")
    conn.execute("ALTER TABLE items_new RENAME TO items")


def version(config: Config) -> str:
    with session(config) as conn:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
    return row["value"] if row else "unknown"


def stats(config: Config) -> dict[str, int]:
    with session(config) as conn:
        counts = {}
        for table in ("items", "observations", "photos", "identifiers",
                      "suggestions", "events"):
            counts[table] = conn.execute(
                f"SELECT count(*) FROM {table}"  # noqa: S608 — 固定表名，非使用者輸入
            ).fetchone()[0]
    return counts


def backup(config: Config) -> Path:
    """輸出完整快照（資料庫 + 檔案樹）到 backups/shop-<timestamp>/。"""
    if not config.database.exists():
        raise FileNotFoundError("尚未初始化，請先執行 shopctl.py init")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = config.backup_dir / f"shop-{stamp}"
    target.mkdir(parents=True, exist_ok=False)

    src = connect(config)
    try:
        dst = sqlite3.connect(target / config.database.name)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    for name in ("files", "inbox"):
        source = config.data_root / name
        if source.is_dir():
            _copy_tree(source, target / name)

    (target / "BACKUP.txt").write_text(
        f"created: {now()}\nschema: {SCHEMA_VERSION}\n"
        f"source:  {config.data_root}\n"
        "restore: 整份資料夾複製回去，覆蓋原 shop/ 即可。\n",
        encoding="utf-8",
    )
    return target


def prune_backups(config: Config) -> int:
    """只保留最近 backup_keep 份快照。"""
    if not config.backup_dir.is_dir():
        return 0
    snapshots = sorted(
        (p for p in config.backup_dir.iterdir()
         if p.is_dir() and p.name.startswith("shop-")),
        reverse=True,
    )
    removed = 0
    for path in snapshots[config.backup_keep:]:
        _remove_tree(path)
        removed += 1
    return removed


def verify(config: Config) -> dict[str, object]:
    """檢查資料庫完整性，並找出檔案與資料庫不一致的地方。"""
    report: dict[str, object] = {"database": config.database}
    with session(config) as conn:
        report["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        report["schema_version"] = version(config)
        report["counts"] = stats(config)

        missing = conn.execute(
            "SELECT p.filename FROM photos p WHERE p.role = 'original'"
        ).fetchall()
        # photos.filename 存的是相對 DATA_ROOT 的路徑（SPEC-v1 §3），
        # 不是相對 files/，所以用 config.resolve() 還原。
        orphans = [
            row["filename"]
            for row in missing
            if not config.resolve(row["filename"]).exists()
        ]
        report["missing_original_photos"] = orphans
        report["ok"] = report["integrity"] == "ok" and not orphans
    return report


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _copy_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.is_dir():
            _copy_tree(entry, target / entry.name)
        else:
            (target / entry.name).write_bytes(entry.read_bytes())


def _remove_tree(path: Path) -> None:
    for entry in path.rglob("*"):
        if entry.is_file():
            entry.unlink()
    for entry in sorted(path.rglob("*"), reverse=True):
        if entry.is_dir():
            entry.rmdir()
    path.rmdir()