"""Tests for forecasting/datasets/m3.py -- docs/FORECAST_SPEC.md Phase 10."""

from __future__ import annotations

import pandas as pd
import pytest

from forecasting.datasets.m3 import load_m3_monthly_tsf

SAMPLE_TSF = """# Dataset Information
# A tiny hand-written fixture, not the real M3 file.
@relation M3
@attribute series_name string
@attribute start_timestamp date
@frequency monthly
@horizon 18
@missing false
@equallength false
@data
T1:1990-01-01 00-00-00:10,20,30
T2:1991-06-01 00-00-00:-5,5,5
T3:2000-03-01 00-00-00:1,2,3,4,5
"""


@pytest.fixture
def sample_tsf_path(tmp_path):
    path = tmp_path / "sample.tsf"
    path.write_text(SAMPLE_TSF, encoding="latin-1")
    return path


def test_load_m3_monthly_parses_series_and_values(sample_tsf_path):
    df = load_m3_monthly_tsf(sample_tsf_path)
    t1 = df[df["article_id"] == "T1"].sort_values("period")
    assert list(t1["qty_ordered"]) == [10.0, 20.0, 30.0]
    assert list(t1["period"]) == [pd.Timestamp("1990-01-01"), pd.Timestamp("1990-02-01"),
                                   pd.Timestamp("1990-03-01")]


def test_load_m3_monthly_drops_series_with_negative_values(sample_tsf_path):
    df = load_m3_monthly_tsf(sample_tsf_path)
    assert "T2" not in set(df["article_id"])
    assert "T1" in set(df["article_id"])
    assert "T3" in set(df["article_id"])


def test_load_m3_monthly_respects_different_start_dates(sample_tsf_path):
    df = load_m3_monthly_tsf(sample_tsf_path)
    t3 = df[df["article_id"] == "T3"].sort_values("period")
    assert t3["period"].iloc[0] == pd.Timestamp("2000-03-01")
    assert len(t3) == 5


def test_load_m3_monthly_output_shape(sample_tsf_path):
    df = load_m3_monthly_tsf(sample_tsf_path)
    assert list(df.columns) == ["article_id", "period", "qty_ordered"]
