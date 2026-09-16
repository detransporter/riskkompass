"""
test_db.py
Smoke test for db.py: connection layer, tenant isolation, and the
record_transaction stock-consistency logic (the one place allowed to write
to `stock`).

Creates its own throwaway tenant(s) (via auth.register_company) and deletes
them -- directory rows + tenant .db file -- afterwards, even on failure.

Usage: python3 test_db.py
"""

import sys
from pathlib import Path

import auth
import db

TEST_COMPANY_NAME = "__test_db_smoke__"


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
    user, err = auth.register_company(TEST_COMPANY_NAME, "test@dbsmoke.local", "SakertLosen2026")
    if err:
        fail(f"register_company failed: {err}")
    slug = user.company_slug
    print(f"Created test tenant {slug}")

    try:
        conn = db.get_tenant_conn(slug)
        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, created_at) "
            "VALUES ('SKU-1', 'Test item', 10.0, 'SEK', ?)", (db.now_iso(),)
        )
        conn.execute("INSERT INTO locations (code, location_type) VALUES ('LOC-A', 'bulk')")
        conn.execute("INSERT INTO locations (code, location_type) VALUES ('LOC-B', 'bulk')")
        conn.commit()

        db.record_transaction(conn, "receive", "SKU-1", 100, to_location="LOC-A")
        conn.commit()
        qty = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-A'"
        ).fetchone()["qty"]
        if qty != 100:
            fail(f"after receive 100: expected 100, got {qty}")
        print("OK  receive adds stock at to_location")

        db.record_transaction(conn, "putaway", "SKU-1", 30, from_location="LOC-A", to_location="LOC-B")
        conn.commit()
        a = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-A'"
        ).fetchone()["qty"]
        b = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-B'"
        ).fetchone()["qty"]
        if a != 70 or b != 30:
            fail(f"after putaway 30 A->B: expected A=70 B=30, got A={a} B={b}")
        print("OK  putaway moves stock between locations, total unchanged")

        db.record_transaction(conn, "pick", "SKU-1", 20, from_location="LOC-B")
        conn.commit()
        b = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-B'"
        ).fetchone()["qty"]
        if b != 10:
            fail(f"after pick 20 from LOC-B: expected 10, got {b}")
        print("OK  pick removes stock from from_location")

        db.record_transaction(conn, "adjust", "SKU-1", -5, to_location="LOC-B")
        conn.commit()
        b = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-B'"
        ).fetchone()["qty"]
        if b != 5:
            fail(f"after adjust -5 at LOC-B: expected 5, got {b}")
        print("OK  adjust applies a signed delta at a single location")

        try:
            db.record_transaction(conn, "pick", "SKU-1", 999, from_location="LOC-B")
            fail("over-pick should have raised ValueError")
        except ValueError:
            print("OK  insufficient stock raises ValueError instead of going negative")

        n = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        if n != 4:
            fail(f"expected 4 logged transactions (the failed over-pick must not log), got {n}")
        print("OK  transactions log has exactly the successful writes")

        conn.close()

        # Tenant isolation: a second company with the same name must get its
        # own slug and its own empty database.
        user2, err2 = auth.register_company(TEST_COMPANY_NAME, "test2@dbsmoke.local", "SakertLosen2026")
        if err2:
            fail(f"second register_company failed: {err2}")
        slug2 = user2.company_slug
        if slug2 == slug:
            fail("slug collision handling failed: second company got the same slug")
        conn2 = db.get_tenant_conn(slug2)
        n_items = conn2.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
        conn2.close()
        if n_items != 0:
            fail(f"tenant isolation broken: new tenant saw {n_items} items from another tenant")
        print(f"OK  tenant isolation: second company got its own slug ({slug2}) with 0 items")
        cleanup(slug2)
    finally:
        cleanup(slug)

    print("\nALL db.py CHECKS PASSED")


if __name__ == "__main__":
    main()
