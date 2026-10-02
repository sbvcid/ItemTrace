"""事件記錄：所有寫入都要留下可追溯、可復原的痕跡。

這是 SPEC-v1 §1「一切有來源」的實作。prev_value / next_value 讓單一欄位
復原不需要額外邏輯。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import now
from .ids import new_id

ENTITY_TYPES = ("item", "identifier", "photo", "observation", "suggestion")
ACTORS = ("user", "external", "system")


def append(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: str,
    type: str,
    actor: str = "user",
    field: str | None = None,
    prev_value: Any = None,
    next_value: Any = None,
    payload: dict[str, Any] | None = None,
) -> str:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"未知的 entity_type：{entity_type}")
    if actor not in ACTORS:
        raise ValueError(f"未知的 actor：{actor}")

    event_id = new_id()
    conn.execute(
        """
        INSERT INTO events
            (id, entity_type, entity_id, type, actor, field,
             prev_value, next_value, payload, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            entity_type,
            entity_id,
            type,
            actor,
            field,
            _encode(prev_value),
            _encode(next_value),
            json.dumps(payload or {}, ensure_ascii=False),
            now(),
        ),
    )
    return event_id


def record_field_change(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: str,
    field: str,
    before: Any,
    after: Any,
    actor: str = "user",
) -> str | None:
    """值未變動時不寫事件，避免歷史被雜訊淹沒。"""
    if _encode(before) == _encode(after):
        return None
    return append(
        conn,
        entity_type=entity_type,
        entity_id=entity_id,
        type="field.changed",
        actor=actor,
        field=field,
        prev_value=before,
        next_value=after,
    )


def history(
    conn: sqlite3.Connection, entity_type: str, entity_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE entity_type = ? AND entity_id = ?"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (entity_type, entity_id, limit),
    ).fetchall()
    return [_decode(dict(row)) for row in rows]


def revert(
    conn: sqlite3.Connection, event_id: str
) -> tuple[str, str, str, Any] | None:
    """把 field.changed 事件還原，回傳 (entity_type, entity_id, field, prev_value)。

    回傳 None 代表這筆事件不存在，或不是可還原的單欄位變更
    （type 必須是 field.changed，且 field 與 prev_value 都要有值）。
    """
    row = conn.execute(
        "SELECT * FROM events WHERE id = ? AND type = 'field.changed'",
        (event_id,),
    ).fetchone()
    if not row or not row["field"] or row["prev_value"] is None:
        return None
    return (
        row["entity_type"],
        row["entity_id"],
        row["field"],
        _decode_value(row["prev_value"]),
    )


def _encode(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _decode_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    row["prev_value"] = _decode_value(row["prev_value"]) if row["prev_value"] else None
    row["next_value"] = _decode_value(row["next_value"]) if row["next_value"] else None
    row["payload"] = _decode_value(row["payload"])
    return row