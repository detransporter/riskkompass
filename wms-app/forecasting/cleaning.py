"""Demand-series cleaning (docs/FORECAST_SPEC.md Phase 1): censoring,
outlier, one-off-large-order, and level-shift flags.

Every flag here is additive -- it marks a row, it never removes or rewrites
the observed value. The raw qty_ordered/qty_shipped stays the ground
truth; downstream code (backtest, models) decides how much weight to give
a flagged period. Thresholds live in config/forecast.yaml, not here.

Leakage note, read before reusing these in Phase 2's backtest: flag_censored
is per-row and inherently causal (a row's own qty_shipped vs qty_ordered
never depends on any other row). flag_outliers/flag_one_off_large_orders/
flag_level_shifts are BATCH statistics -- computed once over whatever
series is passed in, using that series' own median/mean/std/rolling
windows. Passed the full historical series (as intended here, for
understanding overall data quality), a period's flag can be influenced by
periods that come AFTER it chronologically. That is correct and useful for
a one-off data-quality report, but it is data leakage if reused unchanged
inside a rolling-origin backtest at some origin date T: a flag for period T
must only be computed from data <= T there. flag_level_shifts is the one
exception (its rolling/shift windows are already strictly backward-looking
by construction), but flag_outliers and flag_one_off_large_orders are not.
Phase 2 must recompute those per origin, not reuse a batch run -- see
tests/test_leakage.py, which documents this distinction with a real test.
"""

from __future__ import annotations

import pandas as pd


def _concat_per_article(series: pd.DataFrame, flag_fn) -> pd.Series:
    """Applies `flag_fn(group) -> pd.Series[bool]` per article_id and
    concatenates the results back in the original row order.

    Deliberately NOT series.groupby(...).apply(flag_fn): with exactly one
    group, pandas' groupby-apply is ambiguous about whether a returned
    Series is "one row of aggregated output" or "one value per input row"
    -- observed concretely (not just in the changelog) to transpose a
    single group's boolean Series into a one-row DataFrame instead of
    aligning it back to the original index, silently producing wrong
    results for exactly the single-article case several tests exercise.
    An explicit loop + pd.concat has no such ambiguity regardless of group
    count, at the cost of the loop being Python-level rather than
    vectorised across groups -- still fast in practice (see
    tests/test_data.py's runtime check on the full 3,000-item demo set,
    which exercises the same per-article-loop shape in build_demand_series
    indirectly, and this module's own equivalent check)."""
    if series.empty:
        return pd.Series(dtype=bool)
    parts = [flag_fn(group) for _, group in series.groupby("article_id")]
    return pd.concat(parts).sort_index()


def flag_censored(outbound: pd.DataFrame) -> pd.Series:
    """True where qty_shipped < qty_ordered: unconstrained demand
    (qty_ordered, the spec's demand definition) could not be fully
    observed that period -- a stockout-affected line. Purely row-wise, so
    this alone never leaks (see module docstring)."""
    return outbound["qty_shipped"] < outbound["qty_ordered"]


def flag_outliers(series: pd.DataFrame, qty_col: str = "qty_ordered",
                  mad_multiplier: float = 6.0) -> pd.Series:
    """Per-article modified z-score outlier flag via MAD (median absolute
    deviation) -- robust to the fact that intermittent/lumpy demand already
    has huge natural variance, where a plain std-dev threshold would flag
    half of a lumpy article's real demand as "outliers". Standard modified
    z-score formulation (Iglewicz & Hoaglin): 0.6745 * (x - median) / MAD.
    An article whose demand never varies (MAD == 0) gets no flags at all,
    not a divide-by-zero -- constant demand cannot have an "outlier" by
    this definition."""
    def _flag(group: pd.DataFrame) -> pd.Series:
        med = group[qty_col].median()
        mad = (group[qty_col] - med).abs().median()
        if mad == 0:
            return pd.Series(False, index=group.index)
        modified_z = 0.6745 * (group[qty_col] - med) / mad
        return modified_z.abs() > mad_multiplier

    return _concat_per_article(series, _flag)


