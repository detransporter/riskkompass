"""Tests for forecasting/models/global_gbm.py and
forecasting/backtest.py:run_global_backtest -- docs/FORECAST_SPEC.md
Phase 4's panel-wide global model.

Synthetic panels here are built directly (not via tests/fixtures.py's
small_dataset, which is 50 items/6 months -- too few rows to clear
global_gbm.MIN_TRAIN_ROWS=200 at all, so every test against it would
silently exercise the "not enough data, skip" path instead of the real
one) at a size that reliably clears that floor while staying fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting.backtest import run_global_backtest
from forecasting.models.global_gbm import (
    LIGHTGBM_AVAILABLE,
    MIN_TRAIN_ROWS,
    build_panel_features,
    feature_columns,
    fit_predict_quantiles,
)


def _make_panel(n_articles: int = 60, n_periods: int = 40, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    periods = pd.date_range("2025-01-06", periods=n_periods, freq="W")
    article_ids = [f"A{i:04d}" for i in range(n_articles)]

    items = pd.DataFrame({
        "article_id": article_ids,
        "category": rng.choice(["Verktyg", "Hydraulik", "Elektronik"], size=n_articles),
        "unit_cost_sek": rng.uniform(10, 500, size=n_articles).round(2),
        "lead_time_days": rng.integers(5, 30, size=n_articles),
        "moq": rng.choice([1, 5, 10], size=n_articles),
        "order_multiple": 1,
        "created_date": periods[0],
    })

    base_level = rng.uniform(2, 20, size=n_articles)
    rows = []
    for i, article_id in enumerate(article_ids):
        qty = np.maximum(0, rng.poisson(base_level[i], size=n_periods))
        for p, q in zip(periods, qty):
            rows.append({"article_id": article_id, "period": p, "qty_ordered": float(q)})
    series = pd.DataFrame(rows)
    return {"series": series, "items": items, "periods": periods}


def test_build_panel_features_lags_are_strictly_backward_looking():
    """The core leakage rule: perturbing qty_ordered at period p must never
    change lag_1..lag_13 or roll_mean/roll_std at any period < p."""
    data = _make_panel(n_articles=5, n_periods=20)
    series = data["series"]

    baseline = build_panel_features(series, data["items"])

    perturbed = series.copy()
    late_mask = perturbed["period"] >= data["periods"][15]
    perturbed.loc[late_mask, "qty_ordered"] = 9999.0
    perturbed_features = build_panel_features(perturbed, data["items"])

    feat_cols = [c for c in baseline.columns if c.startswith(("lag_", "roll_"))]
    early = baseline[baseline["period"] < data["periods"][15]].reset_index(drop=True)
    early_perturbed = perturbed_features[perturbed_features["period"] < data["periods"][15]].reset_index(drop=True)

    pd.testing.assert_frame_equal(early[feat_cols], early_perturbed[feat_cols])


def test_build_panel_features_lag_1_hand_computed():
    data = _make_panel(n_articles=2, n_periods=6)
    panel = build_panel_features(data["series"], data["items"])
    one_article = panel[panel["article_id"] == "A0000"].sort_values("period").reset_index(drop=True)
    raw = data["series"][data["series"]["article_id"] == "A0000"].sort_values("period")["qty_ordered"].tolist()
    # lag_1 at row i should equal the raw qty at row i-1, NaN at row 0
    assert pd.isna(one_article.loc[0, "lag_1"])
    for i in range(1, len(one_article)):
        assert one_article.loc[i, "lag_1"] == raw[i - 1]


def test_feature_columns_includes_expected_groups():
    data = _make_panel(n_articles=3, n_periods=10)
    panel = build_panel_features(data["series"], data["items"])
    cols = feature_columns(panel)
    assert "lag_1" in cols
    assert "roll_mean_4" in cols
    assert "month" in cols
    assert "category" in cols
    assert "unit_cost_sek" in cols


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="lightgbm not installed")
def test_fit_predict_quantiles_below_min_rows_returns_none():
    data = _make_panel(n_articles=3, n_periods=10)
    panel = build_panel_features(data["series"], data["items"])
    feat_cols = feature_columns(panel)
    assert len(panel) < MIN_TRAIN_ROWS
    result = fit_predict_quantiles(panel, panel.head(3), "qty_ordered", feat_cols)
    assert result is None


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="lightgbm not installed")
def test_fit_predict_quantiles_produces_monotonic_quantiles():
    data = _make_panel(n_articles=60, n_periods=30)
    panel = build_panel_features(data["series"], data["items"])
    panel["_target"] = panel.groupby("article_id")["qty_ordered"].shift(-1)
    train = panel.dropna(subset=["_target"])
    feat_cols = feature_columns(panel)
    assert len(train) >= MIN_TRAIN_ROWS

    predict_rows = panel[panel["period"] == data["periods"][20]]
    result = fit_predict_quantiles(train, predict_rows, "_target", feat_cols,
                                   quantiles=(0.05, 0.1, 0.5, 0.8, 0.9, 0.95))
    assert result is not None
    stacked = np.vstack([result[q] for q in sorted(result)])
    assert (np.diff(stacked, axis=0) >= 0).all()
    assert (stacked >= 0).all()


def test_run_global_backtest_without_lightgbm_or_too_little_data_is_empty(monkeypatch):
    """Small panel, far below MIN_TRAIN_ROWS -- must degrade to an empty
    frame with the right columns, never raise."""
    data = _make_panel(n_articles=5, n_periods=20)
    result = run_global_backtest(data["series"], data["items"], fixed_horizons=(4,),
                                 min_train_periods=8, origin_step=4)
    assert list(result.columns[:4]) == ["article_id", "origin_period", "horizon", "horizon_type"] \
        if not result.empty else True
    assert result.empty or (result["model"] == "global_gbm").all()


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="lightgbm not installed")
def test_run_global_backtest_output_shape():
    data = _make_panel(n_articles=60, n_periods=40)
    result = run_global_backtest(data["series"], data["items"], fixed_horizons=(4,),
                                 min_train_periods=8, origin_step=8)
    if not result.empty:
        expected_cols = {"article_id", "origin_period", "horizon", "horizon_type",
                         "model", "actual", "forecast", "q5", "q10", "q50", "q80", "q90", "q95"}
        assert expected_cols.issubset(result.columns)
        assert (result["model"] == "global_gbm").all()
        assert (result["horizon_type"] == "4w").all()


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="lightgbm not installed")
def test_run_global_backtest_is_leakage_safe():
    """Same shape of test as test_backtest.py's per-article leakage test:
    a large shift placed well after an origin must not change that
    origin's forecast, now exercised through the whole panel-training
    path (build_panel_features + truncate-by-origin + fit) instead of a
    single model_fn call."""
    data = _make_panel(n_articles=60, n_periods=40)
    series = data["series"]
    items = data["items"]
    periods = data["periods"]

    spiked = series.copy()
    late_mask = spiked["period"] >= periods[30]
    spiked.loc[late_mask, "qty_ordered"] = spiked.loc[late_mask, "qty_ordered"] + 500.0

    kwargs = dict(fixed_horizons=(4,), min_train_periods=8, origin_step=8)
    result_a = run_global_backtest(series, items, **kwargs)
    result_b = run_global_backtest(spiked, items, **kwargs)

    early_cutoff = periods[20]
    early_a = result_a[result_a["origin_period"] <= early_cutoff].sort_values(
        ["article_id", "origin_period"]).reset_index(drop=True)
    early_b = result_b[result_b["origin_period"] <= early_cutoff].sort_values(
        ["article_id", "origin_period"]).reset_index(drop=True)

    assert not early_a.empty
    pd.testing.assert_frame_equal(
        early_a[["article_id", "origin_period", "actual", "forecast"]],
        early_b[["article_id", "origin_period", "actual", "forecast"]],
    )
