"""Tests for forecasting/monitoring.py -- docs/FORECAST_SPEC.md Phase 8
rolling error, drift detection, manual overrides + FVA, and alerts."""

from __future__ import annotations

import pandas as pd
import pytest

from forecasting.monitoring import (
    compute_override_fva,
    detect_coverage_breach,
    detect_persistent_bias,
    generate_alerts,
    obsolescence_risk,
    record_override,
    rolling_error_by_origin,
    should_retrain,
)


# ── rolling_error_by_origin ────────────────────────────────────────────

def test_rolling_error_hand_computed_single_window():
    periods = pd.date_range("2026-01-05", periods=3, freq="W")
    df = pd.DataFrame({
        "article_id": ["A1"] * 3, "model": ["naive"] * 3, "origin_period": periods,
        "actual": [10.0, 10.0, 10.0], "forecast": [10.0, 12.0, 8.0],
    })
    result = rolling_error_by_origin(df, window=4)
    last = result.sort_values("origin_period").iloc[-1]
    # all 3 origins in one window (window=4 > 3 available): errors [0,2,-2]
    # WAPE = sum(|actual-forecast|)/sum(|actual|) = (0+2+2)/30 = 0.1333
    # bias = sum(forecast-actual)/sum(actual) = (0+2-2)/30 = 0.0
    assert last["rolling_wape"] == pytest.approx(4 / 30)
    assert last["rolling_bias"] == pytest.approx(0.0)


def test_rolling_error_empty_input():
    result = rolling_error_by_origin(pd.DataFrame())
    assert result.empty
    assert "rolling_wape" in result.columns


# ── detect_persistent_bias ──────────────────────────────────────────────

def test_detect_persistent_bias_finds_a_streak():
    periods = pd.date_range("2026-01-05", periods=6, freq="W")
    rolling_df = pd.DataFrame({
        "article_id": ["A1"] * 6, "model": ["naive"] * 6, "origin_period": periods,
        "rolling_wape": [0.1] * 6,
        # over-forecasting (bias > 0.2) for 4 in a row, starting at index 1
        "rolling_bias": [0.05, 0.3, 0.35, 0.4, 0.32, 0.1],
    })
    flagged = detect_persistent_bias(rolling_df, bias_threshold=0.2, min_consecutive=3)
    assert len(flagged) == 1
    row = flagged.iloc[0]
    assert row["article_id"] == "A1"
    assert row["direction"] == "over"
    assert row["streak_length"] == 4


def test_detect_persistent_bias_ignores_short_streaks():
    periods = pd.date_range("2026-01-05", periods=5, freq="W")
    rolling_df = pd.DataFrame({
        "article_id": ["A1"] * 5, "model": ["naive"] * 5, "origin_period": periods,
        "rolling_wape": [0.1] * 5,
        "rolling_bias": [0.3, 0.35, 0.05, 0.05, 0.05],  # only 2 in a row -> below min_consecutive=3
    })
    flagged = detect_persistent_bias(rolling_df, bias_threshold=0.2, min_consecutive=3)
    assert flagged.empty


def test_detect_persistent_bias_direction_switch_resets_streak():
    periods = pd.date_range("2026-01-05", periods=6, freq="W")
    rolling_df = pd.DataFrame({
        "article_id": ["A1"] * 6, "model": ["naive"] * 6, "origin_period": periods,
        "rolling_wape": [0.1] * 6,
        "rolling_bias": [0.3, 0.3, -0.3, -0.3, -0.3, -0.3],  # over x2, then under x4
    })
    flagged = detect_persistent_bias(rolling_df, bias_threshold=0.2, min_consecutive=3)
    assert len(flagged) == 1
    assert flagged.iloc[0]["direction"] == "under"
    assert flagged.iloc[0]["streak_length"] == 4


def test_detect_persistent_bias_empty_input():
    assert detect_persistent_bias(pd.DataFrame()).empty


# ── detect_coverage_breach ────────────────────────────────────────────────

def test_detect_coverage_breach_under_covered():
    events = pd.DataFrame({
        "segment": ["intermittent"] * 10,
        "actual": [100.0] * 3 + [0.0] * 7,  # 3/10 outside [lo,hi] -> 70% coverage
        "q05": [10.0] * 10, "q95": [20.0] * 10,
    })
    breach = detect_coverage_breach(events, "q05", "q95", nominal=0.9, tolerance=0.05)
    assert len(breach) == 1
    assert breach.iloc[0]["breach_direction"] == "under"


def test_detect_coverage_breach_within_tolerance_not_flagged():
    events = pd.DataFrame({
        "segment": ["smooth"] * 10,
        "actual": [15.0] * 9 + [100.0] * 1,  # 90% coverage, exactly nominal
        "q05": [10.0] * 10, "q95": [20.0] * 10,
    })
    breach = detect_coverage_breach(events, "q05", "q95", nominal=0.9, tolerance=0.05)
    assert breach.empty


