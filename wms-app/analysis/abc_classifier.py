# Vendored from iha-saas/analysis/abc_classifier.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration".

import numpy as np
import pandas as pd


def _unit_value(df: pd.DataFrame) -> pd.Series:
    """Best available unit value per SKU, in priority order:

        1. unit_price  (single-file path)
        2. unit_cost   (multi-file path from data_merge)
        3. value_sek / stock_qty — ONLY where stock_qty > 0

    Step 3 must never come first. An item that is currently out of stock has
    value_sek = 0 and stock_qty = 0, so deriving its unit value from stock gave
    0 → annual usage value 0 → class C, even for a high-runner that had just
    stocked out. That inverted the point of ABC: the items that just ran out
    got the *lowest* service level (80%) and therefore the *smallest* safety
    stock. Master-data cost is used instead, so a zero-stock A item stays an A.
    """
    unit = pd.Series(np.nan, index=df.index, dtype=float)

    for col in ("unit_price", "unit_cost"):
        if col in df.columns:
            candidate = pd.to_numeric(df[col], errors="coerce")
            unit = unit.where(unit > 0, candidate)

    # Fill remaining gaps from stock value, but only where a quantity exists.
    if "value_sek" in df.columns and "stock_qty" in df.columns:
        qty = pd.to_numeric(df["stock_qty"], errors="coerce")
        val = pd.to_numeric(df["value_sek"], errors="coerce")
        derived = (val / qty.where(qty > 0)).replace([np.inf, -np.inf], np.nan)
        unit = unit.where(unit > 0, derived)

    return unit.fillna(0.0)


def _annual_usage_value(df: pd.DataFrame) -> pd.Series:
    """Annual usage value = avg_daily_demand * 365 * unit value (turnover, not
    stock on hand). Falls back to on-hand stock value (value_sek) only when
    no demand data exists at all, so a dataset without demand still gets a
    classification instead of collapsing everyone into C."""
    has_demand = "avg_daily_demand" in df.columns and df["avg_daily_demand"].sum() > 0

    if has_demand:
        unit = _unit_value(df)
        if unit.sum() > 0:
            demand = pd.to_numeric(df["avg_daily_demand"], errors="coerce").fillna(0)
            return demand * 365 * unit

    return df["value_sek"]


def classify_abc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'abc_class' column (A/B/C) based on cumulative share of annual usage
    value (demand x price) -- i.e. turnover, not static stock value.
    A = top 80%, B = next 15%, C = last 5%.
    """
    df = df.copy()
    df["annual_usage_value"] = _annual_usage_value(df)
    df = df.sort_values("annual_usage_value", ascending=False).reset_index(drop=True)
    total = df["annual_usage_value"].sum()
    df["cum_share"] = df["annual_usage_value"].cumsum() / total if total else 0.0

    def _class(row):
        if row["cum_share"] <= 0.80:
            return "A"
        elif row["cum_share"] <= 0.95:
            return "B"
        else:
            return "C"

    df["abc_class"] = df.apply(_class, axis=1)
    return df
