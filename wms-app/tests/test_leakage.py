"""No-data-leakage tests -- docs/FORECAST_SPEC.md working agreement:
"a forecast made at origin date T may only use data dated <= T... add a
test that proves this (e.g. shifting future data must not change past
forecasts)".

Two things proven here, not just asserted in a docstring:

1. build_demand_series() (forecasting/data.py) IS leakage-safe: adding
   future outbound rows never changes the series values for periods
   before those rows. True by construction (a simple groupby-sum, no
   forward-looking window), but "true by construction" is exactly the
   kind of claim that should have a test instead of just a comment.

2. flag_outliers()/flag_one_off_large_orders() (forecasting/cleaning.py)
   are NOT leakage-safe when applied to a full historical series -- this
   is a real, demonstrated property, not a hypothetical caveat. A period's
   flag can change depending on whether later data was included in the
   batch, because both functions compute their threshold (median/MAD or
   mean/std) over whatever series they are given. flag_censored and
   flag_level_shifts, by contrast, ARE leakage-safe (row-wise and strictly
   backward-looking-window respectively) -- proven here too, not just
   claimed in cleaning.py's docstring.

This matters concretely for Phase 2's backtest: reusing a batch-cleaned
series' outlier/spike flags across every rolling origin would silently
leak future information into what is supposed to be a "what did we know
at time T" evaluation. Phase 2 must recompute those two flags per origin.
"""

from __future__ import annotations

import pandas as pd

from forecasting.cleaning import flag_censored, flag_level_shifts, flag_one_off_large_orders, flag_outliers
from forecasting.data import build_demand_series


def _outbound_row(date, article_id, qty_ordered, qty_shipped=None):
    return {
        "order_date": pd.Timestamp(date), "order_id": f"SO-{date}-{article_id}",
        "order_line": 1, "article_id": article_id, "customer_id": "K0001",
        "qty_ordered": qty_ordered, "qty_shipped": qty_shipped if qty_shipped is not None else qty_ordered,
    }


def _items_row(article_id, created_date="2026-01-01"):
    return {"article_id": article_id, "created_date": pd.Timestamp(created_date)}


# ── build_demand_series: must be leakage-safe ────────────────────────────

