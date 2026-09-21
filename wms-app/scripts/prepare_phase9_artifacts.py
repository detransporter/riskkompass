#!/usr/bin/env python3
"""Precomputes small summary artifacts for the Phase 9 Streamlit page
(views/forecast_demo.py) from the already-run Phase 4-8 outputs.

Why precompute rather than have the page recompute live: Phase 4's own
backtest results CSV is ~155MB / 1.6M rows -- loading that inside a
Streamlit page on every rerun would make the page unusably slow (and
Streamlit Cloud-class hosting has real memory limits, see
wms-app/CLAUDE.md's "Streamlit Deployment Checklist"). This script reads
the heavy intermediate files ONCE and writes small (KB-scale) summary
tables to data/phase9/ that the page actually loads. Only the "item view"
tab computes anything live -- a single article's own forecast/policy is
cheap (milliseconds), unlike re-scoring the whole 3,000-item panel.
"""

from __future__ import annotations

import time

import pandas as pd

from forecasting.cleaning import flag_censored, flag_level_shifts, flag_one_off_large_orders, flag_outliers
from forecasting.data import build_demand_series, load_inbound, load_items, load_outbound, load_stock
from forecasting.models.ensemble import score_models_by_segment
from forecasting.monitoring import detect_persistent_bias, generate_alerts, obsolescence_risk, rolling_error_by_origin
from forecasting.models.intermittent import tsb_forecast
from forecasting.segmentation import build_segment_table

OUT_DIR = "data/phase9"


def main() -> None:
    t0 = time.time()
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    inbound = load_inbound("data/demo/inleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    segment_table = build_segment_table(outbound, items, stock)
    print(f"[{time.time()-t0:.1f}s] loaded demo data + segmentation")

    # ── Overview KPIs ──────────────────────────────────────────────────
    overview = {
        "n_items": len(items),
        "n_outbound_rows": len(outbound),
        "n_inbound_rows": len(inbound),
        "segment_counts": segment_table["sbc_class"].value_counts().to_dict(),
        "abc_counts": segment_table["abc_class"].value_counts().to_dict(),
        "n_new_items": int(segment_table["is_new_item"].sum()),
        "n_becoming_obsolete": int(segment_table["is_becoming_obsolete"].sum()),
        "n_stale_with_stock": int(segment_table["is_stale_with_stock"].sum()),
    }
    pd.Series(overview).to_json(f"{OUT_DIR}/overview.json")
    print(f"[{time.time()-t0:.1f}s] overview.json written")

    # ── Phase 4: per-segment model scores (from the already-run backtest) ──
    t0 = time.time()
    segment_lookup = segment_table.set_index("article_id")["sbc_class"]
    backtest = pd.read_csv(
        "data/phase4_backtest_results.csv",
        usecols=["article_id", "model", "actual", "q90"],
    )
    scores = score_models_by_segment(backtest, segment_lookup, quantile=0.9)
    scores.to_csv(f"{OUT_DIR}/segment_scores.csv", index=False)
    print(f"[{time.time()-t0:.1f}s] segment_scores.csv written ({len(scores)} rows)")

    # ── Data quality summary (Phase 1's cleaning flags, whole demo set) ──
    t0 = time.time()
    series = build_demand_series(outbound, items, freq="W")
    censored = flag_censored(outbound)
    outliers = flag_outliers(series)
    one_off = flag_one_off_large_orders(series)
    shifts = flag_level_shifts(series)
    quality = {
        "n_censored_lines": int(censored.sum()),
        "n_censored_total_lines": len(censored),
        "n_outlier_periods": int(outliers.sum()),
        "n_one_off_periods": int(one_off.sum()),
        "n_level_shift_periods": int(shifts.sum()),
        "n_articles_with_level_shift": int(series.loc[shifts, "article_id"].nunique()),
        "n_total_periods": len(series),
        "n_total_articles": items["article_id"].nunique(),
    }
    pd.Series(quality).to_json(f"{OUT_DIR}/data_quality.json")
    print(f"[{time.time()-t0:.1f}s] data_quality.json written")

    # ── Phase 8: alert sample (first 500 articles, TSB-based obsolescence) ──
    t0 = time.time()
    backtest_ma = backtest[backtest["model"] == "moving_average"]
    # rolling_error_by_origin needs origin_period + forecast; re-read that slice with those columns
    backtest_ma_full = pd.read_csv(
        "data/phase4_backtest_results.csv",
        usecols=["article_id", "model", "horizon_type", "origin_period", "actual", "forecast"],
    )
    backtest_ma_full = backtest_ma_full[
        (backtest_ma_full["model"] == "moving_average") & (backtest_ma_full["horizon_type"] == "4w")
    ].copy()
    backtest_ma_full["origin_period"] = pd.to_datetime(backtest_ma_full["origin_period"])
    rolling = rolling_error_by_origin(backtest_ma_full, window=4)
    bias_flags = detect_persistent_bias(rolling, bias_threshold=0.20, min_consecutive=3)
    bias_flagged_articles = set(bias_flags["article_id"])

    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in series.groupby("article_id")}
    shift_flagged_articles = set(series.loc[shifts, "article_id"].unique())

    alert_rows = []
    for _, row in segment_table.head(500).iterrows():
        article_id = row["article_id"]
        history = series_by_article.get(article_id)
        if history is None or history.empty:
            continue
        pb = article_id in bias_flagged_articles
        ds = article_id in shift_flagged_articles
        forecast_point = tsb_forecast(history, horizon=4)["point"]
        risk = obsolescence_risk(bool(row["is_becoming_obsolete"]), forecast_point)
        pb_row = bias_flags[bias_flags["article_id"] == article_id].iloc[0].to_dict() if pb else None
        alerts = generate_alerts(article_id, row.get("description"), pb_row, None, ds, risk)
        alert_rows.extend(alerts)
    pd.DataFrame(alert_rows).to_csv(f"{OUT_DIR}/alerts_sample.csv", index=False)
    print(f"[{time.time()-t0:.1f}s] alerts_sample.csv written ({len(alert_rows)} alerts on 500 articles)")

    print("\nAll Phase 9 artifacts written to data/phase9/")


if __name__ == "__main__":
    main()
