#!/usr/bin/env python3
"""Phase 7 proof of value (docs/FORECAST_SPEC.md): replays REAL historical
demand for every demo article under policy A (the item's existing ERP
reorder_point/safety_stock, already in artiklar.csv) and policy B
(Phase 6's quantile-based policy), with a SHARED order quantity and the
SAME seeded lead-time draws for both (see forecasting/simulate.py's
compare_policies() docstring for why) -- then reports fill rate, stock
value, stockouts, turns, and dead-stock share, overall and per SBC
segment.

Also traces a service-vs-stock-value FRONTIER by re-running policy B at
several different target service levels (80/85/90/95/98%) instead of its
own critical-ratio-derived one -- "the baselines" the spec's Phase 7
asks the frontier to include has no other defined meaning at the policy
level (Phase 2's "baselines" were forecast MODELS, a different concept);
this interpretation is stated explicitly here rather than assumed
silently.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from forecasting.data import build_demand_series, load_inbound, load_items, load_outbound, load_stock
from forecasting.policy import DEFAULT_HOLDING_COST_RATE, DEFAULT_ORDERING_COST_SEK, apply_moq_and_multiple, \
    economic_order_quantity
from forecasting.probabilistic import build_supplier_lead_time_table, supplier_lead_time_samples
from forecasting.segmentation import build_segment_table
from forecasting.simulate import compare_policies, simulate_policy

N_SIMULATIONS_FOR_POLICY = 300  # for computing policy B's own reorder point (Phase 6 machinery)
FRONTIER_SERVICE_LEVELS = [0.80, 0.85, 0.90, 0.95, 0.98]


def _policy_b_reorder_point(demand_history: pd.Series, lead_samples: np.ndarray,
                            target_service_level: float, seed: int = 42) -> float:
    from forecasting.probabilistic import lead_time_demand_distribution
    dist = lead_time_demand_distribution(
        demand_history, lead_samples, quantiles=(target_service_level,),
        n_simulations=N_SIMULATIONS_FOR_POLICY, seed=seed,
    )
    return dist["quantiles"][target_service_level]


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
    series_by_article = {aid: g.sort_values("period")["qty_ordered"].to_numpy()
                         for aid, g in series.groupby("article_id")}
    print(f"[{time.time()-t0:.1f}s] segmentation + demand series + lead-time table built")

    t0 = time.time()
    rows = []
    for _, item in items.iterrows():
        article_id = item["article_id"]
        demand_periods = series_by_article.get(article_id)
        if demand_periods is None or len(demand_periods) < 10:
            continue

        lead_samples = supplier_lead_time_samples(lt_table, item["supplier_id"])
        unit_cost = item["unit_cost_sek"]
        holding_cost_per_unit_year = DEFAULT_HOLDING_COST_RATE * unit_cost
        avg_period_demand = float(pd.Series(demand_periods).tail(52).mean())
        annual_demand = avg_period_demand * 52
        order_qty = economic_order_quantity(annual_demand, DEFAULT_ORDERING_COST_SEK, holding_cost_per_unit_year)
        order_qty = apply_moq_and_multiple(order_qty, item["moq"], item["order_multiple"])
        if order_qty <= 0:
            continue

        reorder_point_a = float(item["reorder_point"])
        abc_class = abc_lookup.get(article_id)
        target_service_level = {"A": 0.95, "B": 0.90, "C": 0.85}.get(abc_class, 0.85)
        demand_history_series = pd.Series(demand_periods)
        reorder_point_b = _policy_b_reorder_point(demand_history_series, lead_samples, target_service_level)

        result = compare_policies(demand_periods, reorder_point_a, reorder_point_b, order_qty, lead_samples)

        rows.append({
            "article_id": article_id, "abc_class": abc_class, "sbc_class": segment_lookup.get(article_id),
            "unit_cost": unit_cost,
            "fill_rate_a": result["policy_a"]["fill_rate"], "fill_rate_b": result["policy_b"]["fill_rate"],
            "avg_stock_a": result["policy_a"]["avg_stock"], "avg_stock_b": result["policy_b"]["avg_stock"],
            "stockout_periods_a": result["policy_a"]["n_stockout_periods"],
            "stockout_periods_b": result["policy_b"]["n_stockout_periods"],
            "n_periods": result["policy_a"]["n_periods"],
            "total_demand": result["policy_a"]["total_demand"],
            "reorder_point_a": reorder_point_a, "reorder_point_b": reorder_point_b,
        })

    results = pd.DataFrame(rows)
    print(f"[{time.time()-t0:.1f}s] simulated {len(results)} items under both policies")
    results.to_csv("data/phase7_simulation_results.csv", index=False)

    results["stock_value_a"] = results["avg_stock_a"] * results["unit_cost"]
    results["stock_value_b"] = results["avg_stock_b"] * results["unit_cost"]

    def _portfolio_summary(df: pd.DataFrame) -> dict:
        total_demand = df["total_demand"].sum()
        weighted_fill_a = (df["fill_rate_a"] * df["total_demand"]).sum() / total_demand if total_demand else float("nan")
        weighted_fill_b = (df["fill_rate_b"] * df["total_demand"]).sum() / total_demand if total_demand else float("nan")
        # "Dead" here = zero demand across the ENTIRE simulated window (not
        # Phase 3's 180-day recency threshold -- this simulation only has
        # one data point per item, its whole-window total, so it can only
        # ask "did this ever move at all") yet the policy still holds
        # average stock for it -- stock tied up with no signal to justify it.
        dead_mask = df["total_demand"] == 0
        return {
            "n_items": len(df),
            "fill_rate_a": weighted_fill_a, "fill_rate_b": weighted_fill_b,
            "stock_value_a": df["stock_value_a"].sum(), "stock_value_b": df["stock_value_b"].sum(),
            "dead_share_a": (dead_mask & (df["avg_stock_a"] > 0)).mean(),
            "dead_share_b": (dead_mask & (df["avg_stock_b"] > 0)).mean(),
        }

    print("\n=== Policy A (current ERP) vs Policy B (Phase 6 quantile-based), demand-weighted ===")
    overall = _portfolio_summary(results)
    print(f"{'ALL':>14}: fill_rate A={overall['fill_rate_a']:.1%} B={overall['fill_rate_b']:.1%}  |  "
          f"stock_value A={overall['stock_value_a']:,.0f} SEK  B={overall['stock_value_b']:,.0f} SEK  |  "
          f"dead_share A={overall['dead_share_a']:.1%} B={overall['dead_share_b']:.1%}  "
          f"(n={overall['n_items']})".replace(",", " "))
    for segment in ["smooth", "erratic", "intermittent", "lumpy"]:
        seg_df = results[results["sbc_class"] == segment]
        if seg_df.empty:
            continue
        s = _portfolio_summary(seg_df)
        print(f"{segment:>14}: fill_rate A={s['fill_rate_a']:.1%} B={s['fill_rate_b']:.1%}  |  "
              f"stock_value A={s['stock_value_a']:,.0f} SEK  B={s['stock_value_b']:,.0f} SEK  |  "
              f"dead_share A={s['dead_share_a']:.1%} B={s['dead_share_b']:.1%}  "
              f"(n={s['n_items']})".replace(",", " "))

    print("\n=== Service-vs-stock-value frontier (policy B at different target service levels) ===")
    print("(policy A's single point shown for reference; interpretation of 'baselines' here is\n"
          " policy B swept across service levels, stated explicitly -- see script docstring)")
    frontier_rows = []
    for target in FRONTIER_SERVICE_LEVELS:
        fr_rows = []
        for _, item in items.iterrows():
            article_id = item["article_id"]
            demand_periods = series_by_article.get(article_id)
            if demand_periods is None or len(demand_periods) < 10:
                continue
            lead_samples = supplier_lead_time_samples(lt_table, item["supplier_id"])
            unit_cost = item["unit_cost_sek"]
            holding_cost_per_unit_year = DEFAULT_HOLDING_COST_RATE * unit_cost
            avg_period_demand = float(pd.Series(demand_periods).tail(52).mean())
            annual_demand = avg_period_demand * 52
            order_qty = economic_order_quantity(annual_demand, DEFAULT_ORDERING_COST_SEK, holding_cost_per_unit_year)
            order_qty = apply_moq_and_multiple(order_qty, item["moq"], item["order_multiple"])
            if order_qty <= 0:
                continue
            rp = _policy_b_reorder_point(pd.Series(demand_periods), lead_samples, target)
            sim = simulate_policy(demand_periods, rp, order_qty, lead_samples, initial_stock=rp + order_qty)
            fr_rows.append({"fill_rate": sim["fill_rate"], "stock_value": sim["avg_stock"] * unit_cost,
                            "total_demand": sim["total_demand"]})
        fr_df = pd.DataFrame(fr_rows)
        total_demand = fr_df["total_demand"].sum()
        weighted_fill = (fr_df["fill_rate"] * fr_df["total_demand"]).sum() / total_demand if total_demand else float("nan")
        frontier_rows.append({"target_service_level": target, "fill_rate": weighted_fill,
                              "stock_value": fr_df["stock_value"].sum()})
        print(f"  target={target:.0%}: fill_rate={weighted_fill:.1%}  "
              f"stock_value={fr_df['stock_value'].sum():,.0f} SEK".replace(",", " "))
    print(f"  policy A (ERP):  fill_rate={overall['fill_rate_a']:.1%}  "
          f"stock_value={overall['stock_value_a']:,.0f} SEK".replace(",", " "))
    print(f"  policy B (own):  fill_rate={overall['fill_rate_b']:.1%}  "
          f"stock_value={overall['stock_value_b']:,.0f} SEK".replace(",", " "))

    frontier_df = pd.DataFrame(frontier_rows)
    frontier_df.loc[len(frontier_df)] = ["policy_a", overall["fill_rate_a"], overall["stock_value_a"]]
    frontier_df.loc[len(frontier_df)] = ["policy_b", overall["fill_rate_b"], overall["stock_value_b"]]
    frontier_df.to_csv("data/phase7_frontier.csv", index=False)


if __name__ == "__main__":
    main()
