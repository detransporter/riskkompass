"""Tests for forecasting/simulate.py -- docs/FORECAST_SPEC.md Phase 7
inventory policy simulation."""

from __future__ import annotations

import numpy as np
import pytest

from forecasting.simulate import compare_policies, simulate_policy


def test_simulate_policy_perfect_fill_when_stock_never_runs_out():
    demand = np.array([5.0] * 20)
    result = simulate_policy(demand, reorder_point=1000, order_quantity=100,
                             lead_time_days_samples=np.array([7.0] * 10), initial_stock=1000)
    assert result["fill_rate"] == pytest.approx(1.0)
    assert result["n_stockout_periods"] == 0


def test_simulate_policy_zero_stock_zero_reorder_gives_zero_fill_rate():
    demand = np.array([5.0] * 10)
    result = simulate_policy(demand, reorder_point=0, order_quantity=0,
                             lead_time_days_samples=np.array([7.0] * 10), initial_stock=0)
    assert result["fill_rate"] == 0.0
    assert result["n_stockout_periods"] == 10


def test_simulate_policy_no_demand_at_all_is_fill_rate_one():
    demand = np.array([0.0] * 10)
    result = simulate_policy(demand, reorder_point=10, order_quantity=20,
                             lead_time_days_samples=np.array([7.0] * 10), initial_stock=10)
    assert result["fill_rate"] == 1.0
    assert result["total_demand"] == 0.0


def test_simulate_policy_replenishment_arrives_and_prevents_further_stockouts():
    # constant lead time of exactly 1 period (7 days review + 0 lead -> 1 period)
    demand = np.array([10.0] * 10)
    result = simulate_policy(demand, reorder_point=15, order_quantity=100,
                             lead_time_days_samples=np.array([0.0] * 10),
                             initial_stock=20, review_period_days=7, period_days=7)
    # starts at 20, period0: demand 10 -> stock=10 <= reorder_point(15) -> order placed,
    # arrives next period (lead=1). period1: stock=10, demand10 -> fulfilled=10, stock=0
    #   (order hasn't arrived THIS period's start yet since arrival check is at loop start,
    #    i>=pending_arrival_idx=1 -> arrives at start of period1) so actually arrives before demand applied
    assert result["n_orders_placed"] >= 1
    assert result["fill_rate"] > 0.5  # replenishment should prevent most stockouts


def test_simulate_policy_higher_reorder_point_never_gives_worse_fill_rate():
    """Monotonicity sanity check: all else equal, a higher trigger point
    should never (on the same demand/lead-time draws) result in a WORSE
    fill rate than a lower one -- more safety margin can only help or be
    neutral, never hurt service."""
    rng = np.random.default_rng(5)
    demand = rng.poisson(8, size=60).astype(float)
    lead_samples = rng.uniform(5, 20, size=15)

    low = simulate_policy(demand, reorder_point=5, order_quantity=50,
                          lead_time_days_samples=lead_samples, initial_stock=5 + 50, seed=1)
    high = simulate_policy(demand, reorder_point=50, order_quantity=50,
                           lead_time_days_samples=lead_samples, initial_stock=50 + 50, seed=1)
    assert high["fill_rate"] >= low["fill_rate"]
    assert high["avg_stock"] >= low["avg_stock"]


def test_compare_policies_same_seed_isolates_reorder_point_effect():
    """A and B must draw the IDENTICAL lead-time sequence (same seed) --
    verified indirectly: if reorder_point_a == reorder_point_b, both
    results must be identical (same trigger, same lead times, same
    demand -> same outcome down to the fill rate)."""
    rng = np.random.default_rng(9)
    demand = rng.poisson(6, size=40).astype(float)
    lead_samples = rng.uniform(5, 20, size=15)

    result = compare_policies(demand, reorder_point_a=20, reorder_point_b=20,
                              order_quantity=60, lead_time_days_samples=lead_samples)
    assert result["policy_a"]["fill_rate"] == result["policy_b"]["fill_rate"]
    assert result["policy_a"]["avg_stock"] == result["policy_b"]["avg_stock"]


def test_compare_policies_different_reorder_points_can_differ():
    rng = np.random.default_rng(11)
    demand = rng.poisson(10, size=60).astype(float)
    lead_samples = rng.uniform(10, 30, size=15)

    result = compare_policies(demand, reorder_point_a=5, reorder_point_b=80,
                              order_quantity=100, lead_time_days_samples=lead_samples)
    assert result["policy_b"]["fill_rate"] >= result["policy_a"]["fill_rate"]
    assert result["policy_b"]["avg_stock"] > result["policy_a"]["avg_stock"]
