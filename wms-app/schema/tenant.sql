-- =====================================================================
-- WMS-app -- tenant schema (one copy per company, in data/tenants/<slug>.db)
-- =====================================================================
--
-- transactions is the operational log: every receive/putaway/pick/pack/ship/
-- adjust/count is a row here, and it is also the raw material the IHA
-- analysis pipeline (see analysis_bridge.py) consumes in place of an
-- uploaded sales/inbound file. Never delete rows from it -- the analysis
-- and the audit trail both depend on full history.
--
-- Written in the SQLite/PostgreSQL intersection (CHECK instead of enums,
-- ISO-8601 TEXT dates, INTEGER 0/1 for booleans) -- see CLAUDE.md.
-- =====================================================================

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS items (
    sku             TEXT PRIMARY KEY,
    barcode         TEXT UNIQUE,
    description     TEXT,
    unit_cost       REAL,
    currency        TEXT NOT NULL DEFAULT 'SEK',
    supplier        TEXT,
    category        TEXT,
    lead_time_days  INTEGER,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    code            TEXT PRIMARY KEY,          -- e.g. A-01-03
    zone            TEXT,
    location_type   TEXT NOT NULL DEFAULT 'bulk'
                        CHECK (location_type IN ('receiving', 'picking', 'bulk'))
);

CREATE TABLE IF NOT EXISTS stock (
    sku             TEXT NOT NULL REFERENCES items(sku),
    location_code   TEXT NOT NULL REFERENCES locations(code),
    qty             REAL NOT NULL DEFAULT 0 CHECK (qty >= 0),
    PRIMARY KEY (sku, location_code)
);

CREATE INDEX IF NOT EXISTS ix_stock_sku ON stock (sku);

-- Sparse-by-nature: a row is written for every movement, never edited in
-- place. current stock balances are derived from this + the stock table
-- being kept in sync at write time (see db.py transaction helpers).
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_type        TEXT NOT NULL CHECK (txn_type IN
                        ('receive', 'putaway', 'pick', 'pack', 'ship', 'adjust', 'count')),
    sku             TEXT NOT NULL REFERENCES items(sku),
    qty             REAL NOT NULL,
    from_location   TEXT,
    to_location     TEXT,
    reference       TEXT,                       -- order_no / PO number
    user_email      TEXT,
    created_at      TEXT NOT NULL,               -- ISO-8601
    -- Nullable, only meaningful for txn_type='receive'. Added 2026-09-21
    -- for docs/FORECAST_SPEC.md Phase 5: real lead time is receipt date
    -- minus order date, and created_at only ever records the receipt.
    -- Existing tenant databases get these via db._migrate_tenant_db()
    -- (idempotent ALTER, runs on every get_tenant_conn()) since this
    -- CREATE TABLE only applies to brand-new tenants -- keep the two in
    -- sync if either changes.
    po_date         TEXT,                       -- when the goods were ordered
    expected_date   TEXT                         -- promised/expected receipt date
);

CREATE INDEX IF NOT EXISTS ix_txn_sku      ON transactions (sku);
CREATE INDEX IF NOT EXISTS ix_txn_type     ON transactions (txn_type);
CREATE INDEX IF NOT EXISTS ix_txn_created  ON transactions (created_at);

CREATE TABLE IF NOT EXISTS orders (
    order_no        TEXT PRIMARY KEY,            -- free text, user- or ERP-assigned
    order_type      TEXT NOT NULL CHECK (order_type IN ('inbound', 'outbound')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN
                        ('open', 'picking', 'packed', 'shipped', 'received', 'cancelled')),
    reference       TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_no        TEXT NOT NULL REFERENCES orders(order_no),
    line_no         INTEGER NOT NULL,
    sku             TEXT NOT NULL REFERENCES items(sku),
    qty_ordered     REAL NOT NULL,
    qty_done        REAL NOT NULL DEFAULT 0,
    location_code   TEXT,                        -- suggested pick location
    PRIMARY KEY (order_no, line_no)
);

CREATE INDEX IF NOT EXISTS ix_order_lines_sku ON order_lines (sku);
