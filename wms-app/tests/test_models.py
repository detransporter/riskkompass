"""Tests for forecasting/models/{baselines,intermittent}.py --
docs/FORECAST_SPEC.md Phase 2. Hand-derived expected values, independently
verified by direct execution before being written here."""

from __future__ import annotations

import pandas as pd
import pytest

from forecasting.models.baselines import (
    moving_average_forecast,
    naive_forecast,
    seasonal_naive_forecast,
    ses_forecast,
)
from forecasting.models.intermittent import bootstrap_forecast, croston_forecast, sba_forecast, tsb_forecast
from forecasting.models.statistical import ets_forecast, theta_forecast


def test_naive_forecast_is_last_value():
    train = pd.Series([1, 2, 3, 4, 5])
    result = naive_forecast(train, horizon=3)
    assert result["point"] == 5.0


def test_naive_forecast_empty_train_is_zero():
    result = naive_forecast(pd.Series([], dtype=float), horizon=3)
    assert result["point"] == 0.0


def test_seasonal_naive_uses_value_from_one_season_ago():
    # 60 weekly periods, season_length=52 -> forecast = value at index -52 (index 8)
    train = pd.Series(range(60), dtype=float)
    result = seasonal_naive_forecast(train, horizon=3, season_length=52)
    assert result["point"] == float(train.iloc[-52])
    assert result["point"] == 8.0


def test_seasonal_naive_falls_back_to_naive_with_short_history():
    train = pd.Series([1.0, 2.0, 3.0])  # far fewer than season_length
    result = seasonal_naive_forecast(train, horizon=3, season_length=52)
    assert result["point"] == 3.0  # same as naive: last value


def test_moving_average_hand_computed():
    train = pd.Series([2, 4, 6, 8, 10])
    result = moving_average_forecast(train, horizon=3, window=3)
    # mean of last 3: (6+8+10)/3 = 8.0
    assert result["point"] == pytest.approx(8.0)


def test_ses_hand_computed():
    train = pd.Series([10.0, 20.0])
    result = ses_forecast(train, horizon=3, alpha=0.5)
    # level0 = 10; level1 = 0.5*20 + 0.5*10 = 15.0
    assert result["point"] == pytest.approx(15.0)


def test_ses_alpha_one_equals_naive():
    """alpha=1 means no smoothing at all -- SES degenerates to naive."""
    train = pd.Series([5.0, 3.0, 9.0, 1.0])
    result = ses_forecast(train, horizon=3, alpha=1.0)
    assert result["point"] == pytest.approx(1.0)


def test_all_baselines_never_forecast_negative_quantiles():
    """Demand cannot be negative -- the empirical-residual band must clip
    at 0, even for a volatile low-volume series where raw residuals would
    push a low quantile below zero."""
    train = pd.Series([0, 1, 0, 0, 2, 0, 1, 0])
    for fn in (naive_forecast, moving_average_forecast, ses_forecast):
        result = fn(train, horizon=3)
        assert all(v >= 0 for v in result["quantiles"].values()), f"{fn.__name__} produced a negative quantile"


# ── Croston / SBA ──────────────────────────────────────────────────────

def test_croston_hand_computed():
    train = pd.Series([0, 0, 4, 0, 0, 6, 0, 0, 0, 8])
    result = croston_forecast(train, horizon=3, alpha=0.1)
    assert result["point"] == pytest.approx(1.4774193548387096)


def test_sba_hand_computed():
    train = pd.Series([0, 0, 4, 0, 0, 6, 0, 0, 0, 8])
    result = sba_forecast(train, horizon=3, alpha=0.1)
    assert result["point"] == pytest.approx(1.4035483870967742)


def test_sba_always_below_croston():
    """SBA = croston * (1 - alpha/2), and alpha is always in (0,1) here, so
    SBA must strictly dominate (be lower than, i.e. less upward-biased)
    classic Croston on the same series -- see the module docstring."""
    train = pd.Series([0, 3, 0, 0, 5, 0, 0, 0, 7, 0, 2])
    croston = croston_forecast(train, horizon=3)["point"]
    sba = sba_forecast(train, horizon=3)["point"]
    assert sba < croston


