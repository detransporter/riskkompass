"""Lead-time demand distribution and conformal calibration
(docs/FORECAST_SPEC.md Phase 5).

Two things get combined here, both genuinely uncertain: HOW MUCH demand
occurs, and HOW LONG the replenishment lead time actually turns out to be.
Textbook safety-stock formulas usually assume both are normally
distributed and combine their variances analytically -- a poor fit for
the intermittent/lumpy demand that dominates this demo estate (Phase 3
segmentation: lumpy 1,420 + intermittent 1,266 of 3,000 articles), and an
even worse fit for lead time, which is not remotely normal (a supplier
that is usually 10 days but occasionally 40 has a long right tail, not a
symmetric spread around a mean).

Monte Carlo instead: draw a lead time from its own EMPIRICAL distribution
(receipt_date - po_date, per docs/FORECAST_SPEC.md Phase 5, "per
supplier"), bootstrap that many periods of demand from the article's own
recent history (same empirical-bootstrap idea forecasting/models/
intermittent.py:bootstrap_forecast() already uses for lumpy demand, reused
here rather than reimplemented as a different mechanism), sum, repeat many
times, take empirical quantiles of the totals. No distributional
assumption on either side -- matches this codebase's Phase 4 finding that
the fancier structured models did not out-forecast simple empirical
methods on this data, so there is no evidence a parametric shortcut would
help here either.

Conformal calibration (conformalized quantile regression, Romano/Patterson/
Candes 2019) is a small hand-written implementation, not mapie
(requirements-forecast.txt's own note: "a small hand-written numpy
implementation instead of pulling in mapie at all -- not needed yet").
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
DEFAULT_N_SIMULATIONS = 1000
MIN_LEAD_TIME_SAMPLES = 5  # fewer than this and the empirical spread is not trustworthy


def build_supplier_lead_time_table(inbound: pd.DataFrame) -> pd.DataFrame:
    """One row per RECEIVED purchase-order line: supplier_id, po_date,
    receipt_date, lead_time_days, is_partial (qty_received < qty_ordered).

    'Open' lines (no receipt_date yet -- still in transit) are dropped
    here: they have no observed lead time to contribute. Partial
    deliveries are KEPT, not dropped -- the time it took to receive
    SOMETHING is still a real observation of that supplier's lead time,
    even when the quantity fell short; the quantity shortfall is a
    separate reliability signal (is_partial), reported alongside rather
    than used to censor the lead-time sample itself.
    """
    df = inbound[inbound["status"] == "Received"].copy()
    df = df.dropna(subset=["receipt_date"])
    df["lead_time_days"] = (df["receipt_date"] - df["po_date"]).dt.days
    df["is_partial"] = df["qty_received"] < df["qty_ordered"]
    return df[["po_number", "po_line", "supplier_id", "article_id", "po_date", "receipt_date",
              "lead_time_days", "is_partial"]]


def supplier_lead_time_samples(lead_time_table: pd.DataFrame, supplier_id: str,
                               as_of: pd.Timestamp | None = None,
                               exclude_po: tuple[str, int] | None = None) -> np.ndarray:
    """Lead-time-in-days samples for one supplier, point-in-time filtered
    (only deliveries already RECEIVED by `as_of` count as "known" lead
    time -- the leakage rule this whole phase depends on: a PO that
    hasn't arrived yet cannot inform a forecast made at `as_of`).
    `exclude_po` drops one specific (po_number, po_line) -- used when
    evaluating coverage against that exact PO's own outcome, so its own
    realized lead time never leaks into the distribution used to predict
    it.
    """
    df = lead_time_table[lead_time_table["supplier_id"] == supplier_id]
    if as_of is not None:
        df = df[df["receipt_date"] <= as_of]
    if exclude_po is not None:
        po_number, po_line = exclude_po
        df = df[~((df["po_number"] == po_number) & (df["po_line"] == po_line))]
    return df["lead_time_days"].to_numpy(dtype=float)


def lead_time_demand_distribution(demand_history: pd.Series, lead_time_days_samples: np.ndarray,
                                  review_period_days: float = 7, period_days: float = 7,
                                  n_simulations: int = DEFAULT_N_SIMULATIONS,
                                  quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
                                  recent_window: int = 52, seed: int = 42) -> dict:
    """Monte Carlo distribution of TOTAL demand over (lead time + review
    period). demand_history must already be as_of-filtered by the caller
    (same convention forecasting/backtest.py's model_fn callers follow) --
    this function has no opinion on point-in-time correctness itself, it
    only bootstraps from whatever series it is given.

    Falls back to a fixed `review_period_days`-only window (no lead-time
    uncertainty) when there are fewer than MIN_LEAD_TIME_SAMPLES
    observations for this supplier -- an honest degrade, not a crash, for
    a new supplier with no delivery history yet.

    `recent_window`: only the most recent N periods of demand_history are
    bootstrapped from, not the article's whole history -- a highly
    seasonal or trending series should not have its lead-time-demand
    distribution built from what demand looked like three years ago,
    matching the same "recent, not all-time" instinct
    forecasting/models/baselines.py:moving_average_forecast already
    applies with its own window.
    """
    rng = np.random.default_rng(seed)
    recent_values = demand_history.iloc[-recent_window:].to_numpy(dtype=float) \
        if len(demand_history) else np.array([0.0])
    if len(recent_values) == 0:
        recent_values = np.array([0.0])

    if len(lead_time_days_samples) < MIN_LEAD_TIME_SAMPLES:
        lead_days_draws = np.zeros(n_simulations)  # no lead-time uncertainty to draw from
    else:
        lead_days_draws = rng.choice(lead_time_days_samples, size=n_simulations, replace=True)

    total_days = lead_days_draws + review_period_days
    n_periods_draws = np.maximum(1, np.ceil(total_days / period_days).astype(int))

    totals = np.empty(n_simulations)
    for i, n_periods in enumerate(n_periods_draws):
        sampled = rng.choice(recent_values, size=n_periods, replace=True)
        totals[i] = sampled.sum()

    point = float(np.median(totals))
    q_values = {q: max(float(np.quantile(totals, q)), 0.0) for q in quantiles}
    # "mean" alongside "point" (median) -- forecasting/policy.py's safety-
    # stock formula needs the DISTRIBUTION MEAN specifically ("expected
    # lead-time demand", the textbook newsvendor term), not the median
    # this dict's "point" key uses everywhere else for a skewed
    # right-tailed lead-time-demand distribution the two differ, and
    # substituting median for mean here would quietly under-state safety
    # stock on exactly the lumpy/intermittent articles it matters most for.
    return {"point": point, "mean": float(totals.mean()), "quantiles": q_values}


def conformal_correction(actual: np.ndarray, lo: np.ndarray, hi: np.ndarray, alpha: float) -> float:
    """Split-conformal correction (conformalized quantile regression,
    Romano/Patterson/Candes 2019): a single additive offset that, applied
    to [lo, hi] on a FRESH set of points from the same distribution as the
    calibration set, gives empirical coverage close to the nominal
    (1-alpha).

    Conformity score per calibration point: how far outside the interval
    the actual fell (positive = outside/under-covered, negative = safely
    inside, since a very-covered point could in principle let the
    interval narrow). The correction is the
    ceil((n+1)(1-alpha))/n empirical quantile of those scores -- the
    standard finite-sample-exact formula, not a plain (1-alpha) quantile
    (which would under-cover slightly on small n).

    Returns 0.0 (no correction) if there are fewer than 2 calibration
    points -- nothing to calibrate against."""
    n = len(actual)
    if n < 2:
        return 0.0
    scores = np.maximum(lo - actual, actual - hi)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level))


def apply_conformal_correction(lo, hi, correction: float):
    """Widen (or narrow, if `correction` is negative) [lo, hi] by
    `correction` on each side, clipped at 0 -- demand cannot be
    negative. lo/hi may be scalars OR array-likes (np.ndarray/pd.Series) --
    np.maximum broadcasts either way, unlike Python's builtin max()."""
    return np.maximum(lo - correction, 0.0), np.maximum(hi + correction, 0.0)
