#!/usr/bin/env python3
"""Phase 10 validation on real data (docs/FORECAST_SPEC.md): runs the
SAME backtest + SBC segmentation + FVA-per-segment machinery Phase 2-4
already built and validated on synthetic data, against the M3 competition
dataset (Makridakis & Hibon 2000) instead -- a real, independently
collected forecasting benchmark, not this project's own data generator.

Scope, stated honestly up front: M3 is a bare (series_id, date, value)
benchmark with no items/inbound/lead-time/stock data at all, so only
Phases 2-4 (forecasting accuracy + segmentation) can be validated this
way. Phases 5-7 (lead-time demand, policy, simulation) need real
inbound/PO data M3 does not have -- genuinely out of scope for this
dataset, not a gap in this script. global_gbm is also skipped here: its
whole value proposition is pooling across item ATTRIBUTES (category,
cost, lead time) M3 doesn't provide either, so a degraded panel model
with none of those features would not be a fair test of the real thing.

Run `curl -sL "https://zenodo.org/api/records/4656298/files/m3_monthly_dataset.zip/content" -o data/m3/m3_monthly_dataset.zip && unzip -o data/m3/m3_monthly_dataset.zip -d data/m3/`
first if data/m3/m3_monthly_dataset.tsf does not exist yet.
"""

from __future__ import annotations

import time

import pandas as pd

from analysis.demand_forecast import classify_sbc
from forecasting.backtest import run_backtest
from forecasting.datasets.m3 import load_m3_monthly_tsf
from forecasting.models.baselines import (
    moving_average_forecast, naive_forecast, seasonal_naive_forecast, ses_forecast,
)
from forecasting.models.ensemble import score_models_by_segment
from forecasting.models.intermittent import bootstrap_forecast, croston_forecast, sba_forecast, tsb_forecast
from forecasting.models.statistical import ets_forecast, theta_forecast

QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
FIXED_HORIZONS = (3, 6, 12)  # months -- the monthly-cadence analogue of the demo set's 4/13/26 WEEKS
MIN_TRAIN_PERIODS = 24        # 2 years
ORIGIN_STEP = 6                # semi-annual origins -- M3 series average ~117 months, not 208 weeks

MODELS = {
    "naive": naive_forecast, "seasonal_naive": seasonal_naive_forecast,
    "moving_average": moving_average_forecast, "ses": ses_forecast,
    "croston": croston_forecast, "sba": sba_forecast, "tsb": tsb_forecast, "bootstrap": bootstrap_forecast,
    "ets": ets_forecast, "theta": theta_forecast,
}


def main() -> None:
    t0 = time.time()
    series = load_m3_monthly_tsf("data/m3/m3_monthly_dataset.tsf")
    print(f"[{time.time()-t0:.1f}s] loaded M3 monthly: {series['article_id'].nunique()} series, "
          f"{len(series)} observations")

    # run_backtest() needs an `items` frame with lead_time_days -- M3 has
    # no such concept, so every series gets None (lead_time_horizon_periods()
    # already handles that gracefully: falls back to the review period alone).
    items = pd.DataFrame({"article_id": series["article_id"].unique(), "lead_time_days": None})

    t0 = time.time()
    sbc_input = series.rename(columns={"article_id": "sku", "qty_ordered": "qty"})
    sbc = classify_sbc(sbc_input)
    segment_lookup = sbc.set_index("sku")["sbc_class"]
    print(f"[{time.time()-t0:.1f}s] SBC segmentation -- {sbc['sbc_class'].value_counts().to_dict()}")

    t0 = time.time()
    # review_period_days=30 (one month) so the "lead_time" horizon label,
    # even though unused here (all lead_time_days are None), stays on the
    # same monthly footing as the fixed horizons rather than defaulting to
    # backtest.py's own weekly review_period_days=7.
    results = run_backtest(
        series, items, MODELS, fixed_horizons=FIXED_HORIZONS,
        min_train_periods=MIN_TRAIN_PERIODS, origin_step=ORIGIN_STEP,
        review_period_days=30, quantiles=QUANTILES,
    )
    print(f"[{time.time()-t0:.1f}s] backtest done -- {len(results)} rows, {len(MODELS)} models")
    results.to_csv("data/phase10_m3_backtest_results.csv", index=False)

    scores = score_models_by_segment(results, segment_lookup, quantile=0.9)
    print("\n=== Pinball loss @ q0.9 per segment x model (M3, real data) ===")
    print(scores.to_string(index=False))

    print("\n=== Best model per segment, FVA vs best baseline (M3, real data) ===")
    baseline_names = {"naive", "seasonal_naive", "moving_average", "ses"}
    for segment in sorted(scores["segment"].dropna().unique()):
        seg_scores = scores[scores["segment"] == segment].sort_values("pinball_q90")
        best_row = seg_scores.iloc[0]
        baseline_rows = seg_scores[seg_scores["model"].isin(baseline_names)]
        if baseline_rows.empty:
            continue
        best_baseline = baseline_rows.sort_values("pinball_q90").iloc[0]
        fva = 100 * (best_baseline["pinball_q90"] - best_row["pinball_q90"]) / best_baseline["pinball_q90"] \
            if best_baseline["pinball_q90"] else float("nan")
        print(f"{str(segment):>14}: best={best_row['model']:<15} pinball_q90={best_row['pinball_q90']:.3f}  "
              f"| best_baseline={best_baseline['model']:<15} pinball_q90={best_baseline['pinball_q90']:.3f}  "
              f"| FVA={fva:+.1f}%  (n={best_row['n_observations']})")

    print("\nNOTE: Phases 5-7 (lead-time demand, policy, simulation) are NOT validated here --")
    print("M3 has no items/inbound/lead-time/stock data at all. See this script's own docstring.")


if __name__ == "__main__":
    main()
