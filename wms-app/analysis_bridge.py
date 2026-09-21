"""SQLite -> canonical DataFrame -> IHA analysis pipeline.

Replaces iha-saas's Excel-upload step (analysis/data_merge.build_canonical,
which solves messy-column-name mapping) with direct SQL reads, since the WMS
schema already has known, canonical column names. Everything downstream
(dos_calculator, abc_classifier, segmentation, lead_time, inventory_bridge)
is the same vendored code iha-saas runs, in the same order, on the same
column names -- see wms-app/CLAUDE.md "IHA integration".
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from analysis.abc_classifier import classify_abc
from analysis.data_merge import aggregate_inbound, sales_statistics
from analysis.dos_calculator import calculate_dos, classify_status, compute_replenishment
from analysis.inventory_bridge import classify_root_cause, compute_bridge
from analysis.lead_time import resolve_lead_time
from analysis.segmentation import segment


def build_canonical(conn: sqlite3.Connection) -> tuple[pd.DataFrame, str]:
    """One row per item, with demand/inbound statistics derived from the
    live transaction log. Returns (df, data-quality note for the report)."""
    items = pd.read_sql(
        "SELECT sku, description, unit_cost, supplier, category, lead_time_days FROM items",
        conn,
    )
    if items.empty:
        return items, "Inga artiklar registrerade."

    stock = pd.read_sql(
        "SELECT sku, SUM(qty) AS stock_qty FROM stock GROUP BY sku", conn
    )

    # Demand = confirmed outbound movement. 'ship' has no stock effect of its
    # own (pick already removed the goods, see db.record_transaction) but is
    # included here too in case a future flow logs a ship-only movement.
    picks = pd.read_sql(
        "SELECT sku, qty, created_at FROM transactions WHERE txn_type IN ('pick', 'ship')",
        conn,
    )
    demand_stats, demand_note = sales_statistics(
        picks, sku_col="sku", qty_col="qty", date_col="created_at"
    )

    inbound = pd.read_sql(
        "SELECT sku, qty, created_at FROM transactions WHERE txn_type = 'receive'",
        conn,
    )
    # No order_date_col/promised_col: the WMS schema does not track a
    # separate "ordered at" timestamp for inbound goods yet, only when they
    # were physically received. lead_time.resolve_lead_time() falls back to
    # each item's master lead_time_days as a result -- honest for now, see
    # the note at the top of analysis/lead_time.py.
    inbound_stats = aggregate_inbound(inbound, sku_col="sku", qty_col="qty", date_col="created_at")

    df = items.merge(stock, on="sku", how="left")
    df["stock_qty"] = df["stock_qty"].fillna(0).clip(lower=0)

    df = df.merge(demand_stats, on="sku", how="left")
    df["avg_daily_demand"] = df["avg_daily_demand"].fillna(0)

    df = df.merge(inbound_stats, on="sku", how="left")

    df["last_movement_date"] = pd.to_datetime(df.get("last_movement_date"), errors="coerce")
    today = pd.Timestamp.today().normalize()
    df["days_since_last_movement"] = (today - df["last_movement_date"]).dt.days

    df["value_sek"] = df["stock_qty"] * df["unit_cost"].fillna(0)

    return df, demand_note


def build_demand_history(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """Long-format (sku, period, qty) demand history for
    analysis/demand_forecast.py's classify_sbc/forecast_* functions.

    Reuses build_canonical()'s already-computed demand_monthly_full column
    (a {period_str: qty} dict per SKU from data_merge.sales_statistics())
    instead of re-querying and re-deriving it -- that column already applies
    the exact masking demand_forecast.py itself requires: an explicit zero
    for a month with no movement, but the month entirely ABSENT (not
    zero-filled) before the SKU's own first transaction, so a SKU launched
    partway through the tenant's history isn't penalized for months it
    didn't exist in yet. See data_merge.py:_stats_from_matrix for where that
    masking actually happens; nothing here re-derives it.

    SKUs with no demand_monthly_full at all (never appeared in a pick/ship
    transaction) are absent from the output entirely, not present with zero
    rows -- matching classify_sbc()'s own "no rows at all" vs "no_demand
    class" distinction (see that function's docstring).
    """
    if canonical_df.empty or "demand_monthly_full" not in canonical_df.columns:
        return pd.DataFrame(columns=["sku", "period", "qty"])

    rows = []
    for _, row in canonical_df.iterrows():
        monthly = row.get("demand_monthly_full")
        if not isinstance(monthly, dict):
            continue
        for period, qty in monthly.items():
            rows.append({"sku": row["sku"], "period": period, "qty": qty})
    return pd.DataFrame(rows, columns=["sku", "period", "qty"])


def run_analysis(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Same pipeline order as iha-saas/pages/upload.py:_run_analysis(),
    extended to also return the bridge summary dict (iha-saas discards it at
    this stage and recomputes it later for the report; the report page here
    wants the KPIs immediately)."""
    df = df.copy()
    if "lead_time_days" not in df.columns:
        df["lead_time_days"] = 0
    df["lead_time_days"] = df["lead_time_days"].fillna(0)
    if "avg_daily_demand" not in df.columns:
        df["avg_daily_demand"] = 0
    df["stock_qty"] = df["stock_qty"].clip(lower=0)

    df = calculate_dos(df)
    df = classify_status(df)
    df = classify_abc(df)
    df = segment(df)                 # must precede replenishment
    df = resolve_lead_time(df)       # must precede replenishment
    df = compute_replenishment(df)
    df, bridge_summary = compute_bridge(df)  # must run last (needs safety_stock)
    df = classify_root_cause(df)
    return df, bridge_summary
