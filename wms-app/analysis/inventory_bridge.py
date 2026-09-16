# Vendored from iha-saas/analysis/inventory_bridge.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration".
"""
Phase 4 — answer the question the client actually has.

Everything before this describes the inventory. None of it answers "what
*should* it be?". Without that number the assessment is a health report; with
it, it is an investment case.

The bridge decomposes what is on the shelf today into four parts:

    Current inventory
      ├─ Justified cycle stock    what batching forces you to hold
      ├─ Justified safety stock   what the service target forces you to hold
      ├─ Excess                   above justified, on items that still sell
      └─ Dead stock               no longer sells at all

and adds the part nobody likes to show:

      Deficit                     items BELOW justified — capital that has to
                                  be added to hit the service levels promised

Netting the deficit silently against the excess would flatter the result and
mislead the client, so it is reported as its own line and never subtracted
without being named.

Cycle stock is measured, not assumed, wherever the receipt history allows:
the average received quantity is the real batch size, and average cycle stock
is half of it. That figure comes from the client's own goods-in data rather
than from an EOQ formula fed with invented order costs.
"""

import numpy as np
import pandas as pd

HOLDING_RATE = 0.22        # total annual holding cost, per the IHA framework
LIQUIDATION_RATE = 0.25    # midpoint of the 10-40% typically realised on dead stock
DEFAULT_REVIEW_DAYS = 30   # ordering cycle assumed when no receipt history exists

# ── Root causes ──────────────────────────────────────────────────────────────
# Dead stock is a symptom. These are the causes that can be detected from the
# data the client already supplied — each one implies a different fix, which is
# the difference between "liquidate 3.1 MSEK" and "here is why it happened".
ROOT_CAUSES = {
    "bought_after_death": (
        "Bought after demand stopped",
        "The last delivery arrived after the item had already stopped selling. "
        "A purchasing-control problem, not a forecasting one — an alert on "
        "inbound for items with no recent movement stops it repeating."),
    "moq_overbuy": (
        "Over-bought / MOQ",
        "A single delivery covered more than a year of demand. Minimum order "
        "quantities or batch discounts are creating the dead stock. Renegotiate "
        "the MOQ before renegotiating price."),
    "demand_collapse": (
        "Demand collapsed",
        "The item sold normally and then fell away. Nothing was wrong with the "
        "purchase at the time — the failure is that nobody acted when demand "
        "turned. This is what the trend view is for."),
    "phase_out": (
        "Phased out, never run down",
        "No movement for over a year with stock still on the shelf. The product "
        "was discontinued commercially but never given a run-down plan."),
    "erratic_demand": (
        "Unpredictable demand",
        "Lumpy, hard-to-forecast demand buffered with stock. For low-value items "
        "this is the wrong trade: order against demand instead of holding it."),
    "overstocked_healthy": (
        "Over-ordered, still sells",
        "The item sells fine; there is simply too much of it. The reorder "
        "parameters are wrong — this is the cheapest category to fix."),
    "unknown": (
        "Not determined",
        "Not enough history to attribute a cause. Usually means no dated sales "
        "or inbound data for this item."),
}


def _num_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    """Numeric column as a Series, or a filled Series when the column is absent.

    df.get(name, 0) returns the scalar 0 for a missing column, which then fails
    on every Series operation — so every optional column goes through here.
    """
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def _obj_col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index, dtype="object")