def test_detect_coverage_breach_over_covered():
    events = pd.DataFrame({
        "segment": ["lumpy"] * 10,
        "actual": [15.0] * 10,  # 100% inside -> over-covered relative to 80% nominal
        "q05": [10.0] * 10, "q95": [20.0] * 10,
    })
    breach = detect_coverage_breach(events, "q05", "q95", nominal=0.8, tolerance=0.05)
    assert len(breach) == 1
    assert breach.iloc[0]["breach_direction"] == "over"


# ── obsolescence_risk ─────────────────────────────────────────────────────

def test_obsolescence_risk_all_four_categories():
    assert obsolescence_risk(is_currently_obsolete=False, recent_forecast_point=0.1) == "emerging"
    assert obsolescence_risk(is_currently_obsolete=True, recent_forecast_point=0.1) == "confirmed"
    assert obsolescence_risk(is_currently_obsolete=True, recent_forecast_point=10.0) == "recovering"
    assert obsolescence_risk(is_currently_obsolete=False, recent_forecast_point=10.0) == "none"


def test_obsolescence_risk_threshold_boundary():
    assert obsolescence_risk(False, 0.5, near_zero_threshold=0.5) == "none"  # not STRICTLY below
    assert obsolescence_risk(False, 0.49, near_zero_threshold=0.5) == "emerging"


# ── should_retrain ─────────────────────────────────────────────────────

def test_should_retrain_any_signal_triggers():
    assert should_retrain(True, False, False) is True
    assert should_retrain(False, True, False) is True
    assert should_retrain(False, False, True) is True
    assert should_retrain(False, False, False) is False


# ── manual overrides + FVA ─────────────────────────────────────────────

def test_record_override_appends_without_mutating_input():
    original = []
    updated = record_override(original, "A1", "2026-01-05", model_forecast=10.0,
                              override_value=15.0, user="david", reason="known promotion")
    assert original == []  # not mutated
    assert len(updated) == 1
    assert updated[0]["article_id"] == "A1"
    assert updated[0]["reason"] == "known promotion"


def test_compute_override_fva_positive_when_override_was_better():
    overrides = [
        {"article_id": "A1", "period": "2026-01-05", "model_forecast": 10.0, "override_value": 18.0},
    ]
    actuals = pd.Series({("A1", "2026-01-05"): 20.0})
    fva = compute_override_fva(overrides, actuals)
    assert len(fva) == 1
    row = fva.iloc[0]
    assert row["model_error"] == pytest.approx(10.0)
    assert row["override_error"] == pytest.approx(2.0)
    assert row["fva"] == pytest.approx(8.0)  # override was 8 units closer -> positive FVA


def test_compute_override_fva_negative_when_override_was_worse():
    overrides = [
        {"article_id": "A1", "period": "2026-01-05", "model_forecast": 20.0, "override_value": 5.0},
    ]
    actuals = pd.Series({("A1", "2026-01-05"): 20.0})
    fva = compute_override_fva(overrides, actuals)
    assert fva.iloc[0]["fva"] == pytest.approx(-15.0)


def test_compute_override_fva_drops_unresolved_overrides():
    overrides = [
        {"article_id": "A1", "period": "2026-01-05", "model_forecast": 10.0, "override_value": 18.0},
        {"article_id": "A2", "period": "2026-02-01", "model_forecast": 5.0, "override_value": 6.0},
    ]
    actuals = pd.Series({("A1", "2026-01-05"): 20.0})  # A2's actual not known yet
    fva = compute_override_fva(overrides, actuals)
    assert len(fva) == 1
    assert fva.iloc[0]["article_id"] == "A1"


def test_compute_override_fva_empty_input():
    result = compute_override_fva([], pd.Series(dtype=float))
    assert result.empty
    assert "fva" in result.columns


# ── generate_alerts ─────────────────────────────────────────────────────

def test_generate_alerts_empty_when_nothing_triggered():
    alerts = generate_alerts("A1", "Testartikel", None, None, False, "none")
    assert alerts == []


def test_generate_alerts_all_four_conditions_at_once():
    persistent_bias_row = {"model": "naive", "direction": "over", "streak_length": 5}
    coverage_breach_row = {"empirical_coverage": 0.7, "breach_direction": "under"}
    alerts = generate_alerts("A1", "Testartikel", persistent_bias_row, coverage_breach_row,
                             demand_shift_flagged=True, obs_risk="confirmed")
    types = {a["type"] for a in alerts}
    assert types == {"persistent_bias", "coverage_breach", "demand_shift", "obsolescence_risk"}
    assert all("Testartikel" in a["message"] for a in alerts)


def test_generate_alerts_recovering_is_info_not_critical():
    alerts = generate_alerts("A1", "Testartikel", None, None, False, "recovering")
    assert len(alerts) == 1
    assert alerts[0]["type"] == "obsolescence_recovering"
    assert alerts[0]["severity"] == "info"
