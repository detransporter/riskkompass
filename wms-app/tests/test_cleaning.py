"""Phase 1 tests for forecasting/cleaning.py -- docs/FORECAST_SPEC.md.

Exercises the fixture's deliberately-planted patterns (tests/fixtures.py:
article A0001 has a clean outlier + a sustained level shift, A0002 has a
censored line), plus the explicit Phase 1 acceptance criterion "on demo
data the censoring flags cover the known stockout lines" against the real
3,000-item demo set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from forecasting.cleaning import (
    flag_censored,
    flag_level_shifts,
    flag_one_off_large_orders,
    flag_outliers,
)
from forecasting.data import build_demand_series, load_outbound

_DEMO_DIR = Path(os.environ.get("WMS_DEMO_DATA_DIR", "data/demo"))


def _demo_available() -> bool:
    return (_DEMO_DIR / "utleverans.csv").exists()


# ── flag_censored ─────────────────────────────────────────────────────────

def test_flag_censored_matches_the_planted_stockout_line(small_dataset):
    outbound = small_dataset["outbound"]
    censored = flag_censored(outbound)
    a0002 = outbound[outbound["article_id"] == "A0003"]  # third fixture item; see fixtures.py idx==2
    # At least one line for that article must be flagged -- the fixture
    # plants exactly one partial-ship line deliberately.
    assert censored[a0002.index].any()
    # And every flagged line must actually have qty_shipped < qty_ordered --
    # not just "some line for this article", the RIGHT line.
    flagged_rows = outbound[censored]
    assert (flagged_rows["qty_shipped"] < flagged_rows["qty_ordered"]).all()


def test_flag_censored_never_flags_fully_shipped_lines(small_dataset):
    outbound = small_dataset["outbound"]
    censored = flag_censored(outbound)
    fully_shipped = outbound["qty_shipped"] >= outbound["qty_ordered"]
    assert not (censored & fully_shipped).any()


# ── flag_outliers ─────────────────────────────────────────────────────────

def test_flag_outliers_catches_the_planted_spike(small_dataset):
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    outliers = flag_outliers(series)
    spike_article = "A0002"  # fixtures.py idx==1: intermittent + planted spike + level shift
    g = series[series["article_id"] == spike_article]
    g_outliers = outliers[g.index]
    assert g_outliers.any(), "the deliberately planted 20x spike was not flagged"
    # The flagged period(s) must actually be near the article's own max --
    # confirms the flag landed on the real spike, not an arbitrary row.
    flagged_values = g.loc[g_outliers[g_outliers].index, "qty_ordered"]
    assert flagged_values.max() == g["qty_ordered"].max()


def test_flag_outliers_constant_demand_never_flagged():
    """MAD == 0 (every period identical) must not divide by zero or flag
    anything -- constant demand cannot have an "outlier" by this metric."""
    series = pd.DataFrame({
        "article_id": ["X"] * 10,
        "period": pd.date_range("2026-01-01", periods=10, freq="W"),
        "qty_ordered": [5] * 10,
    })
    result = flag_outliers(series)
    assert not result.any()


# ── flag_one_off_large_orders ────────────────────────────────────────────

def test_flag_one_off_large_orders_needs_at_least_four_nonzero_periods():
    """Leave-one-out needs n-1 >= 3 remaining points for a std with 2
    degrees of freedom -- below n=4 total, no flags rather than a noisy
    one (see cleaning.py's docstring)."""
    series = pd.DataFrame({
        "article_id": ["X", "X", "X"],
        "period": pd.date_range("2026-01-01", periods=3, freq="W"),
        "qty_ordered": [5, 4, 500],
    })
    result = flag_one_off_large_orders(series)
    assert not result.any(), "fewer than 4 nonzero periods must not produce a (noisy) flag"


def test_flag_one_off_large_orders_catches_a_real_spike():
    rng_values = [4, 5, 3, 6, 4, 5, 3, 50]  # last value is an unmistakable spike
    series = pd.DataFrame({
        "article_id": ["X"] * len(rng_values),
        "period": pd.date_range("2026-01-01", periods=len(rng_values), freq="W"),
        "qty_ordered": rng_values,
    })
    result = flag_one_off_large_orders(series)
    assert result.iloc[-1]
    assert not result.iloc[:-1].any()


def test_flag_one_off_large_orders_self_masking_is_actually_fixed():
    """Regression guard for the leave-one-out design: a self-inclusive
    z-score cannot flag this spike at z_threshold=4.0 no matter how large
    it is (mathematically capped around sqrt(n-1)~2.6 for n=8) -- proves
    the fix, not just that SOME spike gets caught."""
    rng_values = [4, 5, 3, 6, 4, 5, 3, 5000]  # absurdly large, still just 8 points
    series = pd.DataFrame({
        "article_id": ["X"] * len(rng_values),
        "period": pd.date_range("2026-01-01", periods=len(rng_values), freq="W"),
        "qty_ordered": rng_values,
    })
    assert flag_one_off_large_orders(series).iloc[-1]


# ── flag_level_shifts ─────────────────────────────────────────────────────

def test_flag_level_shifts_catches_the_planted_shift(small_dataset):
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    shifts = flag_level_shifts(series)
    shift_article = "A0002"  # same article as the outlier test -- also has a planted level shift
    g = series[series["article_id"] == shift_article]
    assert shifts[g.index].any(), "the planted sustained level shift was not flagged"


def test_flag_level_shifts_flat_series_never_flagged():
    series = pd.DataFrame({
        "article_id": ["X"] * 20,
        "period": pd.date_range("2026-01-01", periods=20, freq="W"),
        "qty_ordered": [10] * 20,
    })
    result = flag_level_shifts(series, window=3)
    assert not result.any()


# ── real demo-data check: Phase 1's explicit acceptance criterion ────────

@pytest.mark.skipif(not _demo_available(), reason="demo CSVs not present at WMS_DEMO_DATA_DIR/data/demo")
def test_censoring_flags_cover_known_stockout_lines_on_real_demo_data():
    outbound = load_outbound(_DEMO_DIR / "utleverans.csv")
    censored = flag_censored(outbound)
    n_censored = int(censored.sum())
    assert n_censored > 0, "demo generator is known to produce stockout-affected lines; found none"
    flagged = outbound[censored]
    assert (flagged["qty_shipped"] < flagged["qty_ordered"]).all()
    # Sanity-check against the fill-rate the generator itself reports
    # (~0.96 observed at generation time, see the Phase 1 report) --
    # loosely bounded since the exact figure depends on the run.
    fill_rate = 1 - (n_censored / len(outbound))
    assert 0.80 < fill_rate < 1.0, f"censoring rate implausible: fill_rate={fill_rate:.3f}"
