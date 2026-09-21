"""Tests for forecasting/explain.py -- docs/FORECAST_SPEC.md Phase 6:
"explanations exist for all items and reference real drivers"."""

from __future__ import annotations

import numpy as np
import pandas as pd

from forecasting.explain import explain_policy
from forecasting.policy import compute_policy


def _demand_and_lead_samples():
    rng = np.random.default_rng(3)
    demand = pd.Series(rng.poisson(8, size=60).astype(float))
    lead_samples = rng.uniform(10, 25, size=15)
    return demand, lead_samples


def test_explain_policy_returns_nonempty_string_for_every_segment():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, abc_class="B", n_simulations=200)
    for segment in ["smooth", "erratic", "intermittent", "lumpy", "no_demand", None, "something_unmapped"]:
        text = explain_policy("A0001", "Testartikel", policy, segment, demand, lead_samples)
        assert isinstance(text, str)
        assert len(text) > 20


def test_explain_policy_references_article_id_when_no_description():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, abc_class="A", n_simulations=200)
    text = explain_policy("A9999", None, policy, "lumpy", demand, lead_samples)
    assert "A9999" in text


def test_explain_policy_reports_real_reorder_point_and_safety_stock_numbers():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, abc_class="A", n_simulations=200)
    text = explain_policy("A0001", "Testartikel", policy, "erratic", demand, lead_samples)
    assert f"{policy['reorder_point']:.0f}" in text
    assert f"{policy['safety_stock']:.0f}" in text
    assert f"{policy['order_quantity']:.0f}" in text


def test_explain_policy_states_margin_based_reason_when_margin_known():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, margin_per_unit=300.0, n_simulations=200)
    assert policy["margin_based"] is True
    text = explain_policy("A0001", "Testartikel", policy, "smooth", demand, lead_samples)
    assert "marginal" in text.lower()


def test_explain_policy_states_abc_fallback_reason_when_no_margin():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, abc_class="C", n_simulations=200)
    assert policy["margin_based"] is False
    text = explain_policy("A0001", "Testartikel", policy, "smooth", demand, lead_samples)
    assert "abc" in text.lower()


def test_explain_policy_mentions_lead_time_spread_when_enough_samples():
    demand, lead_samples = _demand_and_lead_samples()
    policy = compute_policy(demand, lead_samples, unit_cost=100.0, abc_class="B", n_simulations=200)
    text = explain_policy("A0001", "Testartikel", policy, "smooth", demand, lead_samples)
    assert "ledtid" in text.lower()
    assert f"{len(lead_samples)}" in text


def test_explain_policy_handles_too_few_lead_time_samples_gracefully():
    demand, _ = _demand_and_lead_samples()
    few_samples = np.array([12.0])
    policy = compute_policy(demand, few_samples, unit_cost=100.0, abc_class="B", n_simulations=200)
    text = explain_policy("A0001", "Testartikel", policy, "smooth", demand, few_samples)
    assert isinstance(text, str)
    assert len(text) > 20


def test_explain_policy_handles_empty_demand_history_gracefully():
    policy = compute_policy(pd.Series([], dtype=float), np.array([10.0] * 10),
                            unit_cost=100.0, abc_class="C", n_simulations=200)
    text = explain_policy("A0001", "Testartikel", policy, "no_demand", pd.Series([], dtype=float),
                          np.array([10.0] * 10))
    assert isinstance(text, str)
    assert len(text) > 20
