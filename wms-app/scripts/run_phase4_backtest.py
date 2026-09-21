#!/usr/bin/env python3
"""Runs the full Phase 4 evaluation (docs/FORECAST_SPEC.md) on the demo
data/demo/ estate: backtests every per-article model (Phase 2 baselines +
Phase 4's Croston/SBA/TSB/ETS/Theta/bootstrap) plus the global LightGBM
model, then reports pinball loss @ q=0.9 per SBC segment against the best
baseline -- the exact numbers the working agreement requires before any
"the new model is better" claim is allowed.

The global model is run on a smaller item subset than the per-article
models by default (see --global-n-items): retraining a panel-wide
LightGBM model at every origin/horizon/quantile is far more expensive
than a per-article statsforecast call, and this script's job is to
produce real, honestly-scoped numbers on a laptop in a reasonable time,
not to guess at full-3000-item timing. The measured runtime for each
stage is printed so a future full-scale run can be budgeted for.
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from forecasting.backtest import run_backtest, run_global_backtest
from forecasting.data import load_items, load_outbound, load_stock, build_demand_series
from forecasting.models.baselines import (
    moving_average_forecast, naive_forecast, seasonal_naive_forecast, ses_forecast,
)
from forecasting.models.ensemble import score_models_by_segment
from forecasting.models.intermittent import bootstrap_forecast, croston_forecast, sba_forecast, tsb_forecast
from forecasting.models.statistical import ets_forecast, theta_forecast
from forecasting.segmentation import build_segment_table

QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)

PER_ARTICLE_MODELS = {
    "naive": naive_forecast,
    "seasonal_naive": seasonal_naive_forecast,
    "moving_average": moving_average_forecast,
    "ses": ses_forecast,
    "croston": croston_forecast,
    "sba": sba_forecast,
    "tsb": tsb_forecast,
    "bootstrap": bootstrap_forecast,
    "ets": ets_forecast,
    "theta": theta_forecast,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-items", type=int, default=None, help="Subset for per-article models (default: all)")
    parser.add_argument("--global-n-items", type=int, default=500, help="Subset for the global GBM model")
    parser.add_argument("--origin-step", type=int, default=13)
    parser.add_argument("--fixed-horizons", type=int, nargs="+", default=[4, 13, 26])
    parser.add_argument("--out-csv", default="data/phase4_backtest_results.csv")
    args = parser.parse_args()

    t0 = time.time()
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    if args.n_items:
        items = items.head(args.n_items).copy()
        outbound = outbound[outbound["article_id"].isin(items["article_id"])]
        stock = stock[stock["article_id"].isin(items["article_id"])]
    print(f"[{time.time()-t0:.1f}s] loaded {len(items)} items, {len(outbound)} outbound rows")

    t0 = time.time()
    segment_table = build_segment_table(outbound, items, stock)
    segment_lookup = segment_table.set_index("article_id")["sbc_class"]
    print(f"[{time.time()-t0:.1f}s] segmentation done -- "
          f"{segment_table['sbc_class'].value_counts().to_dict()}")

    t0 = time.time()
    series = build_demand_series(outbound, items, freq="W")
    print(f"[{time.time()-t0:.1f}s] demand series built -- {len(series)} rows, "
          f"{series['period'].nunique()} periods")

    t0 = time.time()
    per_article_results = run_backtest(
        series, items, PER_ARTICLE_MODELS,
        fixed_horizons=tuple(args.fixed_horizons), origin_step=args.origin_step,
        quantiles=QUANTILES,
    )
    print(f"[{time.time()-t0:.1f}s] per-article backtest done -- {len(per_article_results)} rows, "
          f"{len(PER_ARTICLE_MODELS)} models")

    global_items = items.head(args.global_n_items).copy()
    global_article_ids = set(global_items["article_id"])
    global_series = series[series["article_id"].isin(global_article_ids)]
    t0 = time.time()
    global_results = run_global_backtest(
        global_series, global_items,
        fixed_horizons=tuple(args.fixed_horizons), origin_step=args.origin_step,
        quantiles=QUANTILES,
    )
    print(f"[{time.time()-t0:.1f}s] global GBM backtest done on {len(global_items)} items -- "
          f"{len(global_results)} rows")

    all_results = pd.concat([per_article_results, global_results], ignore_index=True)
    all_results.to_csv(args.out_csv, index=False)
    print(f"results written to {args.out_csv} ({len(all_results)} rows total)")

    scores = score_models_by_segment(all_results, segment_lookup, quantile=0.9)
    print("\n=== Pinball loss @ q0.9 per segment x model (lower is better) ===")
    print(scores.to_string(index=False))

    print("\n=== Best model per segment, and FVA vs best baseline ===")
    print("(baseline is re-scored on exactly the same (article,origin,horizon) rows as the\n"
          " candidate model before computing FVA -- global_gbm ran on a smaller item subset\n"
          " than the per-article models, and comparing its score against the full-population\n"
          " baseline average would be an unfair, misleadingly favourable comparison whenever\n"
          " its subset happens to be easier than the population average.)")
    baseline_names = {"naive", "seasonal_naive", "moving_average", "ses"}
    q90_col = "q90"
    for segment in sorted(scores["segment"].dropna().unique()):
        seg_scores = scores[scores["segment"] == segment].sort_values("pinball_q90")
        best_row = seg_scores.iloc[0]
        baseline_rows = seg_scores[seg_scores["model"].isin(baseline_names)]
        if baseline_rows.empty:
            continue
        best_baseline_name = baseline_rows.sort_values("pinball_q90").iloc[0]["model"]

        seg_mask = all_results["article_id"].map(segment_lookup) == segment
        best_keys = all_results[seg_mask & (all_results["model"] == best_row["model"])][
            ["article_id", "origin_period", "horizon"]]
        baseline_all = all_results[seg_mask & (all_results["model"] == best_baseline_name)]
        baseline_matched = baseline_all.merge(best_keys, on=["article_id", "origin_period", "horizon"], how="inner")

        from forecasting.metrics import pinball_loss
        baseline_q90_matched = pinball_loss(baseline_matched["actual"], baseline_matched[q90_col], 0.9) \
            if not baseline_matched.empty else float("nan")
        fva = 100 * (baseline_q90_matched - best_row["pinball_q90"]) / baseline_q90_matched \
            if baseline_q90_matched else float("nan")
        note = "" if len(baseline_matched) == len(best_keys) else \
            f"  [WARNING: only matched {len(baseline_matched)}/{len(best_keys)} rows]"
        print(f"{segment:>14}: best={best_row['model']:<15} pinball_q90={best_row['pinball_q90']:.3f}  "
              f"| best_baseline={best_baseline_name:<15} pinball_q90(matched)={baseline_q90_matched:.3f}  "
              f"| FVA={fva:+.1f}%  (n={best_row['n_observations']}){note}")


if __name__ == "__main__":
    main()
