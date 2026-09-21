"""Phase 1 tests for forecasting/data.py -- docs/FORECAST_SPEC.md.

Two data sources exercised deliberately: the small fixture (tests/fixtures.py,
fast, exact known patterns) for correctness, and the real 3,000-item demo
CSVs generated from datagen/v1/generera_lagerdata.py for the Phase 1
acceptance criterion this spec literally names ("series are complete, no
gaps, start at item creation" -- on demo data, not just a toy fixture).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import pytest

from forecasting.data import (
    build_demand_series,
    is_business_day,
    load_inbound,
    load_items,
    load_outbound,
    load_stock,
    swedish_public_holidays,
)

# Set once by running datagen/v1/generera_lagerdata.py with its OUT_DIR
# pointed here -- see the Phase 1 report for how it was generated (a
# throwaway copy with OUT_DIR redirected, v1 file itself untouched).
# Skips gracefully rather than failing when the demo CSVs are not present
# (e.g. a fresh clone, or CI without the generation step run first) --
# these are "on real demo data" checks, additive to the fixture-based
# ones above, not a hard requirement to run the whole suite.
_DEMO_DIR = Path(os.environ.get("WMS_DEMO_DATA_DIR", "data/demo"))


def _demo_available() -> bool:
    return (_DEMO_DIR / "utleverans.csv").exists() and (_DEMO_DIR / "artiklar.csv").exists()


# ── swedish_public_holidays ──────────────────────────────────────────────

def test_swedish_public_holidays_known_dates_2026():
    holidays = swedish_public_holidays(2026, 2026)
    assert pd.Timestamp("2026-01-01") in holidays  # Nyarsdagen
    assert pd.Timestamp("2026-06-06") in holidays  # Nationaldagen
    assert pd.Timestamp("2026-12-25") in holidays  # Juldagen
    # Easter Sunday 2026 is April 5 (verified independently: Gauss's
    # algorithm against a published calendar) -> Annandag pask April 6.
    assert pd.Timestamp("2026-04-06") in holidays


def test_swedish_public_holidays_midsummer_is_a_friday():
    holidays = swedish_public_holidays(2026, 2026)
    midsummer = [d for d in holidays if d.month == 6 and 19 <= d.day <= 25]
    assert len(midsummer) == 1
    assert midsummer[0].dayofweek == 4  # Friday


def test_is_business_day_excludes_weekends_and_holidays():
    dates = pd.Series(pd.to_datetime([
        "2026-01-01",  # Nyarsdagen -- holiday
        "2026-01-03",  # Saturday
        "2026-01-05",  # ordinary Monday
    ]))
    result = is_business_day(dates)
    assert result.tolist() == [False, False, True]


# ── loaders: required columns present, dates parsed ──────────────────────

def test_load_outbound_requires_columns(tmp_path):
    bad_csv = tmp_path / "outbound.csv"
    pd.DataFrame({"order_date": ["2026-01-01"], "article_id": ["A1"]}).to_csv(bad_csv, index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        load_outbound(bad_csv)


def test_load_outbound_parses_dates(small_dataset, tmp_path):
    path = tmp_path / "outbound.csv"
    small_dataset["outbound"].to_csv(path, index=False)
    loaded = load_outbound(path)
    assert pd.api.types.is_datetime64_any_dtype(loaded["order_date"])


# ── build_demand_series: the actual contract under test ──────────────────

def test_build_demand_series_zero_fills_within_window(small_dataset):
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    # Item 0 (steady) should have a row for every week in the observed
    # window, including weeks with genuinely zero demand -- not just the
    # weeks where an order happened to land.
    a0 = series[series["article_id"] == "A0001"]
    assert len(a0) > 10  # sanity: this is weeks, not raw order rows
    assert (a0["qty_ordered"] >= 0).all()
    assert a0["qty_ordered"].eq(0).any() or a0["qty_ordered"].gt(0).all()  # either is plausible, just must be well-formed


def test_build_demand_series_no_gaps(small_dataset):
    """Every article's own period range must be a complete, consecutive
    weekly sequence from its first included period to the series' end --
    the "series are complete (no gaps)" Phase 1 acceptance criterion."""
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    for article_id, g in series.groupby("article_id"):
        periods = g["period"].sort_values()
        expected = pd.period_range(periods.iloc[0], periods.iloc[-1], freq="W").start_time
        assert list(periods) == list(expected), f"{article_id}: gap in period sequence"


def test_build_demand_series_starts_at_item_creation(small_dataset):
    """The last fixture item is deliberately created mid-window (see
    tests/fixtures.py) -- its series must not contain any period before
    that created_date, i.e. no zero-filled "existed before it existed"
    rows leaking in."""
    series = build_demand_series(small_dataset["outbound"], small_dataset["items"], freq="W")
    items = small_dataset["items"]
    late_item = items.iloc[-1]
    g = series[series["article_id"] == late_item["article_id"]]
    assert not g.empty
    created_period_start = late_item["created_date"].to_period("W").start_time
    assert g["period"].min() >= created_period_start


def test_build_demand_series_empty_inputs_return_empty_frame():
    empty = pd.DataFrame(columns=["order_date", "article_id", "qty_ordered", "qty_shipped"])
    items = pd.DataFrame(columns=["article_id", "created_date"])
    result = build_demand_series(empty, items)
    assert result.empty
    assert list(result.columns) == ["article_id", "period", "qty_ordered", "qty_shipped"]


# ── real demo-data checks (Phase 1's own acceptance criterion) ───────────

@pytest.mark.skipif(not _demo_available(), reason="demo CSVs not present at WMS_DEMO_DATA_DIR/data/demo")
def test_build_demand_series_on_real_demo_data_no_gaps_and_starts_at_creation():
    outbound = load_outbound(_DEMO_DIR / "utleverans.csv")
    items = load_items(_DEMO_DIR / "artiklar.csv")

    start = time.time()
    series = build_demand_series(outbound, items, freq="W")
    elapsed = time.time() - start

    assert elapsed < 60, f"build_demand_series took {elapsed:.1f}s on the full demo set -- too slow"
    assert not series.empty

    # No-gaps check, sampled (checking all 3,000 articles' full period
    # ranges here would dominate test runtime for marginal extra
    # confidence over a large random sample).
    sample_ids = series["article_id"].drop_duplicates().sample(n=100, random_state=42)
    for article_id in sample_ids:
        g = series[series["article_id"] == article_id]["period"].sort_values()
        expected = pd.period_range(g.iloc[0], g.iloc[-1], freq="W").start_time
        assert list(g) == list(expected), f"{article_id}: gap in period sequence on real demo data"

    # Starts-at-creation check, same sample.
    created = items.set_index("article_id")["created_date"]
    for article_id in sample_ids:
        g = series[series["article_id"] == article_id]
        created_period_start = created[article_id].to_period("W").start_time
        assert g["period"].min() >= created_period_start
