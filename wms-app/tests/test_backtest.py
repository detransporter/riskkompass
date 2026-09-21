"""Tests for forecasting/backtest.py -- docs/FORECAST_SPEC.md Phase 2."""

from __future__ import annotations

import pandas as pd
import pytest

from forecasting.backtest import lead_time_horizon_periods, run_backtest
from forecasting.data import build_demand_series
from forecasting.models.baselines import naive_forecast


def test_lead_time_horizon_hand_computed():
    # (14 + 7) / 7 = 3.0 -> ceil = 3
    assert lead_time_horizon_periods(14, review_period_days=7, period_days=7) == 3
    # (10 + 7) / 7 = 2.43 -> ceil = 3
    assert lead_time_horizon_periods(10, review_period_days=7, period_days=7) == 3


def test_lead_time_horizon_missing_lead_time_still_gets_review_period():
    assert lead_time_horizon_periods(None, review_period_days=7, period_days=7) == 1
    assert lead_time_horizon_periods(0, review_period_days=7, period_days=7) == 1


def test_run_backtest_output_shape(small_dataset):
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    models = {"naive": naive_forecast}
    result = run_backtest(series, small_dataset["items"], models,
                          fixed_horizons=(4,), min_train_periods=4, origin_step=4)
    if not result.empty:
        expected_cols = {"article_id", "origin_period", "horizon", "horizon_type",
                         "model", "actual", "forecast", "q5", "q10", "q50", "q80", "q90", "q95"}
        assert expected_cols.issubset(result.columns)
        assert (result["model"] == "naive").all()


def test_run_backtest_is_leakage_safe():
    """The actual harness, not just the cleaning flags: a huge spike
    placed AFTER an origin must not change that origin's forecast. Uses
    naive_forecast (= last training value) specifically because it is
    maximally sensitive to a leak -- if the origin's train slice ever
    included one extra future row, this test would catch it immediately."""
    periods = pd.date_range("2026-01-05", periods=20, freq="W")
    items = pd.DataFrame([{"article_id": "A1", "lead_time_days": 14}])

    steady = pd.DataFrame({
        "article_id": ["A1"] * 20, "period": periods, "qty_ordered": [5.0] * 20,
    })
    with_future_spike = steady.copy()
    with_future_spike.loc[15:, "qty_ordered"] = 500.0  # spike well after any origin below

    models = {"naive": naive_forecast}
    result_steady = run_backtest(steady, items, models, fixed_horizons=(4,),
                                 min_train_periods=8, origin_step=1)
    result_spiked = run_backtest(with_future_spike, items, models, fixed_horizons=(4,),
                                 min_train_periods=8, origin_step=1)

    # Origins whose training window ends before the spike (index 15) must
    # produce IDENTICAL forecasts regardless of what happens after them.
    early_steady = result_steady[result_steady["origin_period"] <= periods[10]]
    early_spiked = result_spiked[result_spiked["origin_period"] <= periods[10]]
    assert not early_steady.empty
    pd.testing.assert_frame_equal(
        early_steady.reset_index(drop=True), early_spiked.reset_index(drop=True),
    )


def test_run_backtest_actual_matches_the_real_future_value():
    """Sanity check on the harness's own bookkeeping: at a known origin
    with a known horizon, `actual` must be exactly the series value at
    origin+horizon, not off by one or reading the wrong row."""
    periods = pd.date_range("2026-01-05", periods=20, freq="W")
    values = list(range(20))  # value at index i is just i, trivially checkable
    series = pd.DataFrame({"article_id": ["A1"] * 20, "period": periods, "qty_ordered": values})
    items = pd.DataFrame([{"article_id": "A1", "lead_time_days": 7}])

    models = {"naive": naive_forecast}
    result = run_backtest(series, items, models, fixed_horizons=(4,),
                          min_train_periods=8, origin_step=1)
    row = result[(result["horizon_type"] == "4w") & (result["origin_period"] == periods[9])]
    assert len(row) == 1
    # origin index 9, horizon 4 -> actual should be values[13] = 13
    assert row.iloc[0]["actual"] == 13.0