def test_build_demand_series_past_periods_unchanged_by_future_data():
    items = pd.DataFrame([_items_row("A1")])

    past_only = pd.DataFrame([
        _outbound_row("2026-01-05", "A1", 10),
        _outbound_row("2026-01-19", "A1", 12),
        _outbound_row("2026-02-02", "A1", 8),
    ])
    with_future = pd.concat([
        past_only,
        pd.DataFrame([
            _outbound_row("2026-03-01", "A1", 999),   # far-future, large
            _outbound_row("2026-03-15", "A1", 1),
        ]),
    ], ignore_index=True)

    series_past = build_demand_series(past_only, items, freq="W")
    series_full = build_demand_series(with_future, items, freq="W")

    cutoff = pd.Timestamp("2026-02-02")
    a = series_past[series_past["period"] <= cutoff].reset_index(drop=True)
    b = series_full[series_full["period"] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


# ── flag_censored: row-wise, must be leakage-safe ────────────────────────

def test_flag_censored_is_row_wise_and_leakage_safe():
    outbound = pd.DataFrame([
        _outbound_row("2026-01-05", "A1", 10, qty_shipped=10),
        _outbound_row("2026-01-12", "A1", 10, qty_shipped=6),   # censored
        _outbound_row("2026-06-01", "A1", 10, qty_shipped=10),  # far future, irrelevant
    ])
    flags_full = flag_censored(outbound)
    flags_past = flag_censored(outbound.iloc[:2])
    assert flags_full.iloc[:2].tolist() == flags_past.tolist()


# ── flag_level_shifts: rolling-backward, must be leakage-safe ────────────

def test_flag_level_shifts_is_leakage_safe():
    periods = pd.date_range("2026-01-05", periods=20, freq="W")
    # A level shift that happens strictly in the past relative to the cutoff.
    qty = [5] * 8 + [20] * 12
    series = pd.DataFrame({"article_id": ["A1"] * 20, "period": periods, "qty_ordered": qty})

    cutoff_idx = 14  # well past the shift (index 8) and past window=6's reach
    past = series.iloc[:cutoff_idx].reset_index(drop=True)
    full = series  # includes 6 more periods after cutoff

    flags_past = flag_level_shifts(past, window=6)
    flags_full = flag_level_shifts(full, window=6)
    assert flags_past.tolist() == flags_full.iloc[:cutoff_idx].tolist()


# ── flag_outliers / flag_one_off_large_orders: NOT leakage-safe as batch
#    statistics -- demonstrated, not just asserted in a comment ──────────

def test_flag_outliers_batch_statistics_leak_future_information():
    """A moderately-elevated PAST period's outlier flag can change
    depending on whether several much-larger FUTURE periods were included
    in the same batch -- because median/MAD are both computed over
    whatever series is passed in. This is the exact leakage risk
    cleaning.py's docstring warns about, proven concretely rather than
    left as an unverified claim.

    Needs several future points, not just one, to actually flip the flag
    -- MAD is a robust statistic precisely because a single extra point
    barely moves the median or MAD of an 11-point group (verified: one
    future outlier of 500 was not enough here). That robustness is a
    genuine property, not a loophole in this test -- it does not mean
    "safe", only "harder to demonstrate with a single future row"; a
    demand series realistically accumulates many future periods before a
    backtest origin moves past them, so this is still the risk Phase 2
    must guard against, not an edge case."""
    periods = pd.date_range("2026-01-05", periods=16, freq="W")
    past_qty = [5, 4, 6, 5, 14, 5, 4, 6, 5, 4]  # index 4 = moderately elevated, near the threshold boundary
    past = pd.DataFrame({
        "article_id": ["A1"] * 10, "period": periods[:10], "qty_ordered": past_qty,
    })
    future_qty = [50, 55, 45, 60, 52, 48]  # several future periods at a genuinely different level
    full = pd.concat([
        past,
        pd.DataFrame({"article_id": ["A1"] * 6, "period": periods[10:16], "qty_ordered": future_qty}),
    ], ignore_index=True)

    flags_past_only = flag_outliers(past, mad_multiplier=3.0)
    flags_full = flag_outliers(full, mad_multiplier=3.0)

    # The SAME historical row (index 4) must be checked here -- if its flag
    # differs between the two runs, future data changed a past verdict.
    assert flags_past_only.iloc[4] != flags_full.iloc[4], (
        "expected the future periods to change the past row's flag (demonstrating "
        "leakage) -- if this now fails, re-verify the leakage risk is still real "
        "before assuming flag_outliers became safe to reuse across backtest origins"
    )


def test_flag_one_off_large_orders_batch_statistics_leak_future_information():
    """Leave-one-out fixed the self-masking problem (see cleaning.py and
    the regression test in test_cleaning.py), but leave-one-out is still a
    BATCH statistic over whatever series it is given -- a future period
    enters every other period's leave-one-out mean/std the moment it is
    included in the group, which is exactly the leakage this test
    demonstrates. Fixing self-masking and fixing leakage were two
    different problems; only the first one is actually fixed."""
    periods = pd.date_range("2026-01-05", periods=9, freq="W")
    past_qty = [4, 5, 3, 10, 4, 5, 3, 4]  # index 3 = moderately elevated, near the threshold boundary
    past = pd.DataFrame({
        "article_id": ["A1"] * 8, "period": periods[:8], "qty_ordered": past_qty,
    })
    full = pd.concat([
        past,
        pd.DataFrame({"article_id": ["A1"], "period": [periods[8]], "qty_ordered": [800]}),
    ], ignore_index=True)

    flags_past_only = flag_one_off_large_orders(past, z_threshold=2.5)
    flags_full = flag_one_off_large_orders(full, z_threshold=2.5)

    assert flags_past_only.iloc[3] != flags_full.iloc[3], (
        "expected the future large order to change the past row's flag "
        "(demonstrating leakage) -- see flag_outliers leakage test above for why "
        "this matters for Phase 2's backtest"
    )
