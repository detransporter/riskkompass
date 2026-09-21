"""Unit tests for forecasting/segmentation.py on the small fixture --
docs/FORECAST_SPEC.md Phase 3. Real-data validation against facit lives in
tests/test_segmentation_facit.py; this file checks the plumbing (shape,
column presence, lifecycle-flag logic) fast and without needing data/demo/.
"""

from __future__ import annotations

import pandas as pd

from forecasting.segmentation import build_segment_table, flag_new_item, flag_stale_with_stock


def test_build_segment_table_shape_and_columns(small_dataset):
    stock = pd.DataFrame(columns=["article_id", "snapshot_date", "stock_qty", "stock_value_sek"])
    seg = build_segment_table(small_dataset["outbound"], small_dataset["items"], stock)
    assert len(seg) == len(small_dataset["items"])
    expected = {"article_id", "abc_class", "xyz_class", "trend_class", "sbc_class",
               "is_new_item", "is_becoming_obsolete", "is_stale_with_stock"}
    assert expected.issubset(seg.columns)


def test_flag_new_item_uses_calendar_age():
    items = pd.DataFrame({
        "article_id": ["A", "B", "C"],
        "created_date": pd.to_datetime(["2026-01-01", "2026-06-01", "2025-01-01"]),
    })
    as_of = pd.Timestamp("2026-06-15")
    result = flag_new_item(items, as_of, new_item_days=90)
    # A: 165 days old -> not new. B: 14 days old -> new. C: >1 year -> not new.
    assert result.tolist() == [False, True, False]


def test_flag_new_item_future_created_date_is_not_new():
    """A created_date after as_of (bad data, or as_of computed too early)
    must not be flagged new -- negative age is nonsensical, not "very new"."""
    items = pd.DataFrame({"article_id": ["A"], "created_date": pd.to_datetime(["2026-12-01"])})
    result = flag_new_item(items, pd.Timestamp("2026-06-01"), new_item_days=90)
    assert result.tolist() == [False]


def test_flag_stale_with_stock():
    df = pd.DataFrame({
        "stock_qty": [10.0, 0.0, 5.0, 0.0],
        "avg_daily_demand": [0.0, 0.0, 2.0, 3.0],
    })
    result = flag_stale_with_stock(df)
    # row0: stock but no demand -> stale. row1: no stock -> not stale (nothing to be stale about).
    # row2: stock and moving -> not stale. row3: no stock -> not stale.
    assert result.tolist() == [True, False, False, False]
