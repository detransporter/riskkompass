"""Tests for forecasting/probabilistic.py -- docs/FORECAST_SPEC.md Phase 5
lead-time demand distribution and conformal calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting.probabilistic import (
    MIN_LEAD_TIME_SAMPLES,
    apply_conformal_correction,
    build_supplier_lead_time_table,
    conformal_correction,
    lead_time_demand_distribution,
    supplier_lead_time_samples,
)


def _make_inbound() -> pd.DataFrame:
    rows = [
        # supplier S1: three received lines, lead times 10, 12, 14 days
        {"po_number": "PO1", "po_line": 1, "supplier_id": "S1", "article_id": "A1",
         "po_date": pd.Timestamp("2026-01-01"), "receipt_date": pd.Timestamp("2026-01-11"),
         "qty_ordered": 100, "qty_received": 100, "status": "Received"},
        {"po_number": "PO2", "po_line": 1, "supplier_id": "S1", "article_id": "A1",
         "po_date": pd.Timestamp("2026-02-01"), "receipt_date": pd.Timestamp("2026-02-13"),
         "qty_ordered": 100, "qty_received": 60, "status": "Received"},  # partial
        {"po_number": "PO3", "po_line": 1, "supplier_id": "S1", "article_id": "A2",
         "po_date": pd.Timestamp("2026-03-01"), "receipt_date": pd.Timestamp("2026-03-15"),
         "qty_ordered": 50, "qty_received": 50, "status": "Received"},
        # supplier S1: one still open (no receipt yet)
        {"po_number": "PO4", "po_line": 1, "supplier_id": "S1", "article_id": "A1",
         "po_date": pd.Timestamp("2026-04-01"), "receipt_date": pd.NaT,
         "qty_ordered": 100, "qty_received": 0, "status": "Open"},
        # supplier S2: one received line, lead time 20 days
        {"po_number": "PO5", "po_line": 1, "supplier_id": "S2", "article_id": "A3",
         "po_date": pd.Timestamp("2026-01-01"), "receipt_date": pd.Timestamp("2026-01-21"),
         "qty_ordered": 200, "qty_received": 200, "status": "Received"},
    ]
    return pd.DataFrame(rows)


def test_build_supplier_lead_time_table_hand_computed():
    table = build_supplier_lead_time_table(_make_inbound())
    assert len(table) == 4  # PO4 (Open) dropped
    row1 = table[table["po_number"] == "PO1"].iloc[0]
    assert row1["lead_time_days"] == 10
    assert row1["is_partial"] == False  # noqa: E712
    row2 = table[table["po_number"] == "PO2"].iloc[0]
    assert row2["lead_time_days"] == 12
    assert row2["is_partial"] == True  # noqa: E712


def test_supplier_lead_time_samples_filters_by_supplier():
    table = build_supplier_lead_time_table(_make_inbound())
    s1_samples = supplier_lead_time_samples(table, "S1")
    s2_samples = supplier_lead_time_samples(table, "S2")
    assert sorted(s1_samples) == [10.0, 12.0, 14.0]
    assert list(s2_samples) == [20.0]


def test_supplier_lead_time_samples_as_of_is_leakage_safe():
    """A delivery received AFTER as_of must not appear in the sample --
    the core point-in-time rule this whole module depends on."""
    table = build_supplier_lead_time_table(_make_inbound())
    samples = supplier_lead_time_samples(table, "S1", as_of=pd.Timestamp("2026-01-15"))
    # only PO1 (received 2026-01-11) is known by 2026-01-15
    assert list(samples) == [10.0]


def test_supplier_lead_time_samples_exclude_po():
    table = build_supplier_lead_time_table(_make_inbound())
    samples = supplier_lead_time_samples(table, "S1", exclude_po=("PO1", 1))
    assert sorted(samples) == [12.0, 14.0]


def test_lead_time_demand_distribution_is_deterministic_with_same_seed():
    demand = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 20)
    lead_samples = np.array([10.0, 14.0, 21.0, 7.0, 28.0, 10.0])
    a = lead_time_demand_distribution(demand, lead_samples, seed=42)
    b = lead_time_demand_distribution(demand, lead_samples, seed=42)
    assert a == b


def test_lead_time_demand_distribution_constant_series_is_exact():
    """Bootstrapping a CONSTANT demand series always returns that same
    constant, regardless of which periods get drawn -- so with a constant
    lead time too, the total is deterministic and hand-computable exactly:
    value * ceil((lead_days + review_period_days) / period_days)."""
    demand = pd.Series([5.0] * 60)
    lead_samples = np.array([14.0] * 10)  # constant 14-day lead time
    result = lead_time_demand_distribution(
        demand, lead_samples, review_period_days=7, period_days=7, n_simulations=100,
    )
    expected_periods = 3  # ceil((14+7)/7) = 3
    expected_total = 5.0 * expected_periods
    assert result["point"] == pytest.approx(expected_total)
    for q in result["quantiles"].values():
        assert q == pytest.approx(expected_total)


def test_lead_time_demand_distribution_falls_back_below_min_samples():
    """Fewer than MIN_LEAD_TIME_SAMPLES: falls back to review-period-only
    (no lead-time uncertainty), not a crash or a nonsensical distribution."""
    demand = pd.Series([2.0] * 20)
    few_samples = np.array([10.0, 12.0])  # below MIN_LEAD_TIME_SAMPLES
    assert len(few_samples) < MIN_LEAD_TIME_SAMPLES
    result = lead_time_demand_distribution(
        demand, few_samples, review_period_days=7, period_days=7, n_simulations=50,
    )
    expected_periods = 1  # ceil(7/7) = 1
    assert result["point"] == pytest.approx(2.0 * expected_periods)


def test_lead_time_demand_distribution_empty_history_is_zero():
    result = lead_time_demand_distribution(pd.Series([], dtype=float), np.array([10.0] * 10))
    assert result["point"] == 0.0
    assert all(v == 0.0 for v in result["quantiles"].values())


def test_lead_time_demand_distribution_quantiles_are_monotonic():
    rng = np.random.default_rng(1)
    demand = pd.Series(rng.poisson(5, size=80).astype(float))
    lead_samples = rng.uniform(5, 40, size=30)
    result = lead_time_demand_distribution(demand, lead_samples, n_simulations=500,
                                           quantiles=(0.05, 0.1, 0.5, 0.8, 0.9, 0.95))
    values = [result["quantiles"][q] for q in sorted(result["quantiles"])]
    assert values == sorted(values)


def test_conformal_correction_hand_computed():
    # 4 calibration points, interval [10,20] each; actuals 15 (inside),
    # 25 (5 over hi), 5 (5 under lo), 18 (inside). Scores: -5, 5, 5, -2.
    # n=4, alpha=0.1 -> level = ceil(5*0.9)/4 = ceil(4.5)/4 = 5/4 -> clipped to 1.0 -> max score = 5
    actual = np.array([15.0, 25.0, 5.0, 18.0])
    lo = np.array([10.0, 10.0, 10.0, 10.0])
    hi = np.array([20.0, 20.0, 20.0, 20.0])
    correction = conformal_correction(actual, lo, hi, alpha=0.1)
    assert correction == pytest.approx(5.0)


def test_conformal_correction_perfectly_covered_can_be_negative():
    # actual always exactly at the center -- interval could shrink
    actual = np.array([15.0, 15.0, 15.0, 15.0, 15.0])
    lo = np.array([10.0] * 5)
    hi = np.array([20.0] * 5)
    correction = conformal_correction(actual, lo, hi, alpha=0.5)
    assert correction < 0  # scores are all -5 (well inside), so the interval can narrow


def test_conformal_correction_too_few_points_returns_zero():
    assert conformal_correction(np.array([1.0]), np.array([0.0]), np.array([2.0]), alpha=0.1) == 0.0
    assert conformal_correction(np.array([]), np.array([]), np.array([]), alpha=0.1) == 0.0


def test_apply_conformal_correction_widens_and_clips_at_zero():
    lo, hi = apply_conformal_correction(10.0, 20.0, correction=5.0)
    assert lo == 5.0
    assert hi == 25.0

    lo, hi = apply_conformal_correction(3.0, 20.0, correction=10.0)
    assert lo == 0.0  # clipped, not negative
    assert hi == 30.0


def test_apply_conformal_correction_can_narrow():
    lo, hi = apply_conformal_correction(10.0, 20.0, correction=-3.0)
    assert lo == 13.0
    assert hi == 17.0
