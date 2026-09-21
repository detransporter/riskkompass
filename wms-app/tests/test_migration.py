"""Regression test for db._migrate_tenant_db() -- the po_date/expected_date
migration (docs/FORECAST_SPEC.md Phase 5 needs a real order date to compute
actual lead time; created_at only ever records the receipt).

Formalizes the ad-hoc verification run once by hand while building the
migration: simulate a pre-migration tenant database (the exact schema
transactions had before this change), then prove get_tenant_conn() adds the
columns without touching existing data, and that a second call is a no-op.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import db


def _make_pre_migration_tenant_db(path: Path) -> None:
    """A transactions table exactly as it looked before po_date/expected_date
    existed -- not schema/tenant.sql (which already has the new columns for
    brand-new tenants), deliberately the OLD shape."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_type TEXT NOT NULL,
            sku TEXT NOT NULL,
            qty REAL NOT NULL,
            from_location TEXT,
            to_location TEXT,
            reference TEXT,
            user_email TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO transactions (txn_type, sku, qty, to_location, created_at) "
        "VALUES ('receive', 'SKU-OLD', 10, 'A-01', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()


def test_migration_adds_columns_without_touching_existing_data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "TENANTS_DIR", tmp_path)
    slug = "test-migration-tenant"
    db_path = tmp_path / f"{slug}.db"
    _make_pre_migration_tenant_db(db_path)

    before = sqlite3.connect(str(db_path)).execute("PRAGMA table_info(transactions)").fetchall()
    before_cols = {c[1] for c in before}
    assert "po_date" not in before_cols
    assert "expected_date" not in before_cols

    conn = db.get_tenant_conn(slug)
    after_cols = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    assert "po_date" in after_cols
    assert "expected_date" in after_cols

    row = conn.execute("SELECT sku, po_date, expected_date FROM transactions WHERE sku = 'SKU-OLD'").fetchone()
    assert row["sku"] == "SKU-OLD"
    assert row["po_date"] is None
    assert row["expected_date"] is None
    conn.close()


def test_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "TENANTS_DIR", tmp_path)
    slug = "test-migration-idempotent"
    db_path = tmp_path / f"{slug}.db"
    _make_pre_migration_tenant_db(db_path)

    conn1 = db.get_tenant_conn(slug)
    conn1.close()
    # Second call must not raise "duplicate column name" or otherwise fail.
    conn2 = db.get_tenant_conn(slug)
    cols = {row["name"] for row in conn2.execute("PRAGMA table_info(transactions)")}
    assert {"po_date", "expected_date"}.issubset(cols)
    conn2.close()


def test_migration_is_a_noop_on_a_brand_new_tenant_db(tmp_path, monkeypatch):
    """A connection to a file with no tables yet (init_tenant_db's own first
    call, before schema/tenant.sql's CREATE TABLE has run) must not raise."""
    monkeypatch.setattr(db, "TENANTS_DIR", tmp_path)
    slug = "test-migration-fresh"
    conn = db.get_tenant_conn(slug)  # no tables exist at all yet
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == []
    conn.close()
