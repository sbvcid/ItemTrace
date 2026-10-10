"""ID 產生與序號正規化。

items / observations 用人類可讀短碼：既是主鍵也是資料夾名，
你會想自己去翻 files/，所以不用 UUID。
事件等內部紀錄用 ULID（時間有序，單人寫入不會碰撞）。
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

from .config import Config

ITEM_PREFIX = "ITM"
ITEM_WIDTH = 4
TEMPLATE_PREFIX = "TPL"
TEMPLATE_WIDTH = 4
OBSERVATION_KINDS = ("intake", "recheck", "manual")
NON_ALNUM = re.compile(r"[\s\-_/\\.,;:'\"()\[\]{}<>+*&^%$#@!?]")

_RAND_BITS = 80
_RAND_LIMIT = 1 << _RAND_BITS
_LAST_MS = -1
_LAST_RAND = 0


def now_ulid() -> str:
    """時間有序的 26 字元 ID。

    同一毫秒內遞增亂數部分，而不是每次重抽 —— 重抽會讓同一毫秒內產生的
    ID 順序變成隨機，而 events 是用 id 當同秒事件的排序依據，歷史順序
    必須反映實際寫入順序。
    """
    global _LAST_MS, _LAST_RAND

    ms = int(time.time() * 1000)
    if ms > _LAST_MS:
        _LAST_MS = ms
        _LAST_RAND = int.from_bytes(os.urandom(10), "big")
    else:
        # 同一毫秒，或系統時鐘被往後校正：遞增亂數部分保持單調。
        _LAST_RAND += 1
        if _LAST_RAND >= _RAND_LIMIT:
            _LAST_MS += 1
            _LAST_RAND = 0

    value = (_LAST_MS << _RAND_BITS) | _LAST_RAND
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out = ""
    for _ in range(26):
        out = alphabet[value & 31] + out
        value >>= 5
    return out


def new_id() -> str:
    return now_ulid()


#: schema_meta 的鍵：ITM 編號已配發的上限（永久刪除後仍不回收）。
_ITEM_SEQ_KEY = "items_seq"


def _meta_int(conn, key: str) -> int:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _set_meta_int(conn, key: str, value: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _numeric_suffix(item_id: str) -> int | None:
    """'ITM-<純數字>' 的數字部分；其他形狀回 None。"""
    prefix = f"{ITEM_PREFIX}-"
    if not item_id.startswith(prefix):
        return None
    tail = item_id[len(prefix):]
    if not tail or not tail.isascii() or not tail.isdigit():
        return None
    return int(tail)


def _max_numeric_suffix(conn, table: str, prefix: str) -> int:
    """找出 prefix 之下最大的數字後綴。

    不能用 ORDER BY id DESC 取最大：那是字串排序，'ITM-10000' < 'ITM-9999'，
    破萬之後就會發號錯亂。CAST 成整數才正確。
    結尾不是純數字的 id（例如手動輸入的 'ITM-0001-old'）不參與發號。
    """
    start = len(prefix) + 1
    row = conn.execute(
        # table 與 start 都來自模組內的呼叫端，不是使用者輸入。
        f"""
        SELECT max(CAST(substr(id, {start}) AS INTEGER)) AS n
          FROM {table}
         WHERE id LIKE ?
           AND length(substr(id, {start})) > 0
           AND substr(id, {start}) NOT GLOB '*[^0-9]*'
        """,
        (prefix + "%",),
    ).fetchone()
    return int(row["n"]) if row and row["n"] is not None else 0


def next_item_id(conn, config: Config) -> str:
    prefix = f"{ITEM_PREFIX}-"
    n = max(
        _max_numeric_suffix(conn, "items", prefix),
        _meta_int(conn, _ITEM_SEQ_KEY),
    ) + 1
    # 配發過就記進 schema_meta：永久刪除把列整個移除後，items 表的最大值
    # 會倒退，這個記號保證編號永不回收（與 void 的既有原則一致）。
    _set_meta_int(conn, _ITEM_SEQ_KEY, n)
    del config  # 保留參數以便未來加入前綴設定
    return f"{prefix}{n:0{ITEM_WIDTH}d}"


def burn_item_sequence(conn, item_id: str) -> None:
    """永久刪除前記下編號，確保之後的發號不回收再利用。

    只做「往上記」：比現有記號小或不像 ITM-<數字> 的 id（手動輸入的）
    不需要也不能影響發號。
    """
    suffix = _numeric_suffix(item_id)
    if suffix is not None and suffix > _meta_int(conn, _ITEM_SEQ_KEY):
        _set_meta_int(conn, _ITEM_SEQ_KEY, suffix)


def next_observation_id(conn, date: str | None = None) -> str:
    # 只取日期部分：傳進來的是完整時間戳時也不會生出畸形的主鍵。
    day = (date or time.strftime("%Y%m%d"))[:10].replace("-", "")
    prefix = f"OBS-{day}-"
    n = _max_numeric_suffix(conn, "observations", prefix) + 1
    return f"{prefix}{n:02d}"


def next_template_id(conn) -> str:
    """產生 Template ID：TPL-XXXX 格式。"""
    prefix = f"{TEMPLATE_PREFIX}-"
    n = _max_numeric_suffix(conn, "templates", prefix) + 1
    return f"{prefix}{n:0{TEMPLATE_WIDTH}d}"


def normalize_identifier(value: str) -> str:
    """序號正規化：轉大寫、移除空白與常見分隔符號。

    實測：BX-807 06_1234 → BX807061234，搜尋 807061234 可命中。
    """
    return NON_ALNUM.sub("", (value or "")).upper()


def item_dir(config: Config, item_id: str) -> Path:
    return config.files_dir / item_id


def uuid4() -> str:
    return uuid.uuid4().hex