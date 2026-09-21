"""Safety stock, reorder point, and order quantity from lead-time demand
quantiles (docs/FORECAST_SPEC.md Phase 6).

Reorder point = the lead-time demand distribution's quantile AT the
item's target service level (critical ratio); safety stock = that same
quantile minus the distribution's MEAN (not median -- see
forecasting/probabilistic.py:lead_time_demand_distribution()'s "mean" key
docstring for why the two differ on a skewed lumpy/intermittent
distribution and which one this formula needs). Both fall out of one
Monte Carlo call per item, reusing Phase 5's distribution machinery
unchanged rather than re-deriving safety stock from a normal-distribution
formula that would not fit this data (Phase 3/4 already measured this
demo estate as overwhelmingly intermittent/lumpy).

Target service level per item: the newsvendor critical ratio
Cu / (Cu + Co) when a selling margin is known (Cu = margin, the cost of
a stockout = lost sale; Co = annual holding cost per unit). Falls back to
the ABC-tier service levels CLAUDE.md's own "Inventory Analysis
Standards" section already establishes (95/90/85% for A/B/C) when margin
is unknown -- not a new convention invented here, the same numbers this
project already quotes to clients. The demo CSV data contract
(forecasting/data.py's _ITEMS_COLS) has no selling-price/margin column at
all, so on this data EVERY item hits the ABC fallback -- stated plainly
in the Phase 6 report, not hidden.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from forecasting.probabilistic import lead_time_demand_distribution

DEFAULT_HOLDING_COST_RATE = 0.22   # per year, matches CLAUDE.md's default
DEFAULT_ORDERING_COST_SEK = 400.0  # matches CLAUDE.md's default
ABC_SERVICE_LEVEL = {"A": 0.95, "B": 0.90, "C": 0.85}
MIN_CRITICAL_RATIO = 0.50  # below this is not a real inventory policy (stock less than half the time?)
MAX_CRITICAL_RATIO = 0.99  # a Monte Carlo distribution with n_simulations in the low thousands cannot
                            # reliably estimate a tail quantile beyond this -- capped, not extrapolated


def critical_ratio(margin_per_unit: float | None, holding_cost_per_unit_per_year: float,
                   abc_class: str | None = None) -> float:
    """Newsvendor critical ratio, clipped to [MIN_CRITICAL_RATIO,
    MAX_CRITICAL_RATIO]. Falls back to ABC_SERVICE_LEVEL[abc_class]
    (defaulting to the C-tier level if abc_class itself is unknown -- the
    most conservative of the three, appropriate when there is no
    information at all) whenever margin_per_unit is missing, non-positive,
    or holding_cost_per_unit_per_year is non-positive (a zero holding
    cost breaks the ratio's denominator, not a real economic scenario)."""
    if margin_per_unit is None or pd.isna(margin_per_unit) or margin_per_unit <= 0 \
            or holding_cost_per_unit_per_year <= 0:
        return ABC_SERVICE_LEVEL.get(abc_class, ABC_SERVICE_LEVEL["C"])
    cr = margin_per_unit / (margin_per_unit + holding_cost_per_unit_per_year)
    return min(max(cr, MIN_CRITICAL_RATIO), MAX_CRITICAL_RATIO)


def economic_order_quantity(annual_demand: float, ordering_cost: float,
                            holding_cost_per_unit_per_year: float) -> float:
    """Classic EOQ = sqrt(2*D*S/H). Zero when there is no annual demand or
    no holding cost to trade off against (division by zero avoided, not a
    meaningful order quantity to compute for an item with no signal)."""
    if annual_demand <= 0 or holding_cost_per_unit_per_year <= 0:
        return 0.0
    return math.sqrt(2 * annual_demand * ordering_cost / holding_cost_per_unit_per_year)


def apply_moq_and_multiple(qty: float, moq: float = 1, order_multiple: float = 1) -> float:
    """Rounds an order quantity up to respect MOQ and order multiple --
    never rounds DOWN (a supplier's minimum is a floor, not a target)."""
    qty = max(qty, moq or 1)
    if order_multiple and order_multiple > 1:
        qty = math.ceil(qty / order_multiple) * order_multiple
    return qty


def compute_policy(demand_history: pd.Series, lead_time_days_samples: np.ndarray,
                   unit_cost: float, abc_class: str | None = None,
                   margin_per_unit: float | None = None,
                   holding_cost_rate: float = DEFAULT_HOLDING_COST_RATE,
                   ordering_cost: float = DEFAULT_ORDERING_COST_SEK,
                   moq: float = 1, order_multiple: float = 1,
                   review_period_days: float = 7, period_days: float = 7,
                   weeks_per_year: float = 52.0,
                   n_simulations: int = 1000, seed: int = 42) -> dict:
    """One full policy for one article: target service level, reorder
    point, safety stock, and order quantity (MOQ/multiple-respecting).

    demand_history and lead_time_days_samples must already be
    as_of-filtered by the caller, same point-in-time convention as every
    other function in forecasting/probabilistic.py and
    forecasting/backtest.py -- this function has no opinion on which
    origin date it is being computed for.
    """
    holding_cost_per_unit_per_year = holding_cost_rate * unit_cost
    target_service_level = critical_ratio(margin_per_unit, holding_cost_per_unit_per_year, abc_class)

    dist = lead_time_demand_distribution(
        demand_history, lead_time_days_samples, review_period_days=review_period_days,
        period_days=period_days, n_simulations=n_simulations,
        quantiles=(target_service_level,), seed=seed,
    )
    reorder_point = dist["quantiles"][target_service_level]
    expected_lead_time_demand = dist["mean"]
    safety_stock = max(reorder_point - expected_lead_time_demand, 0.0)

    recent = demand_history.iloc[-52:]
    avg_period_demand = float(recent.mean()) if len(recent) else 0.0
    annual_demand = avg_period_demand * weeks_per_year

    order_qty = economic_order_quantity(annual_demand, ordering_cost, holding_cost_per_unit_per_year)
    order_qty = apply_moq_and_multiple(order_qty, moq, order_multiple)

    return {
        "target_service_level": target_service_level,
        "margin_based": margin_per_unit is not None and not pd.isna(margin_per_unit) and margin_per_unit > 0,
        "expected_lead_time_demand": expected_lead_time_demand,
        "reorder_point": reorder_point,
        "safety_stock": safety_stock,
        "order_quantity": order_qty,
        "annual_demand_estimate": annual_demand,
    }
