"""型別化資料存取層（SPEC-v1 §10 階段 2）。

這是 API（階段 4）與 UI（階段 6 起）唯一的寫入途徑，只做四件事：

1. 型別化 CRUD —— 一律回傳 dataclass，不讓 sqlite3.Row 漏到上層
2. ID 產生 —— items/observations 用可讀短碼，其餘用 ULID（SPEC-v1 §14.1）
3. events 寫入 —— 資料與事件永遠在同一個交易內落盤
4. 基本資料存取 —— 列表、篩選、分頁

刻意不做，避免越過階段邊界：
  * 檔案落盤、EXIF、sha256 去重 → 階段 3（見 shop.photos / shop.inbox）
  * HTTP 形狀與狀態碼          → 階段 4（見 shop.api）

刪除語意遵守 SPEC-v1 §1、§2.3：

正常生命週期
  items        → 只能 void（status='void'），資料與檔案都保留
  photos       → 只能刪 role='derived'；original 要刪必須先改 role，
                 那是明確表態，不會在流程中被悄悄蓋掉
  identifiers  → 可以刪（API 契約明列 DELETE），但 events 留完整快照
  observations → 不刪，只改狀態
  suggestions  → 不刪，接受與拒絕都保留（推論與事實分離）

永久淘汰
  使用者明確決定要永久刪除某件商品時，未來會允許一次性刪除該 item、
  四張子表與 files/<item-id>/ 整棵目錄樹。**不做任何自動過期清理。**
  那條路徑尚未實作，API 與 UI 都還沒有提供；日常一律走 void。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Union

from . import db, events, ids
from .config import Config
from .errors import ConflictError, NotFoundError, ValidationError
from .models import (
    IDENTIFIER_FIELD_PREFIX,
    IDENTIFIER_KINDS,
    IDENTIFIER_SOURCES,
    ITEM_STATUSES,
    OBSERVATION_KINDS,
    PHOTO_ROLES,
    SUGGESTABLE_FIELDS,
    SUGGESTION_STATUSES,
    Event,
    Identifier,
    Item,
    Observation,
    Photo,
    Suggestion,
    Template,
    dumps_object,
)

#: 可被 update_* 修改的欄位。刻意不含 id / created_at / updated_at ——
#: 識別碼一旦寫入就不該改，時間戳由系統維護。
ITEM_EDITABLE_FIELDS = (
    "name", "brand", "model", "category", "quantity",
    "condition", "notes", "attributes", "status",
)
OBSERVATION_EDITABLE_FIELDS = ("kind", "note", "captured_at")
PHOTO_EDITABLE_FIELDS = (
    "observation_id", "role", "filename", "orig_name", "sha256",
    "bytes", "width", "height", "captured_at", "angle", "source",
)
IDENTIFIER_EDITABLE_FIELDS = (
    "kind", "value", "confidence", "source", "source_photo_id",
)
SUGGESTION_EDITABLE_FIELDS = (
    "field", "value", "confidence", "model_name", "source_photo_id",
)

#: 欄位順序對齊 schema.sql 的 DDL。
ITEM_COLUMNS = ("id",) + ITEM_EDITABLE_FIELDS + ("created_at", "updated_at")
OBSERVATION_COLUMNS = ("id", "item_id") + OBSERVATION_EDITABLE_FIELDS + ("created_at",)
PHOTO_COLUMNS = (
    "id", "item_id", "observation_id", "role", "filename", "orig_name",
    "sha256", "bytes", "width", "height", "captured_at", "angle", "source",
    "created_at",
)
IDENTIFIER_COLUMNS = (
    "id", "item_id", "kind", "value", "normalized", "confidence", "source",
    "source_photo_id", "created_at", "updated_at",
)
SUGGESTION_COLUMNS = (
    "id", "item_id", "field", "value", "confidence", "source", "model_name",
    "source_photo_id", "status", "created_at", "decided_at",
)

TEMPLATE_COLUMNS = (
    "id", "name", "html", "width", "height", "unit", "created_at", "updated_at",
)

#: JSON 欄位：Python 端是 dict，資料庫端是 TEXT。
_JSON_FIELDS: dict[str, tuple[str, ...]] = {"items": ("attributes",)}

#: 從 JSON 進來時可能是字串（例如表單送出 "3"），寫入前先轉成宣告型別。
_COERCERS: dict[str, dict[str, Any]] = {
    "items": {"quantity": int},
    "photos": {"bytes": int, "width": int, "height": int},
    "identifiers": {"confidence": float},
    "suggestions": {"confidence": float},
}

#: events 復原時的對應表：entity_type → (update 方法名, 可用欄位)。
_REVERT_TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "item": ("update_item", ITEM_EDITABLE_FIELDS),
    "observation": ("update_observation", OBSERVATION_EDITABLE_FIELDS),
    "photo": ("update_photo", PHOTO_EDITABLE_FIELDS),
    "identifier": ("update_identifier", IDENTIFIER_EDITABLE_FIELDS),
    "suggestion": ("update_suggestion", SUGGESTION_EDITABLE_FIELDS),
}

Entity = Union[Item, Observation, Photo, Identifier, Suggestion]


class Repository:
    """SPEC-v1 六張表的型別化存取。

    一個實例綁定一條連線；寫入方法自行開交易，巢狀呼叫會沿用外層交易，
    所以 accept_suggestion 這種「同時動多張表」的操作可以安全組裝。
    """

    def __init__(self, conn: sqlite3.Connection, config: Config) -> None:
        self.conn = conn
        self.config = config

    @classmethod
    @contextmanager
    def open(cls, config: Config) -> Iterator[Repository]:
        with db.session(config) as conn:
            yield cls(conn, config)

    # ------------------------------------------------------------------
    # items
    # ------------------------------------------------------------------

    def create_item(
        self,
        *,
        name: str = "",
        brand: str = "",
        model: str = "",
        category: str = "",
        quantity: int = 1,
        condition: str = "",
        notes: str = "",
        attributes: Mapping[str, Any] | None = None,
        actor: str = "user",
    ) -> Item:
        """建立商品。status 固定為 active —— DDL 沒有 draft 這個值。"""
        with db.transaction(self.conn):
            stamp = db.now()
            item = Item(
                id=ids.next_item_id(self.conn, self.config),
                name=name,
                brand=brand,
                model=model,
                category=category,
                quantity=_coerce("items", "quantity", quantity),
                condition=condition,
                notes=notes,
                attributes=dict(attributes or {}),
                status="active",
                created_at=stamp,
                updated_at=stamp,
            )
            _validate_item(item)
            _insert(self.conn, "items", ITEM_COLUMNS, item)
            events.append(
                self.conn,
                entity_type="item",
                entity_id=item.id,
                type="item.created",
                actor=actor,
                payload=_snapshot(item),
            )
            return item

    def get_item(self, item_id: str) -> Item:
        return Item.from_row(_fetch(self.conn, "items", item_id))

    def list_items(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Item]:
        where, params = _where({"status": status, "category": category})
        limit, offset = _paging(limit, offset)
        if q and q.strip():
            # SPEC-v1 §7.2：v1 用 LIKE，不用 FTS5（實測 FTS5 查不到兩字中文，
            # 而資料量在數千筆以內全表掃描完全夠快）。§7.3 的搜尋範圍。
            text = f"%{q.strip()}%"
            normalized = f"%{ids.normalize_identifier(q)}%"
            where = (
                " WHERE i.id IN ("
                "   SELECT i2.id FROM items i2"
                "    LEFT JOIN identifiers d ON d.item_id = i2.id"
                "    WHERE i2.name LIKE ? OR i2.brand LIKE ? OR i2.model LIKE ?"
                "       OR i2.category LIKE ? OR i2.notes LIKE ? OR i2.attributes LIKE ?"
                "       OR d.value LIKE ? OR d.normalized LIKE ?"
                " )" + where.replace(" WHERE ", " AND ", 1)
            )
            params = [
                text, text, text, text, text, text, text, normalized, *params
            ]
            rows = self.conn.execute(
                f"SELECT i.* FROM items i{where} ORDER BY i.id LIMIT ? OFFSET ?",  # noqa: S608
                (*params, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT * FROM items{where} ORDER BY id LIMIT ? OFFSET ?",  # noqa: S608
                (*params, limit, offset),
            ).fetchall()
        return [Item.from_row(row) for row in rows]

    def lookup_identifiers(
        self, value: str, *, kind: str | None = None, limit: int = 200
    ) -> list[Identifier]:
        """半截序號搜尋（SPEC-v1 §7.1）：兩邊都正規化後用 LIKE 比對。

        只在 identifiers 裡找；回傳結果帶 item_id 讓呼叫端自己去查商品。
        """
        text = f"%{value.strip()}%"
        normalized = f"%{ids.normalize_identifier(value)}%"
        params: list[Any] = [text, normalized]
        clause = ""
        if kind is not None:
            clause = " AND kind = ?"
            params.append(kind)
        rows = self.conn.execute(
            f"""
            SELECT * FROM identifiers
             WHERE (value LIKE ? OR normalized LIKE ?){clause}
             ORDER BY item_id, kind, value
             LIMIT ?
            """,
            (*params, max(int(limit), 1)),
        ).fetchall()
        return [Identifier.from_row(row) for row in rows]

    def photo_summaries(self, item_ids: list[str]) -> dict[str, dict[str, Any]]:
        """一次查出多件商品的照片數量與代表照片。

        列表頁要顯示縮圖，但 GET /api/items 不含照片欄位；逐筆呼叫詳情會變成
        N+1 次請求，所以這裡一次撈完。代表照片取最早的 original —— 那是進貨
        當下的證據，比後來補拍的更能代表這件商品。
        """
        summaries: dict[str, dict[str, Any]] = {
            item_id: {"photo_count": 0, "thumbnail": None} for item_id in item_ids
        }
        if not item_ids:
            return summaries
        marks = ", ".join("?" for _ in item_ids)
        rows = self.conn.execute(
            f"""
            SELECT s.item_id,
                   s.n AS photo_count,
                   (SELECT p.filename FROM photos p
                     WHERE p.item_id = s.item_id AND p.role = 'original'
                     ORDER BY p.id LIMIT 1) AS thumbnail
              FROM (SELECT item_id, count(*) AS n
                      FROM photos
                     WHERE item_id IN ({marks})
                     GROUP BY item_id) s
            """,  # noqa: S608 — 欄位來自模組常數，項目 id 走參數
            item_ids,
        ).fetchall()
        for row in rows:
            summaries[row["item_id"]] = {
                "photo_count": row["photo_count"],
                "thumbnail": row["thumbnail"],
            }
        return summaries

    def distinct_categories(self) -> list[str]:
        """已用過的分類清單。UI 的篩選下拉選單需要它。"""
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM items"
            " WHERE category <> '' ORDER BY category"
        ).fetchall()
        return [row["category"] for row in rows]

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "items", "observations", "photos", "identifiers", "suggestions", "events"
        ):
            result[table] = self.conn.execute(
                f"SELECT count(*) FROM {table}"  # noqa: S608 — 固定表名
            ).fetchone()[0]
        return result

    def list_recent_events(self, limit: int = 20) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT ?",
            (max(int(limit), 1),),
        ).fetchall()
        return [Event.from_row(row) for row in rows]

    def update_item(
        self, item_id: str, changes: Mapping[str, Any], *, actor: str = "user"
    ) -> Item:
        with db.transaction(self.conn):
            before = self.get_item(item_id)
            cleaned = _actual_changes(
                before,
                _clean_changes(changes, ITEM_EDITABLE_FIELDS, "items", "item"),
            )
            if not cleaned:
                return before
            after = replace(before, **cleaned, updated_at=db.now())
            _validate_item(after)
            _update(self.conn, "items", ITEM_COLUMNS, after, item_id)
            _record(self.conn, "item", item_id, before, cleaned, actor)
            return after

    def void_item(self, item_id: str, *, actor: str = "user") -> Item:
        """軟刪除。SPEC-v1 §2.3：沒有 deleted_at，刪除就是 status='void'。"""
        return self.update_item(item_id, {"status": "void"}, actor=actor)

    # ------------------------------------------------------------------
    # observations
    # ------------------------------------------------------------------

    def add_observation(
        self,
        item_id: str,
        *,
        kind: str = "intake",
        note: str = "",
        captured_at: str | None = None,
        actor: str = "user",
    ) -> Observation:
        """新增一次觀測。

        編號中的日期是「建立當天」，不是 captured_at —— 用者分組匯入時
        常常是補登過去的日期，編號跟著補登日走才不會跟著舊時間跑掉。
        排序要照拍攝時間請用 list_observations()。
        """
        with db.transaction(self.conn):
            self.get_item(item_id)
            observation = Observation(
                id=ids.next_observation_id(self.conn),
                item_id=item_id,
                kind=kind,
                note=note,
                captured_at=captured_at,
                created_at=db.now(),
            )
            _validate_observation(observation)
            _insert(self.conn, "observations", OBSERVATION_COLUMNS, observation)
            events.append(
                self.conn,
                entity_type="observation",
                entity_id=observation.id,
                type="observation.created",
                actor=actor,
                payload=_snapshot(observation),
            )
            return observation

    def get_observation(self, observation_id: str) -> Observation:
        return Observation.from_row(_fetch(self.conn, "observations", observation_id))

    def list_observations(
        self, item_id: str, *, limit: int = 200, offset: int = 0
    ) -> list[Observation]:
        limit, offset = _paging(limit, offset)
        rows = self.conn.execute(
            "SELECT * FROM observations WHERE item_id = ?"
            " ORDER BY COALESCE(captured_at, created_at), id LIMIT ? OFFSET ?",
            (item_id, limit, offset),
        ).fetchall()
        return [Observation.from_row(row) for row in rows]

    def update_observation(
        self, observation_id: str, changes: Mapping[str, Any], *, actor: str = "user"
    ) -> Observation:
        with db.transaction(self.conn):
            before = self.get_observation(observation_id)
            cleaned = _actual_changes(
                before,
                _clean_changes(
                    changes, OBSERVATION_EDITABLE_FIELDS, "observations", "observation"
                ),
            )
            if not cleaned:
                return before
            after = replace(before, **cleaned)
            _validate_observation(after)
            _update(self.conn, "observations", OBSERVATION_COLUMNS, after, observation_id)
            _record(self.conn, "observation", observation_id, before, cleaned, actor)
            return after

    # ------------------------------------------------------------------
    # photos
    # ------------------------------------------------------------------

    def add_photo(
        self,
        item_id: str,
        filename: str,
        *,
        observation_id: str | None = None,
        role: str = "original",
        orig_name: str = "",
        sha256: str = "",
        bytes: int | None = None,
        width: int | None = None,
        height: int | None = None,
        captured_at: str | None = None,
        angle: str = "",
        source: str = "manual",
        actor: str = "user",
    ) -> Photo:
        """寫入照片的 metadata。檔案落盤由階段 3 負責，這裡只記錄。"""
        with db.transaction(self.conn):
            self.get_item(item_id)
            if observation_id is not None:
                observation = self.get_observation(observation_id)
                if observation.item_id != item_id:
                    raise ValidationError(
                        f"observation {observation_id} 屬於 {observation.item_id}，"
                        f"不能掛在 {item_id} 上"
                    )
            photo = Photo(
                id=ids.new_id(),
                item_id=item_id,
                observation_id=observation_id,
                role=role,
                filename=filename,
                orig_name=orig_name,
                sha256=sha256,
                bytes=bytes,
                width=width,
                height=height,
                captured_at=captured_at,
                angle=angle,
                source=source,
                created_at=db.now(),
            )
            _validate_photo(photo)
            _insert(self.conn, "photos", PHOTO_COLUMNS, photo)
            events.append(
                self.conn,
                entity_type="photo",
                entity_id=photo.id,
                type="photo.created",
                actor=actor,
                payload=_snapshot(photo),
            )
            return photo

    def get_photo(self, photo_id: str) -> Photo:
        return Photo.from_row(_fetch(self.conn, "photos", photo_id))

    def list_photos(
        self,
        *,
        item_id: str | None = None,
        observation_id: str | None = None,
        role: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Photo]:
        where, params = _where(
            {"item_id": item_id, "observation_id": observation_id, "role": role}
        )
        limit, offset = _paging(limit, offset)
        rows = self.conn.execute(
            f"SELECT * FROM photos{where} ORDER BY created_at, id LIMIT ? OFFSET ?",  # noqa: S608
            (*params, limit, offset),
        ).fetchall()
        return [Photo.from_row(row) for row in rows]

    def update_photo(
        self, photo_id: str, changes: Mapping[str, Any], *, actor: str = "user"
    ) -> Photo:
        with db.transaction(self.conn):
            before = self.get_photo(photo_id)
            cleaned = _actual_changes(
                before,
                _clean_changes(changes, PHOTO_EDITABLE_FIELDS, "photos", "photo"),
            )
            if not cleaned:
                return before
            after = replace(before, **cleaned)
            _validate_photo(after)
            _update(self.conn, "photos", PHOTO_COLUMNS, after, photo_id)
            _record(self.conn, "photo", photo_id, before, cleaned, actor)
            return after

    def delete_photo(self, photo_id: str, *, actor: str = "user") -> None:
        """只刪衍生照片。原始照片要刪必須先把 role 改成 derived（明確表態）。"""
        with db.transaction(self.conn):
            photo = self.get_photo(photo_id)
            if photo.role != "derived":
                raise ValidationError(
                    f"photos.role='{photo.role}' 不可刪除 —— SPEC-v1 §1 "
                    "原始資料不可破壞。要刪請先把 role 改成 'derived'。"
                )
            self.conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            events.append(
                self.conn,
                entity_type="photo",
                entity_id=photo_id,
                type="photo.deleted",
                actor=actor,
                payload=_snapshot(photo),
            )

    # ------------------------------------------------------------------
    # identifiers
    # ------------------------------------------------------------------

    def add_identifier(
        self,
        item_id: str,
        value: str,
        *,
        kind: str = "serial",
        confidence: float | None = None,
        source: str = "human",
        source_photo_id: str | None = None,
        actor: str = "user",
    ) -> Identifier:
        """建立識別碼。

        刻意沒有全域 UNIQUE：同一組識別碼出現在不同商品上是「自動辨識讀錯」
        的真實訊號，要看得見而不是被資料庫擋掉。撞號請用
        find_identifier_conflicts() 回報給使用者判斷。
        同一商品內的 (kind, value) 重複則是明確的寫入錯誤，丟 ConflictError。
        """
        with db.transaction(self.conn):
            self.get_item(item_id)
            self._check_photo_ref(item_id, source_photo_id)
            identifier = Identifier(
                id=ids.new_id(),
                item_id=item_id,
                kind=kind,
                value=value,
                normalized=ids.normalize_identifier(value),
                confidence=confidence,
                source=source,
                source_photo_id=source_photo_id,
                created_at=db.now(),
                updated_at=db.now(),
            )
            _validate_identifier(identifier)
            self._check_identifier_unique(identifier)
            _insert(self.conn, "identifiers", IDENTIFIER_COLUMNS, identifier)
            events.append(
                self.conn,
                entity_type="identifier",
                entity_id=identifier.id,
                type="identifier.created",
                actor=actor,
                payload=_snapshot(identifier),
            )
            return identifier

    def get_identifier(self, identifier_id: str) -> Identifier:
        return Identifier.from_row(_fetch(self.conn, "identifiers", identifier_id))

    def list_identifiers(
        self, *, item_id: str | None = None, kind: str | None = None
    ) -> list[Identifier]:
        where, params = _where({"item_id": item_id, "kind": kind})
        rows = self.conn.execute(
            f"SELECT * FROM identifiers{where} ORDER BY item_id, created_at, value",  # noqa: S608
            params,
        ).fetchall()
        return [Identifier.from_row(row) for row in rows]

    def update_identifier(
        self, identifier_id: str, changes: Mapping[str, Any], *, actor: str = "user"
    ) -> Identifier:
        with db.transaction(self.conn):
            before = self.get_identifier(identifier_id)
            cleaned = _clean_changes(
                changes, IDENTIFIER_EDITABLE_FIELDS, "identifiers", "identifier"
            )
            if "value" in cleaned:
                # normalized 永遠由 value 推導，不接受外部指定。
                cleaned["normalized"] = ids.normalize_identifier(cleaned["value"])
            cleaned = _actual_changes(before, cleaned)
            if not cleaned:
                return before
            after = replace(before, **cleaned, updated_at=db.now())
            _validate_identifier(after)
            self._check_photo_ref(after.item_id, after.source_photo_id)
            self._check_identifier_unique(after, exclude_id=identifier_id)
            _update(self.conn, "identifiers", IDENTIFIER_COLUMNS, after, identifier_id)
            _record(self.conn, "identifier", identifier_id, before, cleaned, actor)
            return after

    def delete_identifier(self, identifier_id: str, *, actor: str = "user") -> None:
        with db.transaction(self.conn):
            identifier = self.get_identifier(identifier_id)
            self.conn.execute("DELETE FROM identifiers WHERE id = ?", (identifier_id,))
            events.append(
                self.conn,
                entity_type="identifier",
                entity_id=identifier_id,
                type="identifier.deleted",
                actor=actor,
                payload=_snapshot(identifier),
            )

    def find_identifier_conflicts(
        self,
        value: str,
        *,
        kind: str | None = None,
        exclude_item_id: str | None = None,
    ) -> list[Identifier]:
        """其他商品上已存在正規化後相同的識別碼 —— 供 API 回 409 使用。

        這裡是「完全相同」的正規化比對。半截序號的模糊搜尋屬於階段 5。
        """
        sql = ["SELECT * FROM identifiers WHERE normalized = ?"]
        params: list[Any] = [ids.normalize_identifier(value)]
        if kind is not None:
            sql.append("AND kind = ?")
            params.append(kind)
        if exclude_item_id is not None:
            sql.append("AND item_id <> ?")
            params.append(exclude_item_id)
        sql.append("ORDER BY item_id, kind, value")
        rows = self.conn.execute(" ".join(sql), params).fetchall()
        return [Identifier.from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # suggestions
    # ------------------------------------------------------------------

    def add_suggestion(
        self,
        item_id: str,
        field: str,
        value: str,
        *,
        confidence: float | None = None,
        source: str = "external",
        model_name: str = "",
        source_photo_id: str | None = None,
        actor: str = "external",
    ) -> Suggestion:
        """外部工具寫入建議值。主表不受影響，直到有人接受（推論與事實分離）。"""
        with db.transaction(self.conn):
            self.get_item(item_id)
            self._check_photo_ref(item_id, source_photo_id)
            suggestion = Suggestion(
                id=ids.new_id(),
                item_id=item_id,
                field=field,
                value=value,
                confidence=confidence,
                source=source,
                model_name=model_name,
                source_photo_id=source_photo_id,
                status="pending",
                created_at=db.now(),
                decided_at=None,
            )
            _validate_suggestion(suggestion)
            _insert(self.conn, "suggestions", SUGGESTION_COLUMNS, suggestion)
            events.append(
                self.conn,
                entity_type="suggestion",
                entity_id=suggestion.id,
                type="suggestion.created",
                actor=actor,
                payload=_snapshot(suggestion),
            )
            return suggestion

    def get_suggestion(self, suggestion_id: str) -> Suggestion:
        return Suggestion.from_row(_fetch(self.conn, "suggestions", suggestion_id))

    def list_suggestions(
        self,
        *,
        item_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Suggestion]:
        where, params = _where({"item_id": item_id, "status": status})
        limit, offset = _paging(limit, offset)
        rows = self.conn.execute(
            f"SELECT * FROM suggestions{where}"  # noqa: S608
            " ORDER BY created_at, id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [Suggestion.from_row(row) for row in rows]

    def update_suggestion(
        self, suggestion_id: str, changes: Mapping[str, Any], *, actor: str = "user"
    ) -> Suggestion:
        """只允許改尚未決定的建議。已接受/拒絕的建議是歷史，不該被覆寫。"""
        with db.transaction(self.conn):
            before = self.get_suggestion(suggestion_id)
            _require_pending(before)
            cleaned = _actual_changes(
                before,
                _clean_changes(
                    changes, SUGGESTION_EDITABLE_FIELDS, "suggestions", "suggestion"
                ),
            )
            if not cleaned:
                return before
            after = replace(before, **cleaned)
            _validate_suggestion(after)
            self._check_photo_ref(after.item_id, after.source_photo_id)
            _update(self.conn, "suggestions", SUGGESTION_COLUMNS, after, suggestion_id)
            _record(self.conn, "suggestion", suggestion_id, before, cleaned, actor)
            return after

    def accept_suggestion(
        self, suggestion_id: str, *, actor: str = "user"
    ) -> Suggestion:
        """接受建議：值正式寫入主表。

        field 是一般欄位 → 更新 items；
        field 是 identifier:<kind> → 另建 identifiers，帶上 confidence、
        source='accepted_suggestion' 與來源照片（SPEC-v1 §5）。
        """
        with db.transaction(self.conn):
            before = self.get_suggestion(suggestion_id)
            _require_pending(before)
            after = replace(before, status="accepted", decided_at=db.now())
            _validate_suggestion(after)

            if after.identifier_kind is not None:
                self.add_identifier(
                    after.item_id,
                    after.value,
                    kind=after.identifier_kind,
                    confidence=after.confidence,
                    source="accepted_suggestion",
                    source_photo_id=after.source_photo_id,
                    actor=actor,
                )
            else:
                self.update_item(after.item_id, {after.field: after.value}, actor=actor)

            _update(self.conn, "suggestions", SUGGESTION_COLUMNS, after, suggestion_id)
            events.append(
                self.conn,
                entity_type="suggestion",
                entity_id=suggestion_id,
                type="suggestion.accepted",
                actor=actor,
                field=after.field,
                prev_value=before.value,
                next_value=after.value,
                payload={
                    "confidence": after.confidence,
                    "model_name": after.model_name,
                    "source_photo_id": after.source_photo_id,
                    "created_identifier": after.identifier_kind is not None,
                },
            )
            return after

    def reject_suggestion(
        self, suggestion_id: str, *, actor: str = "user"
    ) -> Suggestion:
        """拒絕建議。被拒的建議保留（SPEC-v1 §1：推論與事實分離）。"""
        with db.transaction(self.conn):
            before = self.get_suggestion(suggestion_id)
            _require_pending(before)
            after = replace(before, status="rejected", decided_at=db.now())
            _update(self.conn, "suggestions", SUGGESTION_COLUMNS, after, suggestion_id)
            events.append(
                self.conn,
                entity_type="suggestion",
                entity_id=suggestion_id,
                type="suggestion.rejected",
                actor=actor,
                field=after.field,
                prev_value=before.value,
                next_value=after.value,
            )
            return after

    def find_photos_by_sha256(
        self, sha256: str, *, item_id: str | None = None, role: str | None = None
    ) -> list[Photo]:
        """以內容雜湊找照片。

        階段 3 用它做 sha256 去重：同一件商品不該有兩份同樣位元組的原始照片，
        而別的商品有同樣位元組時不該搶走對方的證據，只回報讓人判斷。
        """
        where, params = _where({"sha256": sha256, "item_id": item_id, "role": role})
        rows = self.conn.execute(
            f"SELECT * FROM photos{where} ORDER BY created_at, id",  # noqa: S608
            params,
        ).fetchall()
        return [Photo.from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def list_events(
        self, entity_type: str, entity_id: str, *, limit: int = 200
    ) -> list[Event]:
        rows = events.history(self.conn, entity_type, entity_id, limit)
        return [Event.from_row(row) for row in rows]

    def item_history(self, item_id: str, *, limit: int = 500) -> list[Event]:
        """商品的全部歷史：商品本身 + 四張子表的變更，最新在前。

        已刪除的子項（例如刪掉 identifier）已經不在子表裡了，但它的刪除事件
        帶著 payload.item_id，所以用 json_extract 補回來 —— 否則「刪了什麼」
        會從歷史裡消失，跟可觀測的原則相反。
        """
        self.get_item(item_id)
        rows = self.conn.execute(
            """
            SELECT * FROM events
             WHERE (entity_type = 'item'        AND entity_id = :id)
                OR (entity_type = 'observation' AND entity_id IN
                        (SELECT id FROM observations WHERE item_id = :id))
                OR (entity_type = 'photo'       AND entity_id IN
                        (SELECT id FROM photos WHERE item_id = :id))
                OR (entity_type = 'identifier'  AND entity_id IN
                        (SELECT id FROM identifiers WHERE item_id = :id))
                OR (entity_type = 'suggestion'  AND entity_id IN
                        (SELECT id FROM suggestions WHERE item_id = :id))
                OR json_extract(payload, '$.item_id') = :id
             ORDER BY created_at DESC, id DESC
             LIMIT :limit
            """,
            {"id": item_id, "limit": max(int(limit), 1)},
        ).fetchall()
        return [Event.from_row(row) for row in rows]

    def revert_event(self, event_id: str, *, actor: str = "user") -> Entity:
        """把單一欄位還原，並把這次還原本身也記成一筆 field.changed。

        復原不是「刪掉那筆事件」—— 那會讓按第二次又還原回去，歷史也不誠實。
        """
        with db.transaction(self.conn):
            exists = self.conn.execute(
                "SELECT 1 FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"events 找不到 id={event_id}")
            target = events.revert(self.conn, event_id)
            if target is None:
                raise ValidationError(
                    "只有 field.changed 事件可復原（需同時有 field 與 prev_value）"
                )
            entity_type, entity_id, field, value = target
            if entity_type not in _REVERT_TARGETS:
                raise ValidationError(f"不支援還原 {entity_type} 的變更")
            method_name, allowed = _REVERT_TARGETS[entity_type]
            if field not in allowed:
                raise ValidationError(f"{entity_type}.{field} 不可透過事件還原")
            return getattr(self, method_name)(entity_id, {field: value}, actor=actor)

    # ------------------------------------------------------------------
    # templates
    # ------------------------------------------------------------------

    def add_template(
        self,
        name: str,
        html: str,
        *,
        width: float | None = None,
        height: float | None = None,
        unit: str | None = None,
        actor: str = "user",
    ) -> Template:
        """建立 Template。"""
        with db.transaction(self.conn):
            stamp = db.now()
            template = Template(
                id=ids.next_template_id(self.conn),
                name=name,
                html=html,
                width=width,
                height=height,
                unit=unit,
                created_at=stamp,
                updated_at=stamp,
            )
            _validate_template(template)
            _insert(self.conn, "templates", TEMPLATE_COLUMNS, template)
            events.append(
                self.conn,
                entity_type="template",
                entity_id=template.id,
                type="template.created",
                actor=actor,
                payload=_snapshot(template),
            )
            return template

    def get_template(self, template_id: str) -> Template:
        return Template.from_row(_fetch(self.conn, "templates", template_id))

    def list_templates(
        self, *, limit: int = 200, offset: int = 0
    ) -> list[Template]:
        limit, offset = _paging(limit, offset)
        rows = self.conn.execute(
            "SELECT * FROM templates ORDER BY name, id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [Template.from_row(row) for row in rows]

    def update_template(
        self,
        template_id: str,
        *,
        name: str | None = None,
        html: str | None = None,
        width: float | None = None,
        height: float | None = None,
        unit: str | None = None,
        actor: str = "user",
    ) -> Template:
        """更新 Template。需重新驗證。"""
        with db.transaction(self.conn):
            before = self.get_template(template_id)
            changes = {}
            if name is not None:
                changes["name"] = name
            if html is not None:
                changes["html"] = html
            if width is not None:
                changes["width"] = width
            if height is not None:
                changes["height"] = height
            if unit is not None:
                changes["unit"] = unit
            if not changes:
                return before
            after = replace(before, **changes, updated_at=db.now())
            _validate_template(after)
            _update(self.conn, "templates", TEMPLATE_COLUMNS, after, template_id)
            events.append(
                self.conn,
                entity_type="template",
                entity_id=template_id,
                type="template.updated",
                actor=actor,
                payload=_snapshot(after),
            )
            return after

    def delete_template(self, template_id: str, *, actor: str = "user") -> None:
        """刪除 Template。不影響任何 Item。"""
        with db.transaction(self.conn):
            template = self.get_template(template_id)
            self.conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            events.append(
                self.conn,
                entity_type="template",
                entity_id=template_id,
                type="template.deleted",
                actor=actor,
                payload=_snapshot(template),
            )

    # ------------------------------------------------------------------
    # 內部檢查
    # ------------------------------------------------------------------

    def _check_photo_ref(self, item_id: str, photo_id: str | None) -> None:
        """來源照片必須存在，而且是同一件商品的照片。

        否則「序號旁顯示來源照片」會指向別人的商品，來源追溯就說謊了。
        """
        if photo_id is None:
            return
        photo = self.get_photo(photo_id)
        if photo.item_id != item_id:
            raise ValidationError(
                f"photo {photo_id} 屬於 {photo.item_id}，不能當作 {item_id} 的來源照片"
            )

    def _check_identifier_unique(
        self, identifier: Identifier, *, exclude_id: str | None = None
    ) -> None:
        row = self.conn.execute(
            "SELECT id FROM identifiers"
            " WHERE item_id = ? AND kind = ? AND value = ? AND id <> ?",
            (
                identifier.item_id,
                identifier.kind,
                identifier.value,
                exclude_id or "",
            ),
        ).fetchone()
        if row is not None:
            raise ConflictError(
                f"商品 {identifier.item_id} 已有相同的 {identifier.kind}"
                f"「{identifier.value}」（{row['id']}）"
            )


# ----------------------------------------------------------------------
# 模組層級輔助
# ----------------------------------------------------------------------


def _insert(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...], row: Any
) -> None:
    values = _values(row, columns, table)
    marks = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})",  # noqa: S608 — 欄位來自模組常數
        tuple(values[column] for column in columns),
    )


def _update(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...], row: Any, row_id: str
) -> None:
    values = _values(row, columns, table)
    assignments = ", ".join(f"{column} = ?" for column in columns if column != "id")
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?",  # noqa: S608 — 欄位來自模組常數
        (*(values[column] for column in columns if column != "id"), row_id),
    )


def _values(row: Any, columns: tuple[str, ...], table: str) -> dict[str, Any]:
    values = {column: getattr(row, column) for column in columns}
    for json_field in _JSON_FIELDS.get(table, ()):
        values[json_field] = dumps_object(values[json_field])
    return values


def _fetch(conn: sqlite3.Connection, table: str, row_id: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()  # noqa: S608
    if row is None:
        raise NotFoundError(f"{table} 找不到 id={row_id}")
    return row


def _where(filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
    clauses = [f"{name} = ?" for name, value in filters.items() if value is not None]
    params = [value for value in filters.values() if value is not None]
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _paging(limit: int, offset: int) -> tuple[int, int]:
    limit, offset = int(limit), int(offset)
    if limit < 1:
        raise ValidationError(f"limit 必須 >= 1，得到 {limit}")
    if offset < 0:
        raise ValidationError(f"offset 必須 >= 0，得到 {offset}")
    return limit, offset


def _coerce(table: str, name: str, value: Any) -> Any:
    """把外部傳來的值轉成資料表宣告的型別（STRICT 表不接受型別不符）。"""
    coercer = _COERCERS.get(table, {}).get(name)
    if coercer is None or value is None:
        return value
    try:
        return coercer(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{table}.{name} 的值無法轉換：{value!r}") from exc


def _clean_changes(
    changes: Mapping[str, Any],
    allowed: tuple[str, ...],
    table: str,
    entity: str,
) -> dict[str, Any]:
    """擋掉不認識的欄位，並把型別轉成資料表宣告的型別。"""
    unknown = sorted(set(changes) - set(allowed))
    if unknown:
        raise ValidationError(
            f"{entity} 不可修改欄位 {', '.join(unknown)}；"
            f"可用欄位：{', '.join(allowed)}"
        )
    return {name: _coerce(table, name, value) for name, value in changes.items()}


def _actual_changes(before: Any, cleaned: Mapping[str, Any]) -> dict[str, Any]:
    """去掉值沒變的欄位，避免 updated_at 被無意義地推進、歷史被雜訊淹沒。"""
    return {
        name: value
        for name, value in cleaned.items()
        if value != getattr(before, name)
    }


def _record(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    before: Any,
    cleaned: Mapping[str, Any],
    actor: str,
) -> None:
    for name, value in cleaned.items():
        events.record_field_change(
            conn,
            entity_type=entity_type,
            entity_id=entity_id,
            field=name,
            before=getattr(before, name),
            after=value,
            actor=actor,
        )


def _snapshot(row: Any) -> dict[str, Any]:
    return asdict(row)


def _require_pending(suggestion: Suggestion) -> None:
    if suggestion.status != "pending":
        raise ValidationError(
            f"suggestion {suggestion.id} 已是 {suggestion.status}，"
            "建議一經決定就是歷史，不能再改"
        )


# ----------------------------------------------------------------------
# 欄位驗證（DDL 的 CHECK 是最後一道防線，這裡先擋一次以求錯誤訊息可讀）
# ----------------------------------------------------------------------


def _check_choice(field: str, value: Any, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValidationError(
            f"{field} 必須是 {', '.join(allowed)} 之一，得到 {value!r}"
        )


def _check_required(field: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} 不可為空")


def _check_confidence(value: float | None) -> None:
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"confidence 必須是 0..1 的數值，得到 {value!r}") from exc
    if not 0.0 <= number <= 1.0:
        raise ValidationError(f"confidence 必須在 0..1 之間，得到 {value!r}")


def _check_relative_path(filename: str) -> None:
    """SPEC-v1 §3：資料庫只存相對於 DATA_ROOT 的路徑。

    絕對路徑會綁死在某一台機器上，整份資料夾搬不動，所以擋在寫入邊界。
    """
    _check_required("photos.filename", filename)
    if PurePosixPath(filename).is_absolute() or Path(filename).is_absolute():
        raise ValidationError(f"photos.filename 必須是相對路徑，得到 {filename!r}")
    if ".." in PurePosixPath(filename).parts:
        raise ValidationError(f"photos.filename 不可離開資料根目錄，得到 {filename!r}")
    if "\\" in filename:
        raise ValidationError(
            f"photos.filename 一律用 / 分隔，得到 {filename!r}"
        )


def _validate_item(item: Item) -> None:
    _check_choice("items.status", item.status, ITEM_STATUSES)
    if int(item.quantity) < 1:
        raise ValidationError(f"items.quantity 必須 >= 1，得到 {item.quantity}")


def _validate_observation(observation: Observation) -> None:
    _check_choice("observations.kind", observation.kind, OBSERVATION_KINDS)


def _validate_photo(photo: Photo) -> None:
    _check_choice("photos.role", photo.role, PHOTO_ROLES)
    _check_relative_path(photo.filename)


def _validate_identifier(identifier: Identifier) -> None:
    _check_choice("identifiers.kind", identifier.kind, IDENTIFIER_KINDS)
    _check_choice("identifiers.source", identifier.source, IDENTIFIER_SOURCES)
    _check_required("identifiers.value", identifier.value)
    _check_confidence(identifier.confidence)
    if not identifier.normalized:
        raise ValidationError(
            f"identifiers.value「{identifier.value}」去掉分隔符號後為空，"
            "這樣的識別碼永遠搜尋不到，請確認有真正打進去"
        )


def _validate_suggestion(suggestion: Suggestion) -> None:
    _check_choice("suggestions.status", suggestion.status, SUGGESTION_STATUSES)
    _check_required("suggestions.value", suggestion.value)
    _check_confidence(suggestion.confidence)
    field = suggestion.field
    kind = (
        field[len(IDENTIFIER_FIELD_PREFIX):]
        if field.startswith(IDENTIFIER_FIELD_PREFIX)
        else None
    )
    if kind is not None:
        _check_choice("suggestions.field", kind, IDENTIFIER_KINDS)
    elif field not in SUGGESTABLE_FIELDS:
        raise ValidationError(
            f"suggestions.field 必須是 {', '.join(SUGGESTABLE_FIELDS)}"
            f" 或 {IDENTIFIER_FIELD_PREFIX}<kind>（{', '.join(IDENTIFIER_KINDS)}），"
            f"得到 {field!r}"
        )


def _validate_template(template: Template) -> None:
    """驗證 Template 基本欄位。"""
    _check_required("templates.name", template.name)
    _check_required("templates.html", template.html)
    if template.width is not None and template.width <= 0:
        raise ValidationError(f"templates.width 必須 > 0，得到 {template.width}")
    if template.height is not None and template.height <= 0:
        raise ValidationError(f"templates.height 必須 > 0，得到 {template.height}")
