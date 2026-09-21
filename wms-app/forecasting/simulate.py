"""Inventory simulation as proof of value (docs/FORECAST_SPEC.md Phase 7):
replay REAL historical demand against two competing policies -- policy A
(the item's existing ERP `reorder_point`/`safety_stock`, already sitting
in the demo data's items table) and policy B (Phase 6's quantile-based
policy) -- and measure which one actually delivers better service at
lower cost.

Periodic-review, not continuous-review: stock is checked once per period
(matching the weekly granularity every other forecasting/ module uses,
not a per-transaction check) -- at each period, that period's real demand
is applied (a demand exceeding available stock fills only what is
available; this simulator does not backorder), then if stock has fallen
to or below the reorder point and no order is currently in transit, one
replenishment order for a fixed `order_quantity` is placed, arriving a
lead time later drawn from the SAME seeded supplier lead-time sample
sequence for both policies -- so any difference in outcome comes from the
trigger level (reorder point), not from one policy getting luckier lead
times than the other.

`order_quantity` is deliberately shared between policy A and policy B in
the head-to-head comparison (`compare_policies()`) -- the spec frames
this phase as a reorder-point/safety-stock comparison specifically
("current ERP parameters (reorder_point / safety_stock in the data)"),
and giving the two policies different order quantities too would
conflate two separate questions (is the TRIGGER point better calibrated,
vs. is the ORDER SIZE better calibrated) into one number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_REVIEW_PERIOD_DAYS = 7
DEFAULT_PERIOD_DAYS = 7


def _lead_time_periods_samples(lead_time_days_samples: np.ndarray, review_period_days: float,
                                period_days: float) -> np.ndarray:
    if len(lead_time_days_samples) == 0:
        return np.array([1])
    total_days = lead_time_days_samples + review_period_days
    return np.maximum(1, np.ceil(total_days / period_days)).astype(int)


def simulate_policy(demand_periods: np.ndarray, reorder_point: float, order_quantity: float,
                    lead_time_days_samples: np.ndarray, initial_stock: float,
                    review_period_days: float = DEFAULT_REVIEW_PERIOD_DAYS,
                    period_days: float = DEFAULT_PERIOD_DAYS, seed: int = 42) -> dict:
    """Periodic-review simulation of ONE article under ONE policy over its
    own real historical demand sequence (`demand_periods`, one value per
    period, chronological order -- the caller passes the article's actual
    build_demand_series() history, not synthetic data).

    Returns fill_rate (units fulfilled / units demanded, 1.0 if there was
    no demand at all), avg_stock (time-average stock level -- the
    quantity `avg_stock * unit_cost` the caller turns into a stock-value
    number), n_stockout_periods, n_orders_placed, ending_stock.
    """
    rng = np.random.default_rng(seed)
    lead_periods_samples = _lead_time_periods_samples(lead_time_days_samples, review_period_days, period_days)

    stock = initial_stock
    pending_arrival_idx: int | None = None
    pending_qty = 0.0

    total_demand = 0.0
    total_fulfilled = 0.0
    stock_levels = []
    n_stockout_periods = 0
    n_orders = 0

    for i, qty_demanded in enumerate(demand_periods):
        if pending_arrival_idx is not None and i >= pending_arrival_idx:
            stock += pending_qty
            pending_arrival_idx = None

        fulfilled = min(float(qty_demanded), stock)
        stock -= fulfilled
        total_demand += float(qty_demanded)
        total_fulfilled += fulfilled
        if fulfilled < qty_demanded:
            n_stockout_periods += 1
        stock_levels.append(stock)

        if stock <= reorder_point and pending_arrival_idx is None and order_quantity > 0:
            lead_periods = int(rng.choice(lead_periods_samples))
            pending_arrival_idx = i + lead_periods
            pending_qty = order_quantity
            n_orders += 1

    fill_rate = (total_fulfilled / total_demand) if total_demand > 0 else 1.0
    avg_stock = float(np.mean(stock_levels)) if stock_levels else float(initial_stock)
    return {
        "fill_rate": fill_rate,
        "avg_stock": avg_stock,
        "ending_stock": stock,
        "n_stockout_periods": n_stockout_periods,
        "n_periods": len(demand_periods),
        "n_orders_placed": n_orders,
        "total_demand": total_demand,
    }


def compare_policies(demand_periods: np.ndarray, reorder_point_a: float, reorder_point_b: float,
                     order_quantity: float, lead_time_days_samples: np.ndarray,
                     review_period_days: float = DEFAULT_REVIEW_PERIOD_DAYS,
                     period_days: float = DEFAULT_PERIOD_DAYS, seed: int = 42) -> dict:
    """Runs simulate_policy() for A and B with the SAME order_quantity and
    the SAME seed (so both draw the identical sequence of lead-time
    realizations -- the only thing that differs between the two runs is
    the reorder_point trigger). Each policy starts at its own natural
    "just replenished" stock level (reorder_point + order_quantity) --
    giving A and B different starting stock would just be simulating a
    third, arbitrary policy at t=0 for both.
    """
    result_a = simulate_policy(
        demand_periods, reorder_point_a, order_quantity, lead_time_days_samples,
        initial_stock=reorder_point_a + order_quantity,
        review_period_days=review_period_days, period_days=period_days, seed=seed,
    )
    result_b = simulate_policy(
        demand_periods, reorder_point_b, order_quantity, lead_time_days_samples,
        initial_stock=reorder_point_b + order_quantity,
        review_period_days=review_period_days, period_days=period_days, seed=seed,
    )
    return {"policy_a": result_a, "policy_b": result_b}
