"""Tests for forecasting/policy.py -- docs/FORECAST_SPEC.md Phase 6
safety stock / reorder point / order quantity from lead-time quantiles."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting.policy import (
    ABC_SERVICE_LEVEL,
    MAX_CRITICAL_RATIO,
    MIN_CRITICAL_RATIO,
    apply_moq_and_multiple,
    compute_policy,
    critical_ratio,
    economic_order_quantity,
)


# ── critical_ratio ──────────────────────────────────────────────────────

def test_critical_ratio_hand_computed():
    # margin=90, holding=10 -> CR = 90/(90+10) = 0.9
    assert critical_ratio(90.0, 10.0) == pytest.approx(0.9)


def test_critical_ratio_falls_back_to_abc_when_margin_missing():
    assert critical_ratio(None, 10.0, abc_class="A") == ABC_SERVICE_LEVEL["A"]
    assert critical_ratio(float("nan"), 10.0, abc_class="B") == ABC_SERVICE_LEVEL["B"]
    assert critical_ratio(0.0, 10.0, abc_class="C") == ABC_SERVICE_LEVEL["C"]
    assert critical_ratio(-5.0, 10.0, abc_class="A") == ABC_SERVICE_LEVEL["A"]


def test_critical_ratio_falls_back_when_holding_cost_is_zero():
    assert critical_ratio(100.0, 0.0, abc_class="B") == ABC_SERVICE_LEVEL["B"]


def test_critical_ratio_unknown_abc_class_defaults_to_c():
    assert critical_ratio(None, 10.0, abc_class=None) == ABC_SERVICE_LEVEL["C"]
    assert critical_ratio(None, 10.0, abc_class="Z") == ABC_SERVICE_LEVEL["C"]


def test_critical_ratio_is_clipped_to_sane_range():
    # margin hugely dominant -> ratio approaches 1, must clip at MAX
    assert critical_ratio(100000.0, 0.01) == MAX_CRITICAL_RATIO
    # margin tiny relative to holding cost -> ratio approaches 0, must clip at MIN
    assert critical_ratio(0.01, 100000.0) == MIN_CRITICAL_RATIO


# ── economic_order_quantity ──────────────────────────────────────────────

def test_eoq_hand_computed():
    # D=1000/yr, S=400, H=0.22*50=11 -> EOQ = sqrt(2*1000*400/11) = sqrt(72727.27) = 269.68
    eoq = economic_order_quantity(annual_demand=1000, ordering_cost=400, holding_cost_per_unit_per_year=11.0)
    assert eoq == pytest.approx(269.68, abs=0.01)


def test_eoq_zero_when_no_demand_or_no_holding_cost():
    assert economic_order_quantity(0, 400, 11.0) == 0.0
    assert economic_order_quantity(1000, 400, 0.0) == 0.0


# ── apply_moq_and_multiple ────────────────────────────────────────────────

def test_moq_floor_applies():
    assert apply_moq_and_multiple(3.0, moq=10, order_multiple=1) == 10.0


def test_order_multiple_rounds_up_never_down():
    assert apply_moq_and_multiple(23.0, moq=1, order_multiple=10) == 30.0
    assert apply_moq_and_multiple(20.0, moq=1, order_multiple=10) == 20.0  # exact multiple: no change


def test_moq_and_multiple_combined():
    # qty=3, moq=10 -> 10, then rounded up to nearest 6 -> 12
    assert apply_moq_and_multiple(3.0, moq=10, order_multiple=6) == 12.0


# ── compute_policy (integration) ─────────────────────────────────────────

def test_compute_policy_constant_demand_is_hand_verifiable():
    """Constant demand series + constant lead time -> the whole pipeline
    is deterministic and hand-computable exactly, same trick
    tests/test_probabilistic.py uses for the underlying distribution."""
    demand = pd.Series([10.0] * 60)
    lead_samples = np.array([14.0] * 10)  # constant 14-day lead time, review=7 -> 3 periods
    policy = compute_policy(
        demand, lead_samples, unit_cost=50.0, abc_class="A",  # no margin -> ABC fallback, 95%
        review_period_days=7, period_days=7, n_simulations=100,
    )
    # constant series -> reorder_point == expected == 10*3 == 30, safety_stock == 0
    assert policy["reorder_point"] == pytest.approx(30.0)
    assert policy["expected_lead_time_demand"] == pytest.approx(30.0)
    assert policy["safety_stock"] == pytest.approx(0.0, abs=1e-9)
    assert policy["target_service_level"] == ABC_SERVICE_LEVEL["A"]
    assert policy["margin_based"] is False


def test_compute_policy_variable_demand_has_positive_safety_stock():
    rng = np.random.default_rng(7)
    demand = pd.Series(rng.poisson(10, size=80).astype(float))
    lead_samples = rng.uniform(10, 30, size=20)
    policy = compute_policy(demand, lead_samples, unit_cost=50.0, abc_class="B", n_simulations=500)
    assert policy["safety_stock"] > 0
    assert policy["reorder_point"] >= policy["expected_lead_time_demand"]


def test_compute_policy_uses_margin_when_available():
    demand = pd.Series([10.0] * 60)
    lead_samples = np.array([14.0] * 10)
    policy = compute_policy(
        demand, lead_samples, unit_cost=50.0, abc_class="C", margin_per_unit=200.0,
        holding_cost_rate=0.22, n_simulations=100,
    )
    assert policy["margin_based"] is True
    # holding cost/unit/year = 0.22*50 = 11; CR = 200/(200+11) = 0.948
    assert policy["target_service_level"] == pytest.approx(200.0 / 211.0)


def test_compute_policy_order_quantity_respects_moq():
    demand = pd.Series([1.0] * 60)  # very low volume -> small EOQ
    lead_samples = np.array([10.0] * 10)
    policy = compute_policy(demand, lead_samples, unit_cost=500.0, abc_class="C",
                            moq=100, order_multiple=1, n_simulations=100)
    assert policy["order_quantity"] >= 100
