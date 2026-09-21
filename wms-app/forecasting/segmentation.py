"""Segmentation and lifecycle (docs/FORECAST_SPEC.md Phase 3): ABC, XYZ,
trend, SBC (demand pattern), and lifecycle flags (new item, obsolescence,
stale-with-stock).

Reuses already-vendored, already-tested classifiers rather than
reimplementing anything they already do -- same "reuse and extend"
principle as Phase 1's build_demand_history() and Phase 2's SBC-class
reuse in the segment report:
  - analysis/data_merge.py:sales_statistics() for per-article demand
    statistics (avg_daily_demand, demand_cv, months_with_demand,
    demand_recent_avg/demand_prior_avg, ...) -- column-renamed
    (sku<->article_id) to match its sku_col contract.
  - analysis/abc_classifier.py:classify_abc() for ABC.
  - analysis/segmentation.py:classify_xyz()/classify_trend() for XYZ and trend.
  - analysis/demand_forecast.py:classify_sbc() for the ADI/CV2 demand
    pattern, fed by forecasting/data.py:build_demand_series() (already
    built in Phase 1).

New in this module: new-item and obsolescence lifecycle flags, validated
against datagen/v1's facit_dolda_egenskaper.csv ground truth in
tests/test_segmentation_facit.py. facit is TEST-ONLY -- nothing in this
module reads it; the flags below are computed from ordinary demand/items
data alone, exactly as they would be for a real tenant with no ground
truth available at all.
"""

from __future__ import annotations

import pandas as pd

from analysis.abc_classifier import classify_abc
from analysis.demand_forecast import classify_sbc
from analysis.data_merge import sales_statistics
from analysis.segmentation import RECENCY_DEAD, classify_trend, classify_xyz
from forecasting.data import build_demand_series

DEFAULT_NEW_ITEM_DAYS = 90


def build_segment_table(outbound: pd.DataFrame, items: pd.DataFrame, stock: pd.DataFrame,
                        as_of: pd.Timestamp | None = None,
                        new_item_days: int = DEFAULT_NEW_ITEM_DAYS) -> pd.DataFrame:
    """One row per article: abc_class, xyz_class, trend_class, sbc_class,
    plus is_new_item/is_becoming_obsolete/is_stale_with_stock lifecycle
    flags.

    as_of: point-in-time cutoff, same discipline as
    forecasting/cleaning.py's as_of -- filters outbound/stock to <= as_of
    BEFORE any statistic is computed, and is what "new item" and "current
    stock" are evaluated relative to. Defaults to the latest date present
    in `outbound` (the dataset's own "now") when not given.
    """
    if as_of is None:
        as_of = outbound["order_date"].max()

    ob = outbound[outbound["order_date"] <= as_of]
    stk = stock[stock["snapshot_date"] <= as_of] if not stock.empty else stock

    demand_stats, _note = sales_statistics(
        ob, sku_col="article_id", qty_col="qty_ordered", date_col="order_date"
    )
    demand_stats = demand_stats.rename(columns={"sku": "article_id"})

    if not stk.empty:
        latest_stock = (
            stk.sort_values("snapshot_date")
               .groupby("article_id", as_index=False).tail(1)
               [["article_id", "stock_qty", "stock_value_sek"]]
               .rename(columns={"stock_value_sek": "value_sek"})
        )
    else:
        latest_stock = pd.DataFrame({
            "article_id": pd.Series(dtype="object"),
            "stock_qty": pd.Series(dtype="float64"),
            "value_sek": pd.Series(dtype="float64"),
        })

    df = items.rename(columns={"unit_cost_sek": "unit_cost"}).merge(
        demand_stats, on="article_id", how="left"
    )
    df = df.merge(latest_stock, on="article_id", how="left")
    df["stock_qty"] = df["stock_qty"].fillna(0.0)
    df["value_sek"] = df["value_sek"].fillna(0.0)
    df["avg_daily_demand"] = df["avg_daily_demand"].fillna(0.0)
    df["days_since_last_movement"] = (as_of - pd.to_datetime(df["last_movement_date"])).dt.days
    # classify_abc/xyz/trend don't read "sku", but keeping it aliased to
    # article_id costs nothing and matches the vendored modules' usual
    # input shape, in case a caller reuses matrix_summary() etc. downstream.
    df["sku"] = df["article_id"]

    df = classify_abc(df)
    df = classify_xyz(df)
    df = classify_trend(df)

    history_for_sbc = build_demand_series(ob, items, freq="W").rename(
        columns={"article_id": "sku", "qty_ordered": "qty"}
    )
    sbc = classify_sbc(history_for_sbc).rename(columns={"sku": "article_id"})[["article_id", "sbc_class"]]
    df = df.merge(sbc, on="article_id", how="left")

    df["is_new_item"] = flag_new_item(df, as_of, new_item_days)
    df["is_becoming_obsolete"] = flag_obsolescence(df)
    df["is_stale_with_stock"] = flag_stale_with_stock(df)

    return df


def flag_new_item(items_or_segment: pd.DataFrame, as_of: pd.Timestamp,
                  new_item_days: int = DEFAULT_NEW_ITEM_DAYS) -> pd.Series:
    """True where the article's created_date falls within `new_item_days`
    of `as_of` -- "short history" per docs/FORECAST_SPEC.md Phase 3,
    operationalised as calendar age rather than periods-observed (an
    article launched 10 days before as_of is "new" regardless of whether
    it already sold twice)."""
    age_days = (as_of - items_or_segment["created_date"]).dt.days
    return (age_days >= 0) & (age_days <= new_item_days)


def flag_obsolescence(segment_df: pd.DataFrame) -> pd.Series:
    """trend_class in {declining, stopped} AND days_since_last_movement >=
    RECENCY_DEAD (180, the same constant analysis/segmentation.py already
    uses to escalate DOS-based status to dead_stock -- reused, not
    reinvented, for consistency with how "genuinely stopped" is judged
    everywhere else in this codebase).

    The trend_class condition ALONE was tried first and rejected by
    measurement, not by inspection: validated against
    datagen/v1/facit_dolda_egenskaper.csv (tests/test_segmentation_facit.py),
    trend_class in {declining, stopped} alone gave 90.6% recall but only
    13.9% precision -- it fires on ~44% of ALL articles in this
    intermittent/lumpy-dominated demo set (1,326 of 3,000), because a
    routine multi-week gap in sporadic ordering looks identical to genuine
    decline inside a single recent-vs-prior 3-month window comparison.
    Adding the days_since_last_movement>=180 gate cut false positives
    substantially (precision 13.9% -> 36.9%) at a real recall cost (90.6%
    -> 72.4%) -- reported honestly in that test as still below the spec's
    *(initial)* 80%/70% targets, not tuned further to force a pass. A
    genuinely better detector belongs to a forecast-based signal
    (analysis/demand_forecast.py:forecast_dead_stock_risk(), which compares
    an actual SBC-routed forecast against current status rather than a
    fixed two-window ratio) -- a Phase 4+ concern, flagged here rather than
    attempted now."""
    return (
        segment_df["trend_class"].isin(["declining", "stopped"])
        & (segment_df["days_since_last_movement"] >= RECENCY_DEAD)
    )


def flag_stale_with_stock(segment_df: pd.DataFrame) -> pd.Series:
    """True where the article holds stock but has shown no demand at all
    in the observed window. No facit ground-truth column validates this
    one directly (unlike is_new_item/is_becoming_obsolete) -- reported as
    an additional operational flag, not a metric with a recall/precision
    claim behind it."""
    return (segment_df["stock_qty"] > 0) & (segment_df["avg_daily_demand"] <= 0)