def flag_one_off_large_orders(series: pd.DataFrame, qty_col: str = "qty_ordered",
                              z_threshold: float = 4.0) -> pd.Series:
    """Per-article LEAVE-ONE-OUT z-score flag computed on NONZERO periods
    only. Leave-one-out (excluding the candidate point itself from the
    mean/std it is scored against), not a plain self-inclusive z-score --
    a self-inclusive z-score has a hard mathematical ceiling for small n
    (with n points, no single point's z-score can exceed roughly
    sqrt(n-1), REGARDLESS of how extreme it is, because the point inflates
    its own std as it grows -- verified concretely: with n=8 a value of
    500 among small single-digit neighbours scored z~2.5, and z stayed
    within a few percent of that ceiling even pushed to 5,000). Real SME
    demand series routinely have well under sqrt(4.0^2+1)=17 nonzero
    periods for a given article, which would make z_threshold=4.0
    mathematically unreachable with the naive (self-inclusive) formula no
    matter how real the spike is. Leave-one-out removes that ceiling --
    same principle as Grubbs' test for outliers, standard practice for
    exactly this small-n masking problem.

    "Nonzero periods only" for the same reason as before: including zero
    periods would inflate the reference mean/std with values a genuine
    spike is not being compared against (the article's own normal ordering
    behaviour, not its overall pick-vs-no-pick pattern -- that is
    classify_sbc()'s job in analysis/demand_forecast.py, a different
    question). Fewer than 4 nonzero periods is not enough to leave one out
    and still have 2 degrees of freedom left for the remaining std -- no
    flags rather than a noisy one.
    """
    def _flag(group: pd.DataFrame) -> pd.Series:
        nonzero = group.loc[group[qty_col] > 0, qty_col]
        n = len(nonzero)
        if n < 4:
            return pd.Series(False, index=group.index)

        total, total_sq = nonzero.sum(), (nonzero ** 2).sum()
        n_loo = n - 1
        mean_loo = (total - nonzero) / n_loo
        ss_loo = total_sq - nonzero ** 2
        var_loo = (ss_loo - n_loo * mean_loo ** 2) / (n_loo - 1)
        std_loo = var_loo.clip(lower=0) ** 0.5

        z = pd.Series(0.0, index=group.index)
        valid = std_loo > 0
        z.loc[nonzero.index[valid]] = (nonzero[valid] - mean_loo[valid]) / std_loo[valid]
        return z > z_threshold

    return _concat_per_article(series, _flag)


def flag_level_shifts(series: pd.DataFrame, qty_col: str = "qty_ordered",
                      window: int = 6, shift_ratio: float = 2.5,
                      min_window_qty: float = 1.0) -> pd.Series:
    """Per-article level-shift flag: the ratio between a trailing
    `window`-period mean and the `window`-period mean immediately before
    it. A genuine step change shows as a SUSTAINED ratio jump across a
    whole window, not a one-period spike -- flag_one_off_large_orders
    already catches single-period spikes separately, deliberately not
    merged into this signal (same "two signals catch different failures"
    reasoning wms-app's DOS-vs-recency split already uses, see
    wms-app/CLAUDE.md). Both rolling windows here are strictly backward-
    looking by construction -- the one flag in this module that is already
    leakage-safe without recomputation per origin (see module docstring).

    min_window_qty guards against a real bug found and fixed while
    verifying this against the full demo set: for a low-volume/intermittent
    article, both the recent and prior window means are frequently very
    close to zero, and the RATIO between two near-zero numbers is noise,
    not signal -- a single one-unit order landing in an otherwise-empty
    window can swing the ratio past shift_ratio with no real change in the
    article's demand. Measured impact of the bug: 99.5% of all 3,000 demo
    articles got at least one spurious flag before this guard, concentrated
    almost entirely on articles with weekly mean demand near zero (mean
    demand of flagged articles: ~20/week; of never-flagged articles:
    ~0.09/week -- flags were overwhelmingly noise, not signal). Both
    windows must clear min_window_qty before a ratio is even computed."""
    def _flag(group: pd.DataFrame) -> pd.Series:
        g = group.sort_values("period")
        qty = g[qty_col]
        recent = qty.rolling(window).mean()
        prior = qty.shift(window).rolling(window).mean()
        both_meaningful = (recent >= min_window_qty) & (prior >= min_window_qty)
        ratio = (recent / prior.where(prior > 0)).fillna(1.0)
        shifted = both_meaningful & ((ratio > shift_ratio) | (ratio < 1 / shift_ratio))
        return shifted.reindex(group.index)

    return _concat_per_article(series, _flag)
