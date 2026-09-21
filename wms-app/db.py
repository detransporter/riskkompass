"""Connection layer: one SQLite file per tenant, plus the shared directory db.

No ORM on purpose -- plain sqlite3 + sqlite3.Row, same pattern as
transportbokning/app.py elsewhere in this repo. Anything that touches more
than one table inside a single logical operation (recording a movement AND
keeping the stock balance in sync) lives here, not duplicated across pages.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TENANTS_DIR = DATA_DIR / "tenants"
DIRECTORY_DB_PATH = DATA_DIR / "directory.db"
SCHEMA_DIR = BASE_DIR / "schema"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def now_iso() -> str:
    """UTC timestamp, deliberately WITHOUT a timezone offset suffix.

    Always UTC, so the omission is unambiguous -- but keeping it offset-free
    means every timestamp in `transactions` parses as a naive pandas
    Timestamp. The IHA analysis pipeline (analysis_bridge.py) does a lot of
    tz-naive datetime arithmetic (days-since-last-movement, month periods);
    mixing naive and tz-aware Timestamps there raises, so naive-everywhere
    was chosen over threading tz-localize calls through vendored analysis
    code that was written assuming naive dates.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def slugify(name: str) -> str:
    """Turn a company name into a filesystem-safe, URL-safe key.

    Collisions (two companies that slugify to the same thing) are handled by
    the caller: company registration retries with a numeric suffix.
    """
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "company"


def tenant_db_path(company_slug: str) -> Path:
    return TENANTS_DIR / f"{company_slug}.db"


# --------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------- #

def get_directory_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DIRECTORY_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_tenant_conn(company_slug: str) -> sqlite3.Connection:
    TENANTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(tenant_db_path(company_slug)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate_tenant_db(conn)
    return conn


def _migrate_tenant_db(conn: sqlite3.Connection) -> None:
    """Idempotent schema migrations for tenant databases created before a
    schema change -- adds columns schema/tenant.sql now defines for brand-new
    tenants, without touching any existing data. Cheap and safe to call on
    every connection open (a no-op once the column exists); the alternative
    (a separate migration-runner step) would be one more thing to remember
    to run, and this app has no deploy pipeline yet to hook that into.

    Guards on the table existing first: during init_tenant_db() this runs
    via get_tenant_conn() *before* schema/tenant.sql's CREATE TABLE has
    executed, on a connection to a file that may not have any tables yet.
    """
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transactions'"
    ).fetchone()
    if not table_exists:
        return

    # 2026-09-21, docs/FORECAST_SPEC.md Phase 5: real lead time is receipt
    # date minus order date; created_at only ever records the receipt.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    if "po_date" not in existing_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN po_date TEXT")
    if "expected_date" not in existing_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN expected_date TEXT")
    conn.commit()


# --------------------------------------------------------------------- #
# Schema init -- idempotent, safe to call on every app start
# --------------------------------------------------------------------- #

def init_directory_db() -> None:
    conn = get_directory_conn()
    try:
        conn.executescript((SCHEMA_DIR / "directory.sql").read_text())
        conn.commit()
    finally:
        conn.close()


def init_tenant_db(company_slug: str) -> None:
    conn = get_tenant_conn(company_slug)
    try:
        conn.executescript((SCHEMA_DIR / "tenant.sql").read_text())
        conn.commit()
    finally:
        conn.close()


def tenant_exists(company_slug: str) -> bool:
    return tenant_db_path(company_slug).exists()


def find_item_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    """Look up an item by scanned barcode, falling back to SKU.

    A USB/Bluetooth scanner just types whatever is encoded and hits Enter --
    the operator doesn't choose whether that's a barcode or a SKU, so both
    receive/pick flows must accept either.
    """
    code = code.strip()
    if not code:
        return None
    return conn.execute(
        "SELECT * FROM items WHERE barcode = ? OR sku = ?", (code, code)
    ).fetchone()


# --------------------------------------------------------------------- #
# Stock + transaction helpers -- the one place that keeps `stock` balances
# consistent with the `transactions` log. Every write path (receive, pick,
# putaway, ...) must go through record_transaction rather than writing to
# `stock` directly, or the two will drift apart.
# --------------------------------------------------------------------- #

def _adjust_stock(conn: sqlite3.Connection, sku: str, location_code: str, delta: float) -> None:
    row = conn.execute(
        "SELECT qty FROM stock WHERE sku = ? AND location_code = ?",
        (sku, location_code),
    ).fetchone()
    new_qty = (row["qty"] if row else 0.0) + delta
    if new_qty < 0:
        raise ValueError(
            f"Otillräckligt saldo: {sku} på {location_code} har "
            f"{row['qty'] if row else 0.0}, kan inte ta bort {-delta}"
        )
    if row:
        conn.execute(
            "UPDATE stock SET qty = ? WHERE sku = ? AND location_code = ?",
            (new_qty, sku, location_code),
        )
    else:
        conn.execute(
            "INSERT INTO stock (sku, location_code, qty) VALUES (?, ?, ?)",
            (sku, location_code, new_qty),
        )


def record_transaction(
    conn: sqlite3.Connection,
    txn_type: str,
    sku: str,
    qty: float,
    *,
    from_location: str | None = None,
    to_location: str | None = None,
    reference: str | None = None,
    user_email: str | None = None,
    po_date: str | None = None,
    expected_date: str | None = None,
) -> int:
    """Insert a transactions row and apply the matching stock delta.

    Stock-affecting types:
      receive  -> +qty at to_location
      putaway  -> -qty at from_location, +qty at to_location
      pick     -> -qty at from_location
      adjust   -> qty (signed) at to_location (or from_location if only that is given)
    pack / ship / count are logged for the audit trail and the IHA pipeline
    but do not move physical stock themselves in this MVP -- pick already
    removed the goods from the shelf.

    po_date/expected_date are only meaningful for txn_type='receive' (see
    schema/tenant.sql) -- callers for every other txn_type simply never
    pass them, no validation needed here since a NULL is exactly correct
    for "not applicable", not "not yet known".
    """
    if txn_type == "receive":
        if not to_location:
            raise ValueError("receive kräver to_location")
        _adjust_stock(conn, sku, to_location, qty)
    elif txn_type == "putaway":
        if not from_location or not to_location:
            raise ValueError("putaway kräver from_location och to_location")
        _adjust_stock(conn, sku, from_location, -qty)
        _adjust_stock(conn, sku, to_location, qty)
    elif txn_type == "pick":
        if not from_location:
            raise ValueError("pick kräver from_location")
        _adjust_stock(conn, sku, from_location, -qty)
    elif txn_type == "adjust":
        location = to_location or from_location
        if not location:
            raise ValueError("adjust kräver to_location eller from_location")
        _adjust_stock(conn, sku, location, qty)
    elif txn_type in ("pack", "ship", "count"):
        pass
    else:
        raise ValueError(f"okänd txn_type: {txn_type}")

    cur = conn.execute(
        """
        INSERT INTO transactions
            (txn_type, sku, qty, from_location, to_location, reference, user_email,
             created_at, po_date, expected_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (txn_type, sku, qty, from_location, to_location, reference, user_email,
         now_iso(), po_date, expected_date),
    )
    return cur.lastrowid
