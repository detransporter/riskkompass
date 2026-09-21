#!/usr/bin/env python3
"""Phase 6 completeness check (docs/FORECAST_SPEC.md): "explanations exist
for all items and reference real drivers" -- computes a policy AND an
explanation for every article in the demo set, verifies none crash or
produce an empty/placeholder explanation, and reports summary statistics
(target service level distribution, how many items hit the ABC fallback
vs. a real margin, safety stock as % of expected lead-time demand per
segment).
"""

from __future__ import annotations

import time

import pandas as pd

from forecasting.data import build_demand_series, load_inbound, load_items, load_outbound, load_stock
from forecasting.explain import explain_policy
from forecasting.policy import compute_policy
from forecasting.probabilistic import build_supplier_lead_time_table, supplier_lead_time_samples
from forecasting.segmentation import build_segment_table

N_SIMULATIONS = 300


def main() -> None:
    t0 = time.time()
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    inbound = load_inbound("data/demo/inleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    print(f"[{time.time()-t0:.1f}s] loaded demo data, {len(items)} items")

    t0 = time.time()
    segment_table = build_segment_table(outbound, items, stock)
    segment_lookup = segment_table.set_index("article_id")["sbc_class"]
    abc_lookup = segment_table.set_index("article_id")["abc_class"]
    series = build_demand_series(outbound, items, freq="W")
    lt_table = build_supplier_lead_time_table(inbound)
    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in series.groupby("article_id")}
    print(f"[{time.time()-t0:.1f}s] segmentation + demand series + lead-time table built")

    t0 = time.time()
    rows = []
    n_errors = 0
    for _, item in items.iterrows():
        article_id = item["article_id"]
        demand_history = series_by_article.get(article_id, pd.Series([], dtype=float))
        lead_samples = supplier_lead_time_samples(lt_table, item["supplier_id"])
        abc_class = abc_lookup.get(article_id)
        sbc_class = segment_lookup.get(article_id)

        try:
            policy = compute_policy(
                demand_history, lead_samples, unit_cost=item["unit_cost_sek"],
                abc_class=abc_class, margin_per_unit=None,  # demo data contract has no margin column
                moq=item["moq"], order_multiple=item["order_multiple"],
                n_simulations=N_SIMULATIONS,
            )
            explanation = explain_policy(
                article_id, item["description"], policy, sbc_class, demand_history, lead_samples,
            )
        except Exception as exc:  # noqa: BLE001 -- completeness check: report, don't crash the whole run
            n_errors += 1
            print(f"ERROR on {article_id}: {exc}")
            continue

        assert isinstance(explanation, str) and len(explanation) > 20, \
            f"{article_id}: explanation missing or too short"

        rows.append({
            "article_id": article_id, "abc_class": abc_class, "sbc_class": sbc_class,
            "target_service_level": policy["target_service_level"],
            "margin_based": policy["margin_based"],
            "reorder_point": policy["reorder_point"],
            "safety_stock": policy["safety_stock"],
            "expected_lead_time_demand": policy["expected_lead_time_demand"],
            "order_quantity": policy["order_quantity"],
            "n_lead_time_samples": len(lead_samples),
        })

    results = pd.DataFrame(rows)
    print(f"[{time.time()-t0:.1f}s] computed policy + explanation for {len(results)}/{len(items)} items "
          f"({n_errors} errors)")
    results.to_csv("data/phase6_policy_results.csv", index=False)

    print(f"\nMargin-based service level: {results['margin_based'].sum()}/{len(results)} items")
    print(f"\nTarget service level by ABC class:")
    print(results.groupby("abc_class")["target_service_level"].agg(["mean", "count"]).to_string())

    print(f"\nSafety stock as % of expected lead-time demand, by segment:")
    results["ss_pct"] = 100 * results["safety_stock"] / results["expected_lead_time_demand"].replace(0, pd.NA)
    print(results.groupby("sbc_class")["ss_pct"].agg(["mean", "median", "count"]).to_string())

    print(f"\nItems with fewer than 5 lead-time samples (fell back to review-period-only): "
          f"{(results['n_lead_time_samples'] < 5).sum()}/{len(results)}")

    print("\n=== Sample explanations (3 different segments) ===")
    for segment in ["smooth", "intermittent", "lumpy"]:
        sample = results[results["sbc_class"] == segment].head(1)
        if sample.empty:
            continue
        article_id = sample.iloc[0]["article_id"]
        item = items[items["article_id"] == article_id].iloc[0]
        demand_history = series_by_article.get(article_id, pd.Series([], dtype=float))
        lead_samples = supplier_lead_time_samples(lt_table, item["supplier_id"])
        policy = compute_policy(demand_history, lead_samples, unit_cost=item["unit_cost_sek"],
                                abc_class=abc_lookup.get(article_id), moq=item["moq"],
                                order_multiple=item["order_multiple"], n_simulations=N_SIMULATIONS)
        text = explain_policy(article_id, item["description"], policy, segment, demand_history, lead_samples)
        print(f"\n[{segment}] {text}")


if __name__ == "__main__":
    main()
