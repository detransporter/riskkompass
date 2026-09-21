"""Croston, SBA (Syntetos-Boylan Approximation), TSB, and an empirical
bootstrap for intermittent/lumpy demand -- hand-written in pure numpy,
deliberately NOT the statsforecast-based Croston/SBA/TSB already vendored
in analysis/demand_forecast.py. Phase 1-3 stayed on pandas/numpy/scipy
only; Phase 4 (which added statistical.py's statsforecast-based ETS/Theta)
could have reused the vendored versions here too, but kept these
hand-written for consistency within this one file rather than mixing
implementations mid-module (same reasoning as models/baselines.py).

Classic Croston's method (Croston 1972): decomposes an intermittent series
into the SIZE of nonzero demands and the INTERVAL between them, smooths
each with its own exponential smoothing, forecasts size/interval as a
constant rate. SBA (Syntetos & Boylan 2005) applies a bias correction --
Croston's own estimator is provably biased high, SBA multiplies by
(1 - alpha/2) to correct it. See forecasting/models/__init__.py for the
shared model_fn(train, horizon) -> {"point", "quantiles"} contract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_QUANTILES = (0.5, 0.8, 0.9, 0.95)
MIN_OCCURRENCES = 2  # fewer nonzero periods than this: not enough to trust a smoothed interval at all


def _croston_core(train: pd.Series, alpha: float) -> tuple[float, float, int]:
    """Returns (smoothed_size, smoothed_interval, n_occurrences).
    (0.0, 0.0, 0) when there is no nonzero demand at all in `train` --
    callers decide what a flat zero forecast means from n==0."""
    values = train.to_numpy()
    nonzero_idx = np.flatnonzero(values > 0)
    if len(nonzero_idx) == 0:
        return 0.0, 0.0, 0

    sizes = values[nonzero_idx]
    # Periods since the previous occurrence, or since the series start for
    # the very first one (prepend=-1 makes that first "interval" the
    # occurrence's own position + 1, e.g. index 0 -> interval 1).
    intervals = np.diff(nonzero_idx, prepend=-1)

    z = float(sizes[0])
    x = float(intervals[0])
    for i in range(1, len(sizes)):
        z = z + alpha * (sizes[i] - z)
        x = x + alpha * (intervals[i] - x)

    return z, x, len(nonzero_idx)


def _naive_band_from_nonzero(train: pd.Series, point: float, quantiles) -> dict:
    """Same crude empirical-residual band idea as models/baselines.py's
    _empirical_band, restricted to nonzero periods -- a Croston-style
    point forecast is a rate estimated from occurrences, not meant to be
    compared against zero-inflated residuals the way a moving-average
    forecast is."""
    nonzero = train[train > 0]
    if len(nonzero) < 2:
        return {q: max(point, 0.0) for q in quantiles}
    residuals = nonzero - point
    return {q: max(point + float(residuals.quantile(q)), 0.0) for q in quantiles}


def croston_forecast(train: pd.Series, horizon: int, alpha: float = 0.1,
                     quantiles=DEFAULT_QUANTILES) -> dict:
    """Classic Croston point forecast = smoothed_size / smoothed_interval,
    constant across the whole horizon (Croston-family methods have no
    trend component -- see analysis/demand_forecast.py:forecast_ets's
    docstring for why smooth/trending series get routed to ETS instead in
    the full pipeline; this baseline is intentionally simpler). Fewer than
    MIN_OCCURRENCES nonzero periods: flat zero forecast, never a guess
    from 1 data point."""
    z, x, n = _croston_core(train, alpha)
    if n < MIN_OCCURRENCES or x == 0:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}
    point = z / x
    return {"point": point, "quantiles": _naive_band_from_nonzero(train, point, quantiles)}


def sba_forecast(train: pd.Series, horizon: int, alpha: float = 0.1,
                 quantiles=DEFAULT_QUANTILES) -> dict:
    """Croston-SBA: croston_forecast's point estimate times
    (1 - alpha/2), the Syntetos-Boylan bias correction -- strictly
    dominates classic Croston (same mechanism, corrected bias), matching
    the reasoning analysis/demand_forecast.py already documents for
    picking SBA over classic Croston whenever there is a choice."""
    z, x, n = _croston_core(train, alpha)
    if n < MIN_OCCURRENCES or x == 0:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}
    point = (1 - alpha / 2) * z / x
    return {"point": point, "quantiles": _naive_band_from_nonzero(train, point, quantiles)}


def _tsb_core(train: pd.Series, alpha_d: float, alpha_p: float) -> tuple[float, float, int]:
    """Returns (smoothed_size, smoothed_probability, n_occurrences).
    Structurally different from _croston_core: TSB (Teunter, Syntetos &
    Babai 2011) smooths the demand PROBABILITY every single period
    (occurrence or not), not just the interval between occurrences --
    which is exactly what lets its forecast decay toward zero on its own
    when demand fades, unlike Croston/SBA, whose forecast for a SKU that
    stops selling stays flat forever (nothing in their mechanism can make
    it decay -- see analysis/demand_forecast.py:forecast_tsb's docstring,
    same reasoning, independently reimplemented here in pure numpy per
    this module's own no-statsforecast scope)."""
    values = train.to_numpy()
    nonzero_idx = np.flatnonzero(values > 0)
    if len(nonzero_idx) == 0:
        return 0.0, 0.0, 0

    first_idx = int(nonzero_idx[0])
    z = float(values[first_idx])
    # Naive initial probability: one occurrence in (first_idx + 1) periods
    # observed so far -- smoothed away quickly by alpha_p regardless, this
    # is just a reasonable starting point, not load-bearing.
    p = 1.0 / (first_idx + 1)

    for t in range(first_idx + 1, len(values)):
        occurred = values[t] > 0
        p = p + alpha_p * (float(occurred) - p)
        if occurred:
            z = z + alpha_d * (values[t] - z)

    return z, p, len(nonzero_idx)


def tsb_forecast(train: pd.Series, horizon: int, alpha_d: float = 0.1, alpha_p: float = 0.1,
                 quantiles=DEFAULT_QUANTILES) -> dict:
    """TSB point forecast = smoothed_size * smoothed_probability, constant
    across the horizon. Same MIN_OCCURRENCES floor as Croston/SBA -- fewer
    than 2 nonzero periods is not enough to trust either smoothed
    estimate."""
    z, p, n = _tsb_core(train, alpha_d, alpha_p)
    if n < MIN_OCCURRENCES:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}
    point = z * p
    return {"point": point, "quantiles": _naive_band_from_nonzero(train, point, quantiles)}


