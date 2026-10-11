-- 商品證據與歸檔工具 schema（SPEC-v1 §2.2）
-- 已於 SQLite 3.49.1 實測可執行

CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    condition   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    attributes  TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','archived','void')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS observations (
    id          TEXT PRIMARY KEY,
    item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    kind        TEXT NOT NULL DEFAULT 'intake'
                CHECK (kind IN ('intake','recheck','manual')),
    note        TEXT NOT NULL DEFAULT '',
    captured_at TEXT,
    created_at  TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS idx_obs_item ON observations(item_id, captured_at);

CREATE TABLE IF NOT EXISTS photos (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    observation_id  TEXT REFERENCES observations(id) ON DELETE SET NULL,
    role            TEXT NOT NULL DEFAULT 'original'
                    CHECK (role IN ('original','derived')),
    filename        TEXT NOT NULL,
    orig_name       TEXT NOT NULL DEFAULT '',
    sha256          TEXT NOT NULL DEFAULT '',
    bytes           INTEGER,
    width           INTEGER,
    height          INTEGER,
    captured_at     TEXT,
    angle           TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'manual',
    created_at      TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS idx_photos_item ON photos(item_id);
CREATE INDEX IF NOT EXISTS idx_photos_obs  ON photos(observation_id);
CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(sha256);

-- 刻意不設全域 UNIQUE，只約束同一 item 內不重複。
-- 自動辨識讀錯序號時，硬約束會讓寫入直接失敗，使用者就看不到這個錯誤。
-- 撞號改由 API 回報 409，由人判斷是打錯、拍重複，還是同一件。
CREATE TABLE IF NOT EXISTS identifiers (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    kind             TEXT NOT NULL DEFAULT 'serial'
                     CHECK (kind IN ('serial','imei','barcode','custom')),
    value            TEXT NOT NULL,
    normalized       TEXT NOT NULL,
    confidence       REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source           TEXT NOT NULL DEFAULT 'human'
                     CHECK (source IN ('human','accepted_suggestion')),
    source_photo_id  TEXT REFERENCES photos(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (item_id, kind, value)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_ident_norm ON identifiers(normalized);

CREATE TABLE IF NOT EXISTS suggestions (
    id               TEXT PRIMARY KEY,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    field            TEXT NOT NULL,
    value            TEXT NOT NULL,
    confidence       REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source           TEXT NOT NULL DEFAULT 'external',
    model_name       TEXT NOT NULL DEFAULT '',
    source_photo_id  TEXT REFERENCES photos(id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','accepted','rejected','superseded')),
    created_at       TEXT NOT NULL,
    decided_at       TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS idx_sugg_item ON suggestions(item_id, status);

CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'user'
                CHECK (actor IN ('user','external','system')),
    field       TEXT,
    prev_value  TEXT,
    next_value  TEXT,
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_time   ON events(created_at);

CREATE TABLE IF NOT EXISTS templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    html        TEXT NOT NULL,
    width       REAL,
    height      REAL,
    unit        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS idx_templates_name ON templates(name);

-- 已配對的手機／區網裝置（手機免設定檔配對）。
-- 只存裝置權杖的 SHA-256 雜湊；權杖原文只在配對成功當下回給手機一次。
CREATE TABLE IF NOT EXISTS paired_devices (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    token_hash      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT,
    revoked_at      TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS idx_paired_token   ON paired_devices(token_hash);
CREATE INDEX IF NOT EXISTS idx_paired_revoked ON paired_devices(revoked_at);

-- 短效、一次性的配對工作階段（見 shop/pairing.py 的流程說明）。
-- code 是 6 位數字（一次性），attempts 記錄錯誤嘗試次數，達到上限即失效。
CREATE TABLE IF NOT EXISTS pairing_sessions (
    id                TEXT PRIMARY KEY,
    code              TEXT NOT NULL,
    pairing_url       TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0,
    claimed_at        TEXT,
    claimed_device_id TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS idx_pairing_expires ON pairing_sessions(expires_at);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;