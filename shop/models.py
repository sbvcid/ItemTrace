"""型別化的資料列：資料庫的 TEXT/INTEGER/REAL 與 Python 型別之間的橋樑。

每個 dataclass 都與 schema.sql 的一張表一對一，欄位名稱刻意與 DDL 完全相同，
讓 SQL 與型別不會各說各話。資料表是 STRICT 表，型別不符會在寫入時直接被擋下，
所以這一層只處理三件事：列舉值集中管理、JSON 欄位轉換、None 的處理。

列舉值取自 DDL 的 CHECK 約束，DDL 是最後一道防線；這裡先擋一次是為了讓
錯誤訊息可讀（sqlite3.IntegrityError 只會丟一句不明的 constraint failed）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Mapping

from .errors import ValidationError
from .ids import OBSERVATION_KINDS

__all__ = [
    "Event",
    "Identifier",
    "Item",
    "Observation",
    "Photo",
    "Suggestion",
    "Template",
    "IDENTIFIER_KINDS",
    "IDENTIFIER_SOURCES",
    "ITEM_STATUSES",
    "OBSERVATION_KINDS",
    "PHOTO_ROLES",
    "SUGGESTABLE_FIELDS",
    "SUGGESTION_STATUSES",
    "dumps_object",
    "loads_object",
    "loads_value",
]

ITEM_STATUSES = ("active", "archived", "void")
PHOTO_ROLES = ("original", "derived")
IDENTIFIER_KINDS = ("serial", "imei", "barcode", "custom")
IDENTIFIER_SOURCES = ("human", "accepted_suggestion")
SUGGESTION_STATUSES = ("pending", "accepted", "rejected", "superseded")

#: suggestions.field 允許直接寫入 items 的欄位；identifier 類另建 identifiers
#: （SPEC-v1 §2.2 field 註解：name|brand|model|category|condition|identifier:serial）。
#: suggestions.field 可以直接寫進 items 的欄位；identifier 類另建 identifiers。
#: 來源是 SPEC-v1 §2.2 的 field 註解，Phase 8A 起加上 notes ——
#: 外部 Vision 常從照片推斷外觀描述，放進 notes 合理。
#: quantity 不在列表裡：數量是事實，不是 AI 的判斷。
SUGGESTABLE_FIELDS = ("name", "brand", "model", "category", "condition", "notes")

#: suggestions.field 的識別碼前綴，後面接 identifiers.kind。
IDENTIFIER_FIELD_PREFIX = "identifier:"


def dumps_object(value: Mapping[str, Any] | None) -> str:
    """items.attributes 序列化。排序鍵，讓 events 的 payload 可重現。"""
    return json.dumps(dict(value or {}), ensure_ascii=False, sort_keys=True)


def loads_object(raw: str | None, field: str) -> dict[str, Any]:
    """items.attributes 反序列化。壞掉的資料要吵出來，不要靜默吞掉。"""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{field} 不是合法的 JSON：{raw!r}") from exc
    if not isinstance(value, dict):
        raise ValidationError(
            f"{field} 必須是 JSON 物件，得到 {type(value).__name__}：{raw!r}"
        )
    return value


def loads_value(raw: Any) -> Any:
    """events.prev_value / next_value 的反序列化（JSON encoded）。

    events.append 寫入時一律 JSON 編碼，但 history() 已經解過一次，
    所以這裡要能接受已經是 Python 值的輸入。
    """
    if raw is None or not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


Row = sqlite3.Row | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    quantity: int = 1
    condition: str = ""
    notes: str = ""
    attributes: dict[str, Any] = dataclass_field(default_factory=dict)
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Item:
        return cls(
            id=row["id"],
            name=row["name"],
            brand=row["brand"],
            model=row["model"],
            category=row["category"],
            quantity=row["quantity"],
            condition=row["condition"],
            notes=row["notes"],
            attributes=loads_object(row["attributes"], "items.attributes"),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    item_id: str
    kind: str = "intake"
    note: str = ""
    captured_at: str | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Observation:
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            kind=row["kind"],
            note=row["note"],
            captured_at=row["captured_at"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Photo:
    id: str
    item_id: str
    filename: str
    role: str = "original"
    orig_name: str = ""
    sha256: str = ""
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    captured_at: str | None = None
    angle: str = ""
    source: str = "manual"
    observation_id: str | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Photo:
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            observation_id=row["observation_id"],
            role=row["role"],
            filename=row["filename"],
            orig_name=row["orig_name"],
            sha256=row["sha256"],
            bytes=row["bytes"],
            width=row["width"],
            height=row["height"],
            captured_at=row["captured_at"],
            angle=row["angle"],
            source=row["source"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Identifier:
    id: str
    item_id: str
    kind: str
    value: str
    normalized: str
    confidence: float | None = None
    source: str = "human"
    source_photo_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Identifier:
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            kind=row["kind"],
            value=row["value"],
            normalized=row["normalized"],
            confidence=row["confidence"],
            source=row["source"],
            source_photo_id=row["source_photo_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class Suggestion:
    id: str
    item_id: str
    field: str
    value: str
    confidence: float | None = None
    source: str = "external"
    model_name: str = ""
    source_photo_id: str | None = None
    status: str = "pending"
    created_at: str = ""
    decided_at: str | None = None

    @property
    def identifier_kind(self) -> str | None:
        """field 為 identifier:<kind> 時回傳 <kind>，否則 None。"""
        if self.field.startswith(IDENTIFIER_FIELD_PREFIX):
            return self.field[len(IDENTIFIER_FIELD_PREFIX):]
        return None

    @classmethod
    def from_row(cls, row: Row) -> Suggestion:
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            field=row["field"],
            value=row["value"],
            confidence=row["confidence"],
            source=row["source"],
            model_name=row["model_name"],
            source_photo_id=row["source_photo_id"],
            status=row["status"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    entity_type: str
    entity_id: str
    type: str
    actor: str = "user"
    field: str | None = None
    prev_value: Any = None
    next_value: Any = None
    payload: dict[str, Any] = dataclass_field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Event:
        payload = loads_value(row["payload"])
        return cls(
            id=row["id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            type=row["type"],
            actor=row["actor"],
            field=row["field"],
            prev_value=loads_value(row["prev_value"]),
            next_value=loads_value(row["next_value"]),
            payload=payload if isinstance(payload, dict) else {},
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class Template:
    """Template entity for HTML/CSS rendering.

    Templates are untrusted user input. They define HTML structure with
    explicit data-bind attributes for field substitution.
    """

    id: str
    name: str
    html: str
    width: float | None = None
    height: float | None = None
    unit: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Row) -> Template:
        return cls(
            id=row["id"],
            name=row["name"],
            html=row["html"],
            width=row["width"] if row["width"] is not None else None,
            height=row["height"] if row["height"] is not None else None,
            unit=row["unit"] or None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
