#!/usr/bin/env python3
"""Phase 8 demonstration (docs/FORECAST_SPEC.md): runs every
forecasting/monitoring.py signal against real outputs already produced by
earlier phases -- Phase 4's backtest results (rolling bias), Phase 5's
coverage events (coverage breach), Phase 1's level-shift flag (demand
shift), and a fresh short-horizon forecast crossed with Phase 3's
segmentation (obsolescence risk) -- then reports how many articles each
signal actually flags on the demo set, and a small illustrative example
of the manual-override FVA mechanism (there is no real override history
in the demo data -- this can only be demonstrated, not backtested).
"""

from __future__ import annotations

import time

import pandas as pd

from forecasting.cleaning import flag_level_shifts
from forecasting.data import build_demand_series, load_items, load_outbound, load_stock
from forecasting.models.intermittent import tsb_forecast
from forecasting.monitoring import (
    compute_override_fva,
    detect_coverage_breach,
    detect_persistent_bias,
    generate_alerts,
    obsolescence_risk,
    record_override,
    rolling_error_by_origin,
    should_retrain,
)
from forecasting.segmentation import build_segment_table


def main() -> None:
    t0 = time.time()
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    print(f"[{time.time()-t0:.1f}s] loaded demo data")

    # ── 1. Rolling error + persistent bias, from Phase 4's own backtest ──
    t0 = time.time()
    backtest = pd.read_csv(
        "data/phase4_backtest_results.csv",
        usecols=["article_id", "model", "horizon_type", "origin_period", "actual", "forecast"],
    )
    single_slice = backtest[(backtest["model"] == "moving_average") & (backtest["horizon_type"] == "4w")]
    single_slice = single_slice.copy()
    single_slice["origin_period"] = pd.to_datetime(single_slice["origin_period"])
    rolling = rolling_error_by_origin(single_slice, window=4)
    bias_flags = detect_persistent_bias(rolling, bias_threshold=0.20, min_consecutive=3)
    print(f"[{time.time()-t0:.1f}s] rolling error computed on {single_slice['article_id'].nunique()} "
          f"articles (moving_average, 4w horizon) -- "
          f"{len(bias_flags)} articles show persistent bias (>=3 consecutive origins beyond +-20%)")

    # ── 2. Coverage breach, from Phase 5's own coverage events ────────────
    t0 = time.time()
    coverage_events = pd.read_csv("data/phase5_coverage_events.csv")
    coverage_breach = detect_coverage_breach(coverage_events, "q5", "q95", nominal=0.9, tolerance=0.05)
    print(f"[{time.time()-t0:.1f}s] coverage breach check -- segments flagged: "
          f"{coverage_breach[['segment', 'empirical_coverage', 'breach_direction']].to_dict('records') if not coverage_breach.empty else 'none'}")

    # ── 3. Demand shift, reusing Phase 1's flag_level_shifts unchanged ───
    t0 = time.time()
    series_for_shift = build_demand_series(outbound, items, freq="W")
    shift_flags = flag_level_shifts(series_for_shift)
    n_shifted = int(shift_flags.groupby(series_for_shift["article_id"]).any().sum())
    print(f"[{time.time()-t0:.1f}s] demand-shift flag (Phase 1, NOT CALIBRATED -- human-review signal "
          f"only, exactly as documented): {n_shifted}/{items['article_id'].nunique()} articles flagged "
          f"at least once")

    # ── 4. Obsolescence risk: current segmentation vs. a fresh forecast ──
    # Uses TSB, not naive_forecast: naive would repeat the LAST observed
    # value, which is 0 after any single empty period -- for the
    # intermittent/lumpy demand dominating this estate that is routine,
    # not a risk signal, the exact same false-positive trap Phase 3's own
    # flag_obsolescence() docstring already documents at length (trend_class
    # alone flagged 44% of all articles before a recency gate fixed it).
    # TSB's whole point (see forecasting/models/intermittent.py) is a
    # smoothed rate that decays gracefully instead of flipping to zero on
    # a routine gap -- the right tool already built for this, not a new
    # threshold invented here.
    t0 = time.time()
    segment_table = build_segment_table(outbound, items, stock)
    series_by_article = {aid: g.sort_values("period")["qty_ordered"]
                         for aid, g in series_for_shift.groupby("article_id")}
    risk_counts = {"emerging": 0, "confirmed": 0, "recovering": 0, "none": 0}
    for _, row in segment_table.iterrows():
        history = series_by_article.get(row["article_id"])
        if history is None or history.empty:
            continue
        forecast_point = tsb_forecast(history, horizon=4)["point"]
        risk = obsolescence_risk(bool(row["is_becoming_obsolete"]), forecast_point)
        risk_counts[risk] += 1
    print(f"[{time.time()-t0:.1f}s] obsolescence risk categorization: {risk_counts}")

    # ── 5. Auto-retrain trigger + sample alerts ───────────────────────────
    bias_flagged_articles = set(bias_flags["article_id"])
    coverage_breach_segments = set(coverage_breach["segment"]) if not coverage_breach.empty else set()
    shift_flagged_articles = set(series_for_shift.loc[shift_flags, "article_id"].unique())

    n_retrain = 0
    sample_alerts = []
    for _, row in segment_table.head(500).iterrows():
        article_id = row["article_id"]
        history = series_by_article.get(article_id)
        if history is None or history.empty:
            continue
        pb = article_id in bias_flagged_articles
        cb = row.get("sbc_class") in coverage_breach_segments
        ds = article_id in shift_flagged_articles
        if should_retrain(pb, cb, ds):
            n_retrain += 1

        forecast_point = tsb_forecast(history, horizon=4)["point"]
        risk = obsolescence_risk(bool(row["is_becoming_obsolete"]), forecast_point)
        pb_row = bias_flags[bias_flags["article_id"] == article_id].iloc[0].to_dict() if pb else None
        alerts = generate_alerts(article_id, row.get("description"), pb_row, None, ds, risk)
        sample_alerts.extend(alerts)

    print(f"\nOf the first 500 articles: {n_retrain} would trigger should_retrain()")
    print(f"Total alerts generated on those 500: {len(sample_alerts)}")
    by_type = pd.Series([a["type"] for a in sample_alerts]).value_counts()
    print(f"By type:\n{by_type.to_string()}")
    if sample_alerts:
        print(f"\nExample alert: {sample_alerts[0]}")

    # ── 6. Manual override + FVA -- illustrative, no real override history ──
    print("\n=== Manual override FVA -- illustrative example (no real override log exists yet) ===")
    overrides = []
    overrides = record_override(overrides, "A00001", "2026-06-01", model_forecast=50.0,
                                override_value=80.0, user="david", reason="känd kampanj nästa vecka")
    overrides = record_override(overrides, "A00002", "2026-06-01", model_forecast=30.0,
                                override_value=10.0, user="david", reason="kund har bytt leverantör")
    actuals = pd.Series({("A00001", "2026-06-01"): 75.0, ("A00002", "2026-06-01"): 32.0})
    fva = compute_override_fva(overrides, actuals)
    print(fva.to_string(index=False))


if __name__ == "__main__":
    main()