def compute_bridge(df: pd.DataFrame,
                   holding_rate: float = HOLDING_RATE,
                   liquidation_rate: float = LIQUIDATION_RATE,
                   review_days: int = DEFAULT_REVIEW_DAYS) -> tuple[pd.DataFrame, dict]:
    """Split every SKU into justified / excess / dead / deficit, in SEK.

    Returns (df with per-SKU columns added, summary dict).
    """
    df = df.copy()

    qty = _num_col(df, "stock_qty")
    value = _num_col(df, "value_sek")
    demand = _num_col(df, "avg_daily_demand")
    safety = _num_col(df, "safety_stock")

    # Unit value, taken the same way ABC takes it, so the bridge and the
    # classification cannot disagree about what an item is worth.
    unit = pd.Series(np.nan, index=df.index, dtype=float)
    for col in ("unit_price", "unit_cost"):
        if col in df.columns:
            unit = unit.where(unit > 0, pd.to_numeric(df[col], errors="coerce"))
    unit = unit.where(unit > 0, (value / qty.where(qty > 0)))
    unit = unit.fillna(0.0)

    # ── Cycle stock: half the real batch size ────────────────────────────────
    # Measured from goods-in where possible. Falling back to a review period is
    # an assumption, so it is flagged.
    batch = pd.Series(np.nan, index=df.index, dtype=float)
    if {"inbound_qty", "inbound_receipts"} <= set(df.columns):
        inb = pd.to_numeric(df["inbound_qty"], errors="coerce")
        rec = pd.to_numeric(df["inbound_receipts"], errors="coerce")
        batch = (inb / rec.where(rec > 0)).replace([np.inf, -np.inf], np.nan)
    df["avg_receipt_qty"] = batch

    df["cycle_stock_measured"] = batch.notna() & (batch > 0)
    batch = batch.where(batch > 0, demand * review_days)
    df["cycle_stock"] = (batch / 2).fillna(0)

    # ── What is justified ────────────────────────────────────────────────────
    is_dead = _obj_col(df, "status", "") == "dead_stock"

    justified_qty = (df["cycle_stock"] + safety).where(~is_dead, 0)
    # Never call more stock "justified" than actually exists.
    justified_qty = np.minimum(justified_qty, qty.clip(lower=0))

    # A dead item justifies nothing — not even cycle stock. Leaving its cycle
    # component in was double-counting: the value appeared both as justified
    # cycle stock and as dead stock, so the bridge did not add up to the total.
    cycle_component = np.minimum(df["cycle_stock"], qty.clip(lower=0)).where(~is_dead, 0)

    df["justified_qty"] = justified_qty
    df["justified_cycle_value"] = cycle_component * unit
    df["justified_safety_value"] = (justified_qty - cycle_component).clip(lower=0) * unit
    df["justified_value"] = justified_qty * unit

    # ── Excess, dead, deficit ────────────────────────────────────────────────
    df["dead_value"] = value.where(is_dead, 0)
    df["excess_qty"] = (qty - justified_qty).clip(lower=0).where(~is_dead, 0)
    df["excess_value"] = df["excess_qty"] * unit

    # Deficit: items holding less than the service target requires. Phase 3
    # raised the requirement for unreliable suppliers, so this is real money
    # that has to go IN, not a rounding artefact.
    target_qty = (df["cycle_stock"] + safety).where(~is_dead, 0)
    df["deficit_qty"] = (target_qty - qty).clip(lower=0).where(~is_dead, 0)
    df["deficit_value"] = df["deficit_qty"] * unit

    releasable = df["excess_value"].sum() + df["dead_value"].sum()
    summary = {
        "total_value": float(value.sum()),
        "justified_cycle": float(df["justified_cycle_value"].sum()),
        "justified_safety": float(df["justified_safety_value"].sum()),
        "excess": float(df["excess_value"].sum()),
        "dead": float(df["dead_value"].sum()),
        "deficit": float(df["deficit_value"].sum()),
        "releasable": float(releasable),
        # Excess is saleable stock — it converts to cash simply by not
        # reordering while it runs down, so it is counted at book value.
        # Dead stock has to be sold off and rarely fetches more than a fraction.
        "cash_from_excess": float(df["excess_value"].sum()),
        "cash_from_dead": float(df["dead_value"].sum() * liquidation_rate),
        "annual_holding_saving": float(releasable * holding_rate),
        "liquidation_rate": liquidation_rate,
        "holding_rate": holding_rate,
        "cycle_measured_skus": int(df["cycle_stock_measured"].sum()),
        "deficit_skus": int((df["deficit_value"] > 0).sum()),
    }
    summary["total_cash"] = summary["cash_from_excess"] + summary["cash_from_dead"]

    return df, summary


def classify_root_cause(df: pd.DataFrame) -> pd.DataFrame:
    """Attribute a cause to every dead or slow item.

    Order matters: the first rule that fires wins, most specific first, so an
    item bought after its demand died is reported as a purchasing failure
    rather than the blander "demand collapsed".
    """
    df = df.copy()

    status = _obj_col(df, "status", "")
    target = status.isin(["dead_stock", "slow_mover"])

    cause = pd.Series(pd.NA, index=df.index, dtype="object")

    demand = _num_col(df, "avg_daily_demand")
    days_since = _num_col(df, "days_since_last_movement", np.nan)
    last_move = pd.to_datetime(_obj_col(df, "last_movement_date"), errors="coerce")
    last_in = pd.to_datetime(_obj_col(df, "last_inbound_date"), errors="coerce")
    trend = _obj_col(df, "trend_class")
    xyz = _obj_col(df, "xyz_class")

    # 1. Goods received after the item had already stopped selling.
    if last_in.notna().any() and last_move.notna().any():
        bought_late = (last_in.notna() & last_move.notna()
                       & (last_in > last_move + pd.Timedelta(days=30)))
        cause[target & bought_late] = "bought_after_death"

    # 2. One delivery covering more than a year of demand.
    if {"inbound_qty", "inbound_receipts"} <= set(df.columns):
        inb = pd.to_numeric(df["inbound_qty"], errors="coerce")
        rec = pd.to_numeric(df["inbound_receipts"], errors="coerce")
        batch = (inb / rec.where(rec > 0)).replace([np.inf, -np.inf], np.nan)
        annual = demand * 365
        moq = batch.notna() & (annual > 0) & (batch > annual)
        cause[target & cause.isna() & moq] = "moq_overbuy"

    # 3. Discontinued and never run down.
    cause[target & cause.isna() & (days_since >= 365)] = "phase_out"

    # 4. Sold normally, then fell away.
    cause[target & cause.isna() & trend.isin(["stopped", "declining"])] = "demand_collapse"

    # 5. Lumpy demand buffered with stock.
    cause[target & cause.isna() & (xyz == "Z")] = "erratic_demand"

    # 6. Still selling, simply too much of it.
    cause[target & cause.isna() & (demand > 0)] = "overstocked_healthy"

    cause[target & cause.isna()] = "unknown"

    df["root_cause"] = cause.where(cause.notna(), None)
    df["root_cause_label"] = df["root_cause"].map(
        {k: v[0] for k, v in ROOT_CAUSES.items()})
    return df


def root_cause_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Value and SKU count per root cause, worst first."""
    if "root_cause" not in df.columns:
        return pd.DataFrame()

    d = df[df["root_cause"].notna()]
    if d.empty:
        return pd.DataFrame()

    out = (d.groupby("root_cause")
             .agg(skus=("sku", "count"), value_sek=("value_sek", "sum"))
             .reset_index()
             .sort_values("value_sek", ascending=False))
    out["label"] = out["root_cause"].map({k: v[0] for k, v in ROOT_CAUSES.items()})
    out["action"] = out["root_cause"].map({k: v[1] for k, v in ROOT_CAUSES.items()})
    return out