def bootstrap_forecast(train: pd.Series, horizon: int, n_samples: int = 1000,
                       seed: int = 42, quantiles=DEFAULT_QUANTILES) -> dict:
    """Empirical bootstrap (docs/FORECAST_SPEC.md Phase 4's "bootstrap or
    negative binomial" candidate for LUMPY demand -- high ADI and high
    CV², where both Croston-family methods and ETS/Theta assume more
    structure than lumpy demand actually has). Resamples single-period
    values from the training series' own history WITH REPLACEMENT
    (deliberately including zero periods -- for lumpy demand the
    occurrence pattern itself is part of what is being forecast, unlike
    Croston's separate size/interval decomposition), then uses the
    empirical distribution of those resamples directly as the quantile
    forecast rather than a point estimate plus a residual band. Point =
    median of the resamples (robust to the extreme tail a mean would be
    dragged around by, exactly the lumpy case this method targets).

    All randomness seeded (per the working agreement: same seed -> same
    output). horizon is accepted for interface consistency with every
    other model_fn here but not used to widen the band with distance --
    a real limitation, flagged rather than hidden: this treats a 4-week
    and a 26-week horizon identically, which a properly calibrated method
    should not. Acceptable for a Phase 4 baseline candidate, not
    something to present as calibrated (Phase 5's job)."""
    values = train.to_numpy(dtype=float)
    if len(values) == 0:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}

    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=n_samples, replace=True)
    point = max(float(np.median(samples)), 0.0)
    q_values = {q: max(float(np.quantile(samples, q)), 0.0) for q in quantiles}
    return {"point": point, "quantiles": q_values}
