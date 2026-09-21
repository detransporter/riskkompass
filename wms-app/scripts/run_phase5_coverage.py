#!/usr/bin/env python3
"""Phase 5 coverage evaluation (docs/FORECAST_SPEC.md): for every real,
historical purchase-order receipt in the demo data, predict the lead-time
demand distribution using ONLY data available before that PO was placed
(point-in-time correct), then check whether what actually happened
(realized demand over the REALIZED lead time + review period, the actual
receipt date this PO took) fell inside the predicted interval.

This tests against real historical replenishment events, not synthetic
Monte Carlo draws on both sides -- the predicted distribution is
simulated, but the thing it's scored against is a real (article, PO)
outcome that really happened in the data.

Calibration/test split is BY TIME (first ~60% of PO receipts
chronologically = calibration set the conformal correction is fit on,
last ~40% = held-out test set coverage is reported on) -- not a random
split, which would let information about "what a typical week's demand
looks like" leak across the split in a way a real deployment never gets.
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from forecasting.data import build_demand_series, load_inbound, load_items, load_outbound, load_stock
from forecasting.probabilistic import (
    apply_conformal_correction,
    build_supplier_lead_time_table,
    conformal_correction,
    lead_time_demand_distribution,
    supplier_lead_time_samples,
)
from forecasting.segmentation import build_segment_table

QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
REVIEW_PERIOD_DAYS = 7


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-po-lines", type=int, default=None, help="Subsample for speed (default: all)")
    parser.add_argument("--n-simulations", type=int, default=300)
    parser.add_argument("--calibration-frac", type=float, default=0.6)
    parser.add_argument("--out-csv", default="data/phase5_coverage_events.csv")
    args = parser.parse_args()

    t0 = time.time()
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    inbound = load_inbound("data/demo/inleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    print(f"[{time.time()-t0:.1f}s] loaded demo data")

    t0 = time.time()
    segment_table = build_segment_table(outbound, items, stock)
    segment_lookup = segment_table.set_index("article_id")["sbc_class"]
    supplier_by_article = items.set_index("article_id")["supplier_id"]
    print(f"[{time.time()-t0:.1f}s] segmentation done")

    t0 = time.time()
    series = build_demand_series(outbound, items, freq="W")
    lt_table = build_supplier_lead_time_table(inbound)
    print(f"[{time.time()-t0:.1f}s] demand series + lead-time table built "
          f"({len(lt_table)} received PO lines)")

    po_lines = lt_table.sort_values("po_date").reset_index(drop=True)
    if args.n_po_lines:
        po_lines = po_lines.sample(n=min(args.n_po_lines, len(po_lines)), random_state=42) \
            .sort_values("po_date").reset_index(drop=True)

    outbound_by_article = {aid: g.sort_values("order_date") for aid, g in outbound.groupby("article_id")}
    series_by_article = {aid: g.sort_values("period") for aid, g in series.groupby("article_id")}

    t0 = time.time()
    rows = []
    for _, po in po_lines.iterrows():
        article_id = po["article_id"]
        supplier_id = po["supplier_id"]
        po_date = po["po_date"]
        receipt_date = po["receipt_date"]

        g = series_by_article.get(article_id)
        if g is None:
            continue
        train = g[g["period"] <= po_date]["qty_ordered"]
        if train.empty:
            continue

        lead_samples = supplier_lead_time_samples(
            lt_table, supplier_id, as_of=po_date, exclude_po=(po["po_number"], po["po_line"]))

        predicted = lead_time_demand_distribution(
            train, lead_samples, review_period_days=REVIEW_PERIOD_DAYS, period_days=7,
            n_simulations=args.n_simulations, quantiles=QUANTILES, seed=42,
        )

        window_end = receipt_date + pd.Timedelta(days=REVIEW_PERIOD_DAYS)
        ob = outbound_by_article.get(article_id)
        if ob is None:
            actual = 0.0
        else:
            mask = (ob["order_date"] >= po_date) & (ob["order_date"] <= window_end)
            actual = float(ob.loc[mask, "qty_ordered"].sum())

        row = {
            "article_id": article_id, "supplier_id": supplier_id,
            "po_date": po_date, "receipt_date": receipt_date,
            "segment": segment_lookup.get(article_id), "actual": actual,
        }
        for q in QUANTILES:
            row[f"q{int(round(q*100))}"] = predicted["quantiles"][q]
        rows.append(row)

    events = pd.DataFrame(rows)
    events.to_csv(args.out_csv, index=False)
    print(f"[{time.time()-t0:.1f}s] built {len(events)} coverage events, written to {args.out_csv}")

    split_idx = int(len(events) * args.calibration_frac)
    calib = events.iloc[:split_idx]
    test = events.iloc[split_idx:]
    print(f"calibration set: {len(calib)} events (up to {calib['po_date'].max()})")
    print(f"test set: {len(test)} events (from {test['po_date'].min()})")

    interval_pairs = [(0.05, 0.95, "90%"), (0.1, 0.9, "80%")]
    print("\n=== Coverage per segment: raw vs conformal-calibrated ===")
    segments = ["smooth", "erratic", "intermittent", "lumpy", "ALL"]
    for lo_q, hi_q, label in interval_pairs:
        alpha = 1 - (hi_q - lo_q)
        print(f"\n--- Nominal {label} interval (q{int(lo_q*100)}-q{int(hi_q*100)}, target 87-93% "
              f"empirical coverage for the 90% case) ---")
        for segment in segments:
            calib_seg = calib if segment == "ALL" else calib[calib["segment"] == segment]
            test_seg = test if segment == "ALL" else test[test["segment"] == segment]
            if len(test_seg) < 5 or len(calib_seg) < 5:
                print(f"{segment:>14}: too few events (calib={len(calib_seg)}, test={len(test_seg)}) -- skipped")
                continue

            lo_col, hi_col = f"q{int(lo_q*100)}", f"q{int(hi_q*100)}"
            raw_coverage = ((test_seg["actual"] >= test_seg[lo_col]) &
                           (test_seg["actual"] <= test_seg[hi_col])).mean()

            correction = conformal_correction(
                calib_seg["actual"].to_numpy(), calib_seg[lo_col].to_numpy(),
                calib_seg[hi_col].to_numpy(), alpha=alpha,
            )
            cal_lo, cal_hi = apply_conformal_correction(test_seg[lo_col], test_seg[hi_col], correction)
            calibrated_coverage = ((test_seg["actual"] >= cal_lo) & (test_seg["actual"] <= cal_hi)).mean()

            print(f"{segment:>14}: raw={raw_coverage:.1%}  calibrated={calibrated_coverage:.1%}  "
                  f"(correction={correction:+.2f}, n={len(test_seg)})")


if __name__ == "__main__":
    main()
