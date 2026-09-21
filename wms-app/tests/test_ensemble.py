"""Tests for forecasting/models/ensemble.py -- docs/FORECAST_SPEC.md Phase 4
per-segment model selection and combination."""

from __future__ import annotations

import pandas as pd

from forecasting.models.ensemble import (
    FALLBACK_MODEL,
    combine_forecasts,
    forecast_with_selection,
    score_models_by_segment,
    select_best_model_per_segment,
)


def _fake_backtest_results() -> pd.DataFrame:
    """Two segments (smooth, lumpy), two models (naive, good_model).
    good_model is deliberately exact on smooth, mediocre on lumpy;
    naive is mediocre everywhere -- so the "best per segment" answer is
    known by construction: good_model wins smooth, naive wins lumpy."""
    rows = []
    for article_id, segment in [("A1", "smooth"), ("A2", "smooth"), ("A3", "lumpy"), ("A4", "lumpy")]:
        for i in range(20):
            actual = 10.0 if segment == "smooth" else (50.0 if i % 5 == 0 else 0.0)
            rows.append({"article_id": article_id, "model": "good_model", "actual": actual,
                        "q90": actual if segment == "smooth" else actual + 40})
            rows.append({"article_id": article_id, "model": "naive", "actual": actual,
                        "q90": actual + 5 if segment == "smooth" else actual + 5})
    return pd.DataFrame(rows)


def test_score_models_by_segment_hand_verifiable_winner():
    results = _fake_backtest_results()
    segment_lookup = pd.Series({"A1": "smooth", "A2": "smooth", "A3": "lumpy", "A4": "lumpy"})
    scores = score_models_by_segment(results, segment_lookup, quantile=0.9)

    assert set(scores["segment"]) == {"smooth", "lumpy"}
    smooth_best = scores[scores["segment"] == "smooth"].iloc[0]["model"]
    lumpy_best = scores[scores["segment"] == "lumpy"].iloc[0]["model"]
    assert smooth_best == "good_model"
    assert lumpy_best == "naive"


def test_score_models_by_segment_empty_input():
    scores = score_models_by_segment(pd.DataFrame(), pd.Series(dtype=object))
    assert scores.empty
    assert list(scores.columns) == ["segment", "model", "pinball_q90", "n_observations"]


def test_select_best_model_per_segment_matches_scores():
    results = _fake_backtest_results()
    segment_lookup = pd.Series({"A1": "smooth", "A2": "smooth", "A3": "lumpy", "A4": "lumpy"})
    scores = score_models_by_segment(results, segment_lookup, quantile=0.9)
    selection = select_best_model_per_segment(scores, quantile=0.9)
    assert selection == {"smooth": "good_model", "lumpy": "naive"}


def test_select_best_model_per_segment_empty_scores():
    assert select_best_model_per_segment(pd.DataFrame()) == {}


def test_forecast_with_selection_uses_selected_model():
    calls = []

    def model_a(train, horizon, quantiles):
        calls.append("a")
        return {"point": 1.0, "quantiles": {q: 1.0 for q in quantiles}}

    def model_b(train, horizon, quantiles):
        calls.append("b")
        return {"point": 2.0, "quantiles": {q: 2.0 for q in quantiles}}

    models = {"model_a": model_a, "model_b": model_b, "naive": model_a}
    selection = {"smooth": "model_b"}
    result = forecast_with_selection(pd.Series([1, 2, 3]), 4, "smooth", selection, models,
                                     quantiles=(0.5,))
    assert result["point"] == 2.0
    assert calls == ["b"]


def test_forecast_with_selection_falls_back_when_segment_unscored():
    calls = []

    def naive(train, horizon, quantiles):
        calls.append(FALLBACK_MODEL)
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}

    models = {"naive": naive}
    result = forecast_with_selection(pd.Series([1, 2, 3]), 4, "unscored_segment", {}, models,
                                     quantiles=(0.5,))
    assert result["point"] == 0.0
    assert calls == ["naive"]


def test_combine_forecasts_equal_weight_average():
    results = [
        {"point": 10.0, "quantiles": {0.5: 10.0, 0.9: 15.0}},
        {"point": 20.0, "quantiles": {0.5: 20.0, 0.9: 25.0}},
    ]
    combined = combine_forecasts(results, quantiles=(0.5, 0.9))
    assert combined["point"] == 15.0
    assert combined["quantiles"][0.5] == 15.0
    assert combined["quantiles"][0.9] == 20.0


def test_combine_forecasts_missing_quantile_falls_back_to_point():
    results = [
        {"point": 10.0, "quantiles": {0.5: 10.0}},   # no 0.9 key
        {"point": 20.0, "quantiles": {0.5: 20.0, 0.9: 30.0}},
    ]
    combined = combine_forecasts(results, quantiles=(0.5, 0.9))
    # model 1 contributes its own point (10.0) in place of a missing 0.9
    assert combined["quantiles"][0.9] == (10.0 + 30.0) / 2


def test_combine_forecasts_empty_list():
    combined = combine_forecasts([], quantiles=(0.5, 0.9))
    assert combined["point"] == 0.0
    assert combined["quantiles"] == {0.5: 0.0, 0.9: 0.0}