def test_croston_no_demand_at_all_is_flat_zero():
    train = pd.Series([0, 0, 0, 0, 0])
    result = croston_forecast(train, horizon=3)
    assert result["point"] == 0.0
    assert all(v == 0.0 for v in result["quantiles"].values())


def test_croston_needs_at_least_two_occurrences():
    train = pd.Series([0, 0, 5, 0, 0, 0])  # only one nonzero period
    result = croston_forecast(train, horizon=3)
    assert result["point"] == 0.0


# ── TSB ────────────────────────────────────────────────────────────────

def test_tsb_decays_when_demand_stops_unlike_croston_sba():
    """TSB's whole point (Teunter, Syntetos & Babai 2011): a forecast that
    decays toward zero once demand genuinely stops, unlike Croston/SBA
    which stay flat forever -- see the module docstring."""
    train = pd.Series([0, 5, 0, 0, 6, 0, 0, 7, 0, 0, 8] + [0] * 14, dtype=float)
    croston = croston_forecast(train, horizon=3)["point"]
    sba = sba_forecast(train, horizon=3)["point"]
    tsb = tsb_forecast(train, horizon=3)["point"]
    assert tsb < sba < croston


def test_tsb_no_demand_at_all_is_flat_zero():
    train = pd.Series([0, 0, 0, 0, 0], dtype=float)
    result = tsb_forecast(train, horizon=3)
    assert result["point"] == 0.0


def test_tsb_needs_at_least_two_occurrences():
    train = pd.Series([0, 0, 5, 0, 0, 0])
    result = tsb_forecast(train, horizon=3)
    assert result["point"] == 0.0


# ── ETS / Theta ───────────────────────────────────────────────────────

def test_ets_short_history_is_flat_zero():
    """Below MIN_PERIODS=7: flat zero, matching AutoETS's own documented
    refusal below that floor rather than a degraded guess (see
    analysis/demand_forecast.py:forecast_ets, same floor reused here)."""
    train = pd.Series([1.0, 2.0, 3.0])
    result = ets_forecast(train, horizon=3)
    assert result["point"] == 0.0


def test_ets_tracks_a_clear_trend():
    train = pd.Series([float(i) for i in range(1, 21)])  # 1..20, clean linear trend
    result = ets_forecast(train, horizon=3)
    assert result["point"] > 18  # should extrapolate forward, not just repeat the last value


def test_theta_short_history_is_flat_zero():
    train = pd.Series([1.0, 2.0, 3.0])
    result = theta_forecast(train, horizon=3)
    assert result["point"] == 0.0


def test_ets_and_theta_never_crash_on_all_zero_series():
    train = pd.Series([0.0] * 15)
    ets_result = ets_forecast(train, horizon=3)
    theta_result = theta_forecast(train, horizon=3)
    assert ets_result["point"] == 0.0
    assert theta_result["point"] == 0.0


# ── Bootstrap ─────────────────────────────────────────────────────────

def test_bootstrap_is_deterministic_with_same_seed():
    train = pd.Series([0, 0, 15, 0, 0, 0, 40, 0, 0, 0, 0, 8], dtype=float)
    a = bootstrap_forecast(train, horizon=3, seed=42)
    b = bootstrap_forecast(train, horizon=3, seed=42)
    assert a == b


def test_bootstrap_quantiles_bracket_the_point():
    train = pd.Series([0, 0, 15, 0, 0, 0, 40, 0, 0, 0, 0, 8], dtype=float)
    result = bootstrap_forecast(train, horizon=3)
    assert result["quantiles"][0.8] <= result["quantiles"][0.95]
    assert result["point"] <= result["quantiles"][0.95]


def test_bootstrap_empty_train_is_zero():
    result = bootstrap_forecast(pd.Series([], dtype=float), horizon=3)
    assert result["point"] == 0.0
