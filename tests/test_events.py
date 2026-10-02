"""events 寫入與復原的行為（SPEC-v1 §1「一切有來源」、§4.3）。"""

from __future__ import annotations

import json

import pytest

from shop import db as db_mod
from shop import events as events_mod
from shop import ids as ids_mod


def _event_id(conn, **kwargs) -> str:
    return events_mod.append(conn, **kwargs)


def test_append_rejects_unknown_entity_type(config):
    with db_mod.session(config) as conn:
        with pytest.raises(ValueError):
            _event_id(conn, entity_type="sale", entity_id="X1", type="sale.created")


def test_append_rejects_unknown_actor(config):
    with db_mod.session(config) as conn:
        with pytest.raises(ValueError):
            _event_id(
                conn,
                entity_type="item",
                entity_id="ITM-0001",
                type="item.created",
                actor="robot",
            )


def test_values_are_json_encoded(config):
    with db_mod.session(config) as conn:
        event_id = _event_id(
            conn,
            entity_type="item",
            entity_id="ITM-0001",
            type="item.created",
            field="notes",
            prev_value=None,
            next_value="多行\n文字 \"引號\" 與中文",
            payload={"來源": "外部 OCR"},
        )
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        # prev_value 是 NULL（還沒有的東西），next_value 是 JSON 字串
        assert row["prev_value"] is None
        assert json.loads(row["next_value"]) == "多行\n文字 \"引號\" 與中文"
        assert json.loads(row["payload"]) == {"來源": "外部 OCR"}


def test_field_change_suppressed_when_value_unchanged(config):
    with db_mod.session(config) as conn:
        assert (
            events_mod.record_field_change(
                conn,
                entity_type="item",
                entity_id="ITM-0001",
                field="brand",
                before="ASUS",
                after="ASUS",
            )
            is None
        )
        assert (
            events_mod.record_field_change(
                conn,
                entity_type="item",
                entity_id="ITM-0001",
                field="brand",
                before="ASUS",
                after="acer",
            )
            is not None
        )
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_history_is_newest_first_and_decoded(config):
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0001", "2026-10-02T10:00:00", "2026-10-02T10:00:00"),
        )
        for brand in ("ASUS", "acer", "MSI"):
            events_mod.record_field_change(
                conn,
                entity_type="item",
                entity_id="ITM-0001",
                field="brand",
                before=brand,
                after=brand + " ",
            )
        rows = events_mod.history(conn, "item", "ITM-0001")
        assert [row["next_value"] for row in rows] == ["MSI ", "acer ", "ASUS "]
        assert rows[0]["prev_value"] == "MSI"


def test_history_respects_limit(config):
    with db_mod.session(config) as conn:
        for index in range(5):
            _event_id(
                conn,
                entity_type="item",
                entity_id="ITM-0001",
                type="item.created",
                payload={"index": index},
            )
        assert len(events_mod.history(conn, "item", "ITM-0001", limit=2)) == 2


def test_revert_returns_entity_field_and_prev_value(config):
    with db_mod.session(config) as conn:
        event_id = events_mod.record_field_change(
            conn,
            entity_type="identifier",
            entity_id=ids_mod.new_id(),
            field="value",
            before="BX-80706",
            after="BX-80706X",
        )
        entity_type, entity_id, field, value = events_mod.revert(conn, event_id)
        assert entity_type == "identifier"
        assert field == "value"
        assert value == "BX-80706"


def test_revert_refuses_non_field_events(config):
    with db_mod.session(config) as conn:
        event_id = _event_id(
            conn, entity_type="item", entity_id="ITM-0001", type="item.created"
        )
        assert events_mod.revert(conn, event_id) is None
        assert events_mod.revert(conn, "NOPE") is None


def test_revert_refuses_field_change_without_prev_value(config):
    """把欄位從有值清成空值時 prev_value 仍要有值，否則無從還原。"""
    with db_mod.session(config) as conn:
        event_id = _event_id(
            conn,
            entity_type="item",
            entity_id="ITM-0001",
            type="field.changed",
            field="notes",
            next_value="",
        )
        assert events_mod.revert(conn, event_id) is None
