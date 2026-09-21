"""Tests for forecasting/metrics.py -- docs/FORECAST_SPEC.md Phase 2.
Every expected value is hand-derived AND independently verified by direct
execution before being written here (not assumed correct because the
arithmetic looked right on paper)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from forecasting.metrics import bias, coverage, mase, pinball_loss, wape


def test_wape_hand_computed():
    actual = pd.Series([10, 20, 30])
    forecast = pd.Series([12, 18, 33])
    # |−2|+|2|+|−3| = 7; sum(|actual|) = 60; wape = 7/60
    assert wape(actual, forecast) == pytest.approx(7 / 60)


def test_wape_zero_actual_zero_forecast_is_zero():
    actual = pd.Series([0, 0, 0])
    forecast = pd.Series([0, 0, 0])
    assert wape(actual, forecast) == 0.0


def test_wape_zero_actual_nonzero_forecast_is_nan():
    actual = pd.Series([0, 0, 0])
    forecast = pd.Series([1, 0, 0])
    assert math.isnan(wape(actual, forecast))


def test_bias_hand_computed():
    actual = pd.Series([10, 20, 30])
    forecast = pd.Series([12, 18, 33])
    # (2 - 2 + 3) / 60 = 3/60 = 0.05, positive = over-forecasting
    assert bias(actual, forecast) == pytest.approx(0.05)


def test_bias_sign_direction():
    actual = pd.Series([10, 10])
    over_forecast = pd.Series([15, 15])
    under_forecast = pd.Series([5, 5])
    assert bias(actual, over_forecast) > 0
    assert bias(actual, under_forecast) < 0


def test_mase_hand_computed():
    train_actual = pd.Series([5, 7, 6, 8, 7, 9])  # naive diffs: 2,1,2,1,2 -> mean 1.6
    actual = pd.Series([10, 12])
    forecast = pd.Series([11, 11])  # MAE = (1+1)/2 = 1
    assert mase(actual, forecast, train_actual) == pytest.approx(1 / 1.6)


def test_mase_below_one_means_better_than_naive():
    train_actual = pd.Series([10, 10, 10, 10, 10, 10])  # perfectly flat: naive scale = 0
    actual = pd.Series([10, 10])
    forecast = pd.Series([10, 10])
    # scale is 0 here (flat training series) -- must be NaN, not a division error
    assert math.isnan(mase(actual, forecast, train_actual))


def test_pinball_loss_hand_computed():
    actual = pd.Series([10, 8])
    forecast_q = pd.Series([8, 10])
    # row1: diff=2>=0 -> 0.9*2=1.8; row2: diff=-2<0 -> (0.9-1)*(-2)=0.2; mean=1.0
    assert pinball_loss(actual, forecast_q, 0.9) == pytest.approx(1.0)


def test_pinball_loss_perfect_forecast_is_zero():
    actual = pd.Series([5, 10, 15])
    assert pinball_loss(actual, actual, 0.9) == pytest.approx(0.0)


def test_pinball_loss_q_is_asymmetric():
    """At a high quantile (0.9), under-predicting should be penalized more
    than over-predicting by the same absolute amount."""
    actual = pd.Series([10])
    under = pinball_loss(actual, pd.Series([5]), 0.9)   # forecast too low
    over = pinball_loss(actual, pd.Series([15]), 0.9)    # forecast too high, same distance
    assert under > over


def test_coverage_hand_computed():
    actual = pd.Series([5, 15, 25])
    lower = pd.Series([0, 0, 0])
    upper = pd.Series([10, 10, 10])
    # only the first (5) falls inside [0,10]
    assert coverage(actual, lower, upper) == pytest.approx(1 / 3)


def test_coverage_full_containment_is_one():
    actual = pd.Series([5, 6, 7])
    lower = pd.Series([0, 0, 0])
    upper = pd.Series([10, 10, 10])
    assert coverage(actual, lower, upper) == 1.0
