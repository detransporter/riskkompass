"""Adapter: wms-app's live SQLite tenant schema -> forecasting/'s CSV data
contract (forecasting/data.py's _OUTBOUND_COLS/_INBOUND_COLS/_ITEMS_COLS/
_STOCK_COLS). Every phase's own docstring has flagged this as "a natural,
separate adapter to add once a tenant has enough history to be worth
forecasting" -- this is that adapter.

Produces DataFrames in the EXACT column shape forecasting/data.py's
load_outbound()/load_inbound()/load_items()/load_stock() already return,
so everything downstream (build_demand_series, build_segment_table,
run_backtest, build_supplier_lead_time_table, compute_policy,
simulate_policy, forecasting/monitoring.py) runs completely unchanged
against a real tenant's own data -- no forecasting/*.py file needed to
change for this to work, only this one new adapter module.

Real gaps in the live schema, degraded honestly rather than faked:
- No separate "ordered vs received" quantity for inbound receipts (the
  WMS schema logs a receive transaction's qty as what arrived, with no
  PO-line concept at all) -- qty_ordered is set equal to qty_received.
  This means the partial-delivery signal forecasting/probabilistic.py's
  is_partial flag depends on will always read False here; a real
  limitation of the live schema, not of this adapter.
- No moq/order_multiple/reorder_point/safety_stock columns on wms-app's
  own items table (no "current ERP parameters" concept the way
  datagen/v1's synthetic items.csv has one) -- moq/order_multiple default
  to 1 (no rounding constraint), reorder_point/safety_stock default to 0.
  This means forecasting/simulate.py's "policy A = current ERP
  parameters" comparison has nothing real to compare against for a
  wms-app tenant; Phase 7's simulation is not meaningful against this
  data source specifically (there is no policy A here, only policy B).
"""

from __future__ import annotations

import sqlite3

import pandas as pd

import db


def load_wms_tenant(company_slug: str) -> dict[str, pd.DataFrame]:
    """One connection, all four frames, same shape as loading the demo
    CSVs -- see forecasting/data.py's _OUTBOUND_COLS etc. for the exact
    column contract each of these matches."""
    conn = db.get_tenant_conn(company_slug)
    try:
        items = _load_items(conn)
        outbound = _load_outbound(conn)
        inbound = _load_inbound(conn, items)
        stock = _load_stock(conn, items)
    finally:
        conn.close()
    return {"items": items, "outbound": outbound, "inbound": inbound, "stock": stock}


def _load_items(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT sku, description, category, supplier, unit_cost, lead_time_days, created_at FROM items",
        conn,
    )
    df = df.rename(columns={
        "sku": "article_id", "supplier": "supplier_id", "unit_cost": "unit_cost_sek",
        "created_at": "created_date",
    })
    df["created_date"] = pd.to_datetime(df["created_date"])
    df["uom"] = "ST"
    df["moq"] = 1
    df["order_multiple"] = 1
    df["reorder_point"] = 0.0
    df["safety_stock"] = 0.0
    df["status"] = "Aktiv"
    return df[["article_id", "description", "category", "uom", "supplier_id", "unit_cost_sek",
              "moq", "order_multiple", "lead_time_days", "reorder_point", "safety_stock",
              "created_date", "status"]]


def _load_outbound(conn: sqlite3.Connection) -> pd.DataFrame:
    """Demand = qty_ordered (unconstrained), same definition
    forecasting/data.py's own docstring states -- order_lines.qty_ordered
    is exactly that (what the customer asked for), qty_done is what
    actually got picked/shipped so far, mapped to qty_shipped so
    forecasting/cleaning.py:flag_censored()'s existing
    qty_shipped < qty_ordered stockout signal works unchanged. A still-
    open order's qty_done=0 correctly reads as "nothing shipped yet",
    not as a stockout -- flag_censored only looks at completed history
    windows via as_of filtering, so a live open order sitting at 0 simply
    won't be included until it is.
    """
    df = pd.read_sql(
        """
        SELECT o.created_at AS order_date, ol.order_no AS order_id, ol.line_no AS order_line,
               ol.sku AS article_id, o.reference AS customer_id,
               ol.qty_ordered, ol.qty_done AS qty_shipped
        FROM order_lines ol JOIN orders o ON o.order_no = ol.order_no
        WHERE o.order_type = 'outbound'
        """,
        conn,
    )
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def _load_inbound(conn: sqlite3.Connection, items: pd.DataFrame) -> pd.DataFrame:
    """See module docstring: qty_ordered = qty_received (no separate PO
    concept in the live schema), po_number synthesized one-per-transaction
    (`RCV-<id>`), status is always 'Received' -- only completed receive
    transactions are logged at all in this schema, there is no 'Open' PO
    state to represent (unlike datagen/v1's inbound.csv)."""
    df = pd.read_sql(
        """
        SELECT id, sku AS article_id, qty, po_date, expected_date, created_at AS receipt_date
        FROM transactions WHERE txn_type = 'receive'
        """,
        conn,
    )
    df["po_number"] = "RCV-" + df["id"].astype(str)
    df["po_line"] = 1
    df["qty_ordered"] = df["qty"]
    df["qty_received"] = df["qty"]
    df["status"] = "Received"
    df["po_date"] = pd.to_datetime(df["po_date"]).fillna(pd.to_datetime(df["receipt_date"]))
    df["expected_date"] = pd.to_datetime(df["expected_date"])
    df["receipt_date"] = pd.to_datetime(df["receipt_date"])

    supplier_by_item = items.set_index("article_id")["supplier_id"]
    unit_cost_by_item = items.set_index("article_id")["unit_cost_sek"]
    df["supplier_id"] = df["article_id"].map(supplier_by_item)
    df["unit_price_sek"] = df["article_id"].map(unit_cost_by_item)

    return df[["po_number", "po_line", "po_date", "supplier_id", "article_id", "qty_ordered",
              "unit_price_sek", "expected_date", "receipt_date", "qty_received", "status"]]


def _load_stock(conn: sqlite3.Connection, items: pd.DataFrame) -> pd.DataFrame:
    """The live `stock` table is a CURRENT snapshot, not a historical
    monthly series -- so this produces exactly one snapshot row per
    article (today), not the demo CSV's many-month history.
    forecasting/segmentation.py:build_segment_table() already only reads
    the LATEST snapshot per article regardless (`.groupby().tail(1)`), so
    this single-row-per-article shape is exactly what it needs; there is
    just no historical stock trend to look back further than that."""
    df = pd.read_sql("SELECT sku AS article_id, SUM(qty) AS stock_qty FROM stock GROUP BY sku", conn)
    unit_cost_by_item = items.set_index("article_id")["unit_cost_sek"]
    df["stock_value_sek"] = df["stock_qty"] * df["article_id"].map(unit_cost_by_item).fillna(0)
    df["snapshot_date"] = pd.Timestamp.today().normalize()
    return df[["snapshot_date", "article_id", "stock_qty", "stock_value_sek"]]
