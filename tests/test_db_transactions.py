"""交易邊界：資料與 events 不可能只寫進一半。"""

from __future__ import annotations

import pytest

from shop import db as db_mod
from shop.errors import ValidationError


def _counts(conn) -> tuple[int, int]:
    items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    return items, events


def test_transaction_commits_on_success(config):
    with db_mod.session(config) as conn:
        with db_mod.transaction(conn):
            conn.execute(
                "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                ("ITM-0001", db_mod.now(), db_mod.now()),
            )
        assert _counts(conn) == (1, 0)


def test_transaction_rolls_back_on_error(config):
    with db_mod.session(config) as conn:
        with pytest.raises(RuntimeError):
            with db_mod.transaction(conn):
                conn.execute(
                    "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                    ("ITM-0001", db_mod.now(), db_mod.now()),
                )
                raise RuntimeError("boom")
        assert _counts(conn) == (0, 0)
        assert conn.in_transaction is False


def test_nested_transaction_joins_the_outer_one(config):
    with db_mod.session(config) as conn:
        with db_mod.transaction(conn):
            with db_mod.transaction(conn):
                conn.execute(
                    "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                    ("ITM-0001", db_mod.now(), db_mod.now()),
                )
                # 內層結束不應該 COMMIT
                assert conn.in_transaction is True
        assert _counts(conn) == (1, 0)


def test_item_created_but_event_failed_leaves_nothing(config, monkeypatch):
    """寫入順序被破壞時，資料也不能單獨存在。"""
    from shop import events as events_module
    from shop.repo import Repository

    def broken(*args, **kwargs):
        raise RuntimeError("events 寫不進去")

    monkeypatch.setattr(events_module, "append", broken)
    with db_mod.session(config) as conn:
        with pytest.raises(RuntimeError):
            Repository(conn, config).create_item(name="主機板")
        assert _counts(conn) == (0, 0)


def test_repo_uses_a_single_transaction_per_write(repo):
    before = repo.conn.in_transaction
    item = repo.create_item(name="主機板")
    assert before is False
    assert repo.conn.in_transaction is False
    assert item.id == "ITM-0001"


def test_failed_identifier_leaves_no_identifier_event(repo):
    item = repo.create_item()
    repo.add_identifier(item.id, "6LWMF1234567")
    assert repo.conn.execute(
        "SELECT count(*) FROM events WHERE entity_type = 'identifier'"
    ).fetchone()[0] == 1

    with pytest.raises(Exception):
        repo.add_identifier(item.id, "6LWMF1234567")

    assert repo.conn.execute(
        "SELECT count(*) FROM events WHERE entity_type = 'identifier'"
    ).fetchone()[0] == 1


def test_update_failure_keeps_updated_at_untouched(repo):
    item = repo.create_item(quantity=1)
    with pytest.raises(ValidationError):
        repo.update_item(item.id, {"quantity": 0})
    assert repo.get_item(item.id).updated_at == item.updated_at
    assert repo.get_item(item.id).quantity == 1
