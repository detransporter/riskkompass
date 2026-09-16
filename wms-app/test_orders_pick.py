"""
test_orders_pick.py
Smoke test for the order lifecycle: create an order + line, pick it
partially (status open -> picking), then finish it (status -> packed), and
confirm the stock math. Exercises the real functions views/pick.py exposes
as plain, testable logic (_find_open_line, _advance_order_status) --  the
rest of the pick-and-confirm sequence is inlined in Streamlit UI code, so
this test replicates it with the same underlying db.record_transaction +
order_lines calls the UI makes.

Usage: python3 test_orders_pick.py
"""

import sys
from pathlib import Path

import auth
import db
from views.pick import _advance_order_status, _find_open_line

TEST_COMPANY_NAME = "__test_orders_pick_smoke__"


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
    user, err = auth.register_company(TEST_COMPANY_NAME, "test@orderssmoke.local", "SakertLosen2026")
    if err:
        fail(f"register_company failed: {err}")
    slug = user.company_slug

    try:
        conn = db.get_tenant_conn(slug)
        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, created_at) "
            "VALUES ('SKU-1', 'Test item', 10.0, 'SEK', ?)", (db.now_iso(),)
        )
        conn.execute("INSERT INTO locations (code, location_type) VALUES ('LOC-A', 'picking')")
        conn.commit()
        db.record_transaction(conn, "receive", "SKU-1", 100, to_location="LOC-A")
        conn.commit()

        conn.execute(
            "INSERT INTO orders (order_no, order_type, status, created_at) "
            "VALUES ('ORD-1', 'outbound', 'open', ?)", (db.now_iso(),)
        )
        conn.execute(
            "INSERT INTO order_lines (order_no, line_no, sku, qty_ordered, location_code) "
            "VALUES ('ORD-1', 1, 'SKU-1', 60, 'LOC-A')"
        )
        conn.commit()

        line = _find_open_line(conn, "ORD-1", "SKU-1")
        if line is None or line["qty_ordered"] - line["qty_done"] != 60:
            fail(f"_find_open_line: expected 60 remaining, got {dict(line) if line else None}")
        print("OK  _find_open_line finds the open line with correct remaining qty")

        # Partial pick: 20 of 60.
        db.record_transaction(conn, "pick", "SKU-1", 20, from_location="LOC-A", reference="ORD-1")
        conn.execute(
            "UPDATE order_lines SET qty_done = qty_done + 20 WHERE order_no='ORD-1' AND line_no=1"
        )
        _advance_order_status(conn, "ORD-1")
        conn.commit()
        status = conn.execute("SELECT status FROM orders WHERE order_no='ORD-1'").fetchone()["status"]
        if status != "picking":
            fail(f"expected status 'picking' after partial pick, got '{status}'")
        print("OK  order status advances open -> picking on partial pick")

        line = _find_open_line(conn, "ORD-1", "SKU-1")
        if line["qty_ordered"] - line["qty_done"] != 40:
            fail(f"expected 40 remaining after partial pick, got {line['qty_ordered'] - line['qty_done']}")
        print("OK  remaining qty correctly reduced after partial pick")

        # Finish the line: 40 more.
        db.record_transaction(conn, "pick", "SKU-1", 40, from_location="LOC-A", reference="ORD-1")
        conn.execute(
            "UPDATE order_lines SET qty_done = qty_done + 40 WHERE order_no='ORD-1' AND line_no=1"
        )
        _advance_order_status(conn, "ORD-1")
        conn.commit()
        status = conn.execute("SELECT status FROM orders WHERE order_no='ORD-1'").fetchone()["status"]
        if status != "packed":
            fail(f"expected status 'packed' after full pick, got '{status}'")
        print("OK  order status advances picking -> packed when fully picked")

        if _find_open_line(conn, "ORD-1", "SKU-1") is not None:
            fail("_find_open_line should return None once the line is fully picked")
        print("OK  _find_open_line returns None once fully picked")

        remaining_stock = conn.execute(
            "SELECT qty FROM stock WHERE sku='SKU-1' AND location_code='LOC-A'"
        ).fetchone()["qty"]
        if remaining_stock != 40:
            fail(f"expected 40 remaining stock (100 received - 60 picked), got {remaining_stock}")
        print("OK  stock correctly decremented by total picked quantity")

        conn.close()
    finally:
        cleanup(slug)

    print("\nALL order/pick lifecycle CHECKS PASSED")


if __name__ == "__main__":
    main()
