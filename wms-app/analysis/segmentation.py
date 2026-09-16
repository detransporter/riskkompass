# Vendored from iha-saas/analysis/segmentation.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration".
"""
Phase 2 — turn the demand time series kept by data_merge into decisions.

Three things happen here:

  1. XYZ classification — how *predictable* demand is, from the measured
     coefficient of variation. ABC says how much an item is worth; XYZ says
     whether you can plan it. Together they decide which control policy the
     item should get, which is the question a client actually needs answered.

  2. Trend classification — recent demand against the preceding window, so a
     declining item is visible before it turns into dead stock.

  3. Recency-based status — the fix for the dangerous false negative. DOS is
     computed from an average over the whole history, so an item that sold
     heavily a year ago and nothing since still shows a healthy DOS. Time since
     last movement catches it. Status is only ever made *more* severe here,
     never less, so the change can only surface dead stock — never hide it.

Every classifier returns None where the data cannot support a verdict, rather
than defaulting to a benign value. "Not measurable" and "fine" must not look
the same in a client report.
"""

import numpy as np
import pandas as pd

# ── XYZ thresholds (coefficient of variation of period demand) ───────────────
# X ≤ 0.5   predictable, safe to automate
# Y ≤ 1.0   variable, needs a forecast and a real buffer
# Z > 1.0   erratic/lumpy — buffering it to a high service level is expensive
CV_X = 0.5
CV_Y = 1.0

# An item moving in under half the observed periods is intermittent. Its CV can
# look deceptively low when the few movements are similar in size, so it is
# classed Z regardless — the planning problem is *when*, not *how much*.
INTERMITTENT_RATIO = 0.5

# ── Trend thresholds (recent window / preceding window) ──────────────────────
TREND_DOWN = 0.7
TREND_UP = 1.3

# ── Recency thresholds (days since last movement) ────────────────────────────
# Aligned with the standard IHA framework: no movement in 90 days = slow,
# 180 days = dead. These run alongside the DOS rules in dos_calculator, not
# instead of them: an item is caught by whichever signal fires first.
RECENCY_SLOW = 90
RECENCY_DEAD = 180


