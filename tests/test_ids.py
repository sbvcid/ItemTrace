"""ID 產生與序號正規化（SPEC-v1 §14.1、§7.1）。"""

from __future__ import annotations

import re
import sqlite3

import pytest

from shop import db as db_mod
from shop import ids as ids_mod
from shop.ids import (
    ITEM_WIDTH,
    next_item_id,
    next_observation_id,
    new_id,
    normalize_identifier,
    now_ulid,
)

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_ulid_is_26_chars_crockford_base32():
    assert ULID_RE.match(now_ulid())
    assert ULID_RE.match(new_id())


def test_ulid_is_time_ordered():
    """時間有序是選它的唯一理由：事件排序要穩定。"""
    first = now_ulid()
    second = now_ulid()
    assert first < second


def test_ulid_stays_ordered_within_one_millisecond():
    """同一毫秒內不能靠亂數決定順序，events 的歷史順序會失真。"""
    batch = [now_ulid() for _ in range(500)]
    assert batch == sorted(batch)
    assert len(set(batch)) == len(batch)


def test_ulid_survives_clock_going_backwards(monkeypatch):
    ids_mod._LAST_MS = 0
    ids_mod._LAST_RAND = 0
    before = now_ulid()
    monkeypatch.setattr(ids_mod.time, "time", lambda: 0.0)  # 時鐘往回 10 秒
    assert now_ulid() > before


def test_new_id_is_unique():
    assert len({new_id() for _ in range(2000)}) == 2000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # SPEC-v1 §7.1 實測表
        ("BX-807 06_1234", "BX807061234"),
        ("6LWMF1234567", "6LWMF1234567"),
        # 搜尋端也要能正規化
        ("807061234", "807061234"),
        ("6lwmf", "6LWMF"),
        ("", ""),
    ],
)
def test_normalize_identifier(raw, expected):
    assert normalize_identifier(raw) == expected


def test_normalize_identifier_keeps_alnum_only():
    raw = "a-b_c d/e\\f.g,h;i:j'k\"l(m)n[o]p<q>r+s*t&u^v$w%x#y@z!"
    assert normalize_identifier(raw) == "".join(chr(ord("A") + i) for i in range(26))


def test_next_item_id_increments(config):
    with db_mod.session(config) as conn:
        assert next_item_id(conn, config) == f"ITM-{1:0{ITEM_WIDTH}d}"
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0001", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        assert next_item_id(conn, config) == "ITM-0002"
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0042", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        assert next_item_id(conn, config) == "ITM-0043"


def test_next_item_id_ignores_other_rows(config):
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("legacy-0007", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        assert next_item_id(conn, config) == "ITM-0001"


def test_next_item_id_increments_past_four_digits(config):
    """字串排序會讓 'ITM-10000' < 'ITM-9999'，發號在破萬後錯亂。"""
    with db_mod.session(config) as conn:
        stamp = "2026-10-02T00:00:00"
        for existing in ("ITM-9999", "ITM-10000"):
            conn.execute(
                "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                (existing, stamp, stamp),
            )
        assert next_item_id(conn, config) == "ITM-10001"


def test_next_item_id_pads_but_does_not_truncate(config):
    with db_mod.session(config) as conn:
        stamp = "2026-10-02T00:00:00"
        assert next_item_id(conn, config) == "ITM-0001"
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0009", stamp, stamp),
        )
        assert next_item_id(conn, config) == "ITM-0010"


def test_next_item_id_ignores_non_numeric_tails(config):
    """手動輸入過的 id 不該參與發號計算。"""
    with db_mod.session(config) as conn:
        stamp = "2026-10-02T00:00:00"
        for odd in ("ITM-0001-old", "ITM-legacy", "ITM-00X1"):
            conn.execute(
                "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                (odd, stamp, stamp),
            )
        assert next_item_id(conn, config) == "ITM-0001"


def test_next_observation_id_also_increments_numerically(config):
    """同一個字串排序陷阱：當天超過 99 筆觀測時。"""
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0001", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        for existing in ("OBS-20261002-99", "OBS-20261002-100"):
            conn.execute(
                "INSERT INTO observations (id, item_id, created_at) VALUES (?,?,?)",
                (existing, "ITM-0001", "2026-10-02T00:00:00"),
            )
        assert next_observation_id(conn, "2026-10-02") == "OBS-20261002-101"


def test_next_observation_id_is_per_day(config):
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0001", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        assert next_observation_id(conn, "2026-10-02") == "OBS-20261002-01"
        conn.execute(
            "INSERT INTO observations (id, item_id, created_at)"
            " VALUES (?,?,?)",
            ("OBS-20261002-01", "ITM-0001", "2026-10-02T00:00:00"),
        )
        assert next_observation_id(conn, "2026-10-02") == "OBS-20261002-02"
        # 換一天重新從 01 開始
        assert next_observation_id(conn, "2026-10-03") == "OBS-20261003-01"
        assert next_observation_id(conn, "2026-10-03T12:00:00") == "OBS-20261003-01"


def test_next_item_id_does_not_reuse_soft_deleted(config):
    """void 是軟刪除，編號不回收 —— 舊資料夾與事件永遠對得上。"""
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, status, created_at, updated_at) VALUES (?,?,?,?)",
            ("ITM-0001", "void", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        assert next_item_id(conn, config) == "ITM-0002"


def test_ids_are_primary_keys_so_bad_rows_are_rejected(config):
    with db_mod.session(config) as conn:
        conn.execute(
            "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
            ("ITM-0001", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO items (id, created_at, updated_at) VALUES (?,?,?)",
                ("ITM-0001", "2026-10-02T00:00:00", "2026-10-02T00:00:00"),
            )
