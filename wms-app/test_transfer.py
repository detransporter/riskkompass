"""
test_transfer.py
Smoke test for the "Flytta" stock-transfer flow: moving stock between two
locations via db.record_transaction(txn_type='putaway'), and the
_items_with_stock() / _stock_by_location() helpers the transfer.py view
uses (manual no-scan picker + the per-location breakdown shown on confirm).

Usage: python3 test_transfer.py
"""

import sys
from pathlib import Path

import auth
import db
from views.transfer import _items_with_stock, _stock_by_location

TEST_COMPANY_NAME = "__test_transfer_smoke__"


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def cleanup(slug):
    conn = db.get_directory_conn()
    conn.execute(
        "DELETE FROM users WHERE company_id IN (SELECT id FROM companies WHERE slug = ?)", (slug,)
    )
    conn.execute("DELETE FROM companies WHERE slug = ?", (slug,))
    conn.commit()
    conn.close()
    path = db.tenant_db_path(slug)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()


def main():
    db.init_directory_db()
    user, err = auth.register_company(TEST_COMPANY_NAME, "test@transfersmoke.local", "SakertLosen2026")
    if err:
        fail(f"register_company failed: {err}")
    slug = user.company_slug

    try:
        conn = db.get_tenant_conn(slug)
        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, created_at) "
            "VALUES ('SKU-1', 'Test item', 10.0, 'SEK', ?)", (db.now_iso(),)
        )
        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, created_at) "
            "VALUES ('SKU-2', 'No stock item', 5.0, 'SEK', ?)", (db.now_iso(),)
        )
        conn.execute("INSERT INTO locations (code, location_type) VALUES ('LOC-A', 'bulk')")
        conn.execute("INSERT INTO locations (code, location_type) VALUES ('LOC-B', 'bulk')")
        conn.commit()
        db.record_transaction(conn, "receive", "SKU-1", 160, to_location="LOC-A")
        conn.commit()

        with_stock = [r["sku"] for r in _items_with_stock(conn)]
        if with_stock != ["SKU-1"]:
            fail(f"_items_with_stock: expected ['SKU-1'] (SKU-2 has none), got {with_stock}")
        print("OK  _items_with_stock only lists SKUs that currently have stock somewhere")

        db.record_transaction(conn, "putaway", "SKU-1", 60, from_location="LOC-A", to_location="LOC-B")
        conn.commit()

        stock_df = _stock_by_location(conn, "SKU-1")
        by_loc = dict(zip(stock_df["location_code"], stock_df["qty"]))
        if by_loc != {"LOC-A": 100, "LOC-B": 60}:
            fail(f"expected A=100 B=60 after transfer, got {by_loc}")
        print("OK  transfer splits stock correctly across locations, total unchanged")

        try:
            db.record_transaction(conn, "putaway", "SKU-1", 999, from_location="LOC-B", to_location="LOC-A")
            fail("transferring more than available should have raised ValueError")
        except ValueError:
            print("OK  transferring more than available stock raises ValueError")

        conn.close()
    finally:
        cleanup(slug)

    print("\nALL transfer CHECKS PASSED")


if __name__ == "__main__":
    main()