def classify_xyz(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'xyz_class' (X/Y/Z, or None when variability was never measured)."""
    df = df.copy()

    if "demand_cv" not in df.columns:
        df["xyz_class"] = None
        return df

    cv = pd.to_numeric(df["demand_cv"], errors="coerce")

    intermittent = pd.Series(False, index=df.index)
    if {"months_with_demand", "demand_months"} <= set(df.columns):
        months = pd.to_numeric(df["demand_months"], errors="coerce")
        active = pd.to_numeric(df["months_with_demand"], errors="coerce")
        intermittent = (active / months.where(months > 0)) < INTERMITTENT_RATIO

    xyz = pd.Series(pd.NA, index=df.index, dtype="object")
    xyz[cv <= CV_X] = "X"
    xyz[(cv > CV_X) & (cv <= CV_Y)] = "Y"
    xyz[cv > CV_Y] = "Z"
    xyz[intermittent.fillna(False) & cv.notna()] = "Z"

    df["xyz_class"] = xyz.where(xyz.notna(), None)
    return df


def classify_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'demand_trend_ratio' and 'trend_class'.

    trend_class ∈ {new, growing, stable, declining, stopped} or None when the
    history is too short (under 6 complete periods) to compare two windows.
    """
    df = df.copy()

    if not {"demand_recent_avg", "demand_prior_avg"} <= set(df.columns):
        df["demand_trend_ratio"] = np.nan
        df["trend_class"] = None
        return df

    recent = pd.to_numeric(df["demand_recent_avg"], errors="coerce")
    prior = pd.to_numeric(df["demand_prior_avg"], errors="coerce")

    ratio = (recent / prior.where(prior > 0)).replace([np.inf, -np.inf], np.nan)
    df["demand_trend_ratio"] = ratio

    known = recent.notna() & prior.notna()
    had_history = pd.to_numeric(
        df.get("months_with_demand", pd.Series(0, index=df.index)), errors="coerce"
    ).fillna(0) > 0

    trend = pd.Series(pd.NA, index=df.index, dtype="object")

    # Ratio-based classes first, then the absolute cases override them. Order
    # matters: an item that stopped completely has a ratio of 0, which also
    # satisfies "declining" — but "stopped" is the more useful verdict.
    trend[known & (ratio < TREND_DOWN)] = "declining"
    trend[known & (ratio >= TREND_DOWN) & (ratio <= TREND_UP)] = "stable"
    trend[known & (ratio > TREND_UP)] = "growing"
    trend[known & (prior <= 0) & (recent > 0)] = "new"

    # Stopped covers both "sold until recently" (prior > 0) and "stopped before
    # the comparison window but did sell earlier in the history" — the latter
    # has zero demand in both windows, so no ratio exists to classify it.
    trend[known & (recent <= 0) & ((prior > 0) | had_history)] = "stopped"

    # Two 3-month windows cannot characterise an item that only moves a few
    # times a year: a chance movement in the recent window reads as "new" or
    # "growing" when nothing has actually changed. For intermittent items only
    # the absence verdict survives — you can tell that one has stopped, not
    # that it is growing.
    if {"months_with_demand", "demand_months"} <= set(df.columns):
        months = pd.to_numeric(df["demand_months"], errors="coerce")
        active = pd.to_numeric(df["months_with_demand"], errors="coerce")
        intermittent = ((active / months.where(months > 0)) < INTERMITTENT_RATIO).fillna(False)
        trend[intermittent & (trend != "stopped")] = pd.NA

    df["trend_class"] = trend.where(trend.notna(), None)
    return df


# Severity order — the recency rule may raise an item's status but never lower it.
_SEVERITY = {"healthy": 0, "stockout_risk": 1, "slow_mover": 2, "dead_stock": 3}


def apply_recency_status(df: pd.DataFrame) -> pd.DataFrame:
    """Escalate status using time since last movement, and record why.

    Adds 'status_reason' explaining which signal decided the status:
        dos       — the days-of-stock thresholds (the original rule)
        recency   — no movement for 90/180 days, despite an acceptable DOS
        no_demand — stock on hand with no demand at all in the file
        stockout  — no stock but active demand
    """
    df = df.copy()

    if "status" not in df.columns:
        return df

    status = df["status"].astype(object)
    reason = pd.Series("dos", index=df.index, dtype=object)
    reason[status == "stockout_risk"] = "stockout"
    if "avg_daily_demand" in df.columns:
        no_demand = pd.to_numeric(df["avg_daily_demand"], errors="coerce").fillna(0) <= 0
        reason[no_demand & (status == "dead_stock")] = "no_demand"

    if "days_since_last_movement" in df.columns:
        days = pd.to_numeric(df["days_since_last_movement"], errors="coerce")
        stock = pd.to_numeric(df.get("stock_qty", 0), errors="coerce").fillna(0)
        holds_stock = stock > 0

        current = status.map(_SEVERITY).fillna(0)

        # Sitting on stock that has not moved for half a year is dead stock,
        # whatever a full-history average says about days of cover.
        to_dead = holds_stock & (days >= RECENCY_DEAD) & (current < _SEVERITY["dead_stock"])
        to_slow = (holds_stock & (days >= RECENCY_SLOW) & (days < RECENCY_DEAD)
                   & (current < _SEVERITY["slow_mover"]))

        status[to_dead] = "dead_stock"
        status[to_slow] = "slow_mover"
        reason[to_dead | to_slow] = "recency"

    df["status"] = status
    df["status_reason"] = reason
    return df


def segment(df: pd.DataFrame) -> pd.DataFrame:
    """Run the full phase-2 segmentation in the right order."""
    df = classify_xyz(df)
    df = classify_trend(df)
    df = apply_recency_status(df)
    return df


# ── ABC × XYZ policy matrix ──────────────────────────────────────────────────
# The consulting payload: what to actually *do* with each of the nine cells.
# Value drives how much attention an item deserves; predictability drives what
# kind of control is even possible.
POLICY_MATRIX = {
    ("A", "X"): ("Automate", "Automatic reorder point. Tight buffer, review quarterly. "
                             "Best candidate for lowering stock without touching service."),
    ("A", "Y"): ("Forecast + buffer", "Forecast-driven with a real safety stock. "
                                      "Review monthly; seasonality is worth modelling."),
    ("A", "Z"): ("Manual control", "High value, unpredictable — the most expensive cell. "
                                   "Manual review, hedge with supplier agreements or shorter "
                                   "lead times rather than more stock."),
    ("B", "X"): ("Automate", "Automatic reorder point, larger batches, quarterly review."),
    ("B", "Y"): ("Automate + alert", "Automatic with an exception alert on deviation."),
    ("B", "Z"): ("Order to demand", "Avoid holding a buffer. Order against confirmed demand "
                                    "where lead time allows."),
    ("C", "X"): ("Bulk, rarely", "Large infrequent orders. Minimise handling, not capital."),
    ("C", "Y"): ("Bulk, rarely", "Large infrequent orders; accept a lower service level."),
    ("C", "Z"): ("Stop stocking", "Low value and unpredictable. Make to order, or delist. "
                                  "This cell is where dead stock is manufactured."),
}


def policy_for(abc: str, xyz: str) -> tuple[str, str]:
    """(short policy, rationale) for an ABC-XYZ cell; ('–', '') when unknown."""
    return POLICY_MATRIX.get((abc, xyz), ("–", "Demand variability not measured — "
                                               "no policy recommendation possible."))


def matrix_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Nine-box summary: SKU count and inventory value per ABC × XYZ cell."""
    if not {"abc_class", "xyz_class"} <= set(df.columns):
        return pd.DataFrame()

    d = df[df["xyz_class"].notna()].copy()
    if d.empty:
        return pd.DataFrame()

    out = (d.groupby(["abc_class", "xyz_class"])
             .agg(skus=("sku", "count"), value_sek=("value_sek", "sum"))
             .reset_index())
    out["policy"] = [policy_for(a, x)[0] for a, x in zip(out["abc_class"], out["xyz_class"])]
    return out
