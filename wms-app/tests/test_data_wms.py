"""Tests for forecasting/data_wms.py -- the live wms-app SQLite tenant ->
forecasting/ CSV-contract adapter. Creates its own throwaway tenant (same
pattern test_db.py already uses: a real tenant DB under data/tenants/,
deleted afterward, not a mocked path) and seeds it with a few
hand-verifiable rows rather than depending on the generated demo dataset,
which could change shape independently of this adapter's own contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import auth
import db
from forecasting.data_wms import load_wms_tenant

TEST_COMPANY_NAME = "__test_data_wms_smoke__"


@pytest.fixture
def tenant_slug():
    user, error = auth.register_company(TEST_COMPANY_NAME, "test@example.com", "not-a-common-pw-x7q")
    assert error is None, error
    slug = user.company_slug

    conn = db.get_tenant_conn(slug)
    conn.executemany(
        "INSERT INTO items (sku, description, category, supplier, unit_cost, lead_time_days, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("A1", "Widget", "Verktyg", "SupplierX", 100.0, 14, "2024-01-01"),
            ("A2", "Gadget", "Elkomponenter", "SupplierY", 50.0, 7, "2024-02-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO locations (code, zone, location_type) VALUES (?, ?, ?)",
        [("LOC-1", "Z1", "picking")],
    )
    conn.execute("INSERT INTO stock (sku, location_code, qty) VALUES ('A1', 'LOC-1', 30)")
    conn.execute("INSERT INTO stock (sku, location_code, qty) VALUES ('A2', 'LOC-1', 5)")

    conn.execute(
        "INSERT INTO orders (order_no, order_type, status, reference, created_at) "
        "VALUES ('SO-1', 'outbound', 'shipped', 'CustomerZ', '2024-03-01T09:00:00')"
    )
    conn.executemany(
        "INSERT INTO order_lines (order_no, line_no, sku, qty_ordered, qty_done, location_code) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [("SO-1", 1, "A1", 10.0, 8.0, "LOC-1"), ("SO-1", 2, "A2", 4.0, 4.0, "LOC-1")],
    )
    conn.execute(
        "INSERT INTO transactions (txn_type, sku, qty, to_location, created_at, po_date, expected_date) "
        "VALUES ('receive', 'A1', 20.0, 'LOC-1', '2024-01-15T08:00:00', '2024-01-01', '2024-01-14')"
    )
    conn.commit()
    conn.close()

    yield slug

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


def test_load_wms_tenant_returns_all_four_frames(tenant_slug):
    data = load_wms_tenant(tenant_slug)
    assert set(data.keys()) == {"items", "outbound", "inbound", "stock"}


def test_items_mapped_correctly(tenant_slug):
    items = load_wms_tenant(tenant_slug)["items"]
    a1 = items[items["article_id"] == "A1"].iloc[0]
    assert a1["description"] == "Widget"
    assert a1["category"] == "Verktyg"
    assert a1["supplier_id"] == "SupplierX"
    assert a1["unit_cost_sek"] == 100.0
    assert a1["lead_time_days"] == 14
    assert a1["moq"] == 1
    assert a1["order_multiple"] == 1


def test_outbound_qty_ordered_is_order_line_qty_ordered_not_qty_done(tenant_slug):
    """Demand = qty_ordered per the project-wide convention -- must stay
    the CUSTOMER'S requested quantity (10), not what was actually shipped
    so far (8), even though a real order can be partially fulfilled."""
    outbound = load_wms_tenant(tenant_slug)["outbound"]
    a1_line = outbound[outbound["article_id"] == "A1"].iloc[0]
    assert a1_line["qty_ordered"] == 10.0
    assert a1_line["qty_shipped"] == 8.0
    assert a1_line["customer_id"] == "CustomerZ"


def test_inbound_maps_receive_transaction(tenant_slug):
    inbound = load_wms_tenant(tenant_slug)["inbound"]
    assert len(inbound) == 1
    row = inbound.iloc[0]
    assert row["article_id"] == "A1"
    assert row["qty_ordered"] == 20.0
    assert row["qty_received"] == 20.0  # see module docstring: no separate ordered qty in the live schema
    assert row["status"] == "Received"
    assert row["supplier_id"] == "SupplierX"
    assert row["unit_price_sek"] == 100.0


def test_stock_is_a_single_current_snapshot(tenant_slug):
    stock = load_wms_tenant(tenant_slug)["stock"]
    assert len(stock) == 2  # one row per article, not per (article, location)
    a1 = stock[stock["article_id"] == "A1"].iloc[0]
    assert a1["stock_qty"] == 30.0
    assert a1["stock_value_sek"] == 30.0 * 100.0
    assert stock["snapshot_date"].nunique() == 1


def test_downstream_build_demand_series_accepts_the_adapter_output(tenant_slug):
    """The whole point of matching the CSV contract exactly -- confirms
    forecasting/data.py's own function accepts this adapter's output
    unmodified."""
    from forecasting.data import build_demand_series
    data = load_wms_tenant(tenant_slug)
    series = build_demand_series(data["outbound"], data["items"], freq="W")
    assert set(series.columns) == {"article_id", "period", "qty_ordered", "qty_shipped"}
    assert (series["article_id"].isin(["A1", "A2"])).all()
