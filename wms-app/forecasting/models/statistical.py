"""ETS and Theta (docs/FORECAST_SPEC.md Phase 4, "smooth/erratic"
candidates) -- thin per-article wrappers around statsforecast, matching
the shared model_fn(train, horizon) -> {"point", "quantiles"} contract
every other model in forecasting/models/ follows.

Deliberately NOT a reuse of analysis/demand_forecast.py:forecast_ets():
that function is batch-oriented (many SKUs per call, its own internal
history-sufficiency gating) and built for the live wms-app pipeline, not
for being called once per (article, origin) inside backtest.py's rolling-
origin loop -- reusing it here would mean constructing a whole
history DataFrame and re-deriving eligibility per call for no benefit.
Measured: a single-article statsforecast call (AutoETS or Theta) takes
~2-10ms, cheap enough for the backtest loop's scale (see the Phase 4
report for the actual full-run timing) -- this is genuinely a thin
wrapper, not a reimplementation of the modeling logic itself, which still
comes from statsforecast.

Quantiles are approximated from statsforecast's native prediction
intervals: level=[60, 80, 90] gives hi-60≈q80, lo-80/hi-80≈q10/q90,
lo-90/hi-90≈q5/q95 (a level-L interval is [q_(100-L)/2, q_100-(100-L)/2]
under the symmetric assumption these libraries already make internally).
Approximate, not conformally calibrated -- that precision is Phase 5's
job, not this one's.
"""

from __future__ import annotations

import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, Theta

DEFAULT_QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
MIN_PERIODS = 7  # same floor analysis/demand_forecast.py verified empirically for AutoETS

# AutoETS's own internal variance estimate can blow up on some real series
# (found on M3 data, docs/FORECAST_SPEC.md Phase 10: one series' q90 reached
# 1.7e10 against a point forecast near 2,450 and a training maximum around
# 13,000 -- a genuine property of that fitted ETS model, not an arithmetic
# bug here, but not a usable number for any downstream consumer either, e.g.
# forecasting/policy.py's reorder point would inherit the same absurdity).
# SANITY_BOUND_MULTIPLIER caps every quantile at this many times the
# largest value ever observed in training -- generous headroom for real
# growth (20x the historical peak), while still ruling out a
# multi-order-of-magnitude blowup.
SANITY_BOUND_MULTIPLIER = 20


def _quantiles_from_levels(point: float, lo80: float, hi80: float, lo90: float, hi90: float,
                           hi60: float, quantiles) -> dict:
    lookup = {0.5: point, 0.1: lo80, 0.9: hi80, 0.05: lo90, 0.95: hi90, 0.8: hi60}
    return {q: max(lookup.get(q, point), 0.0) for q in quantiles}


def _clip_to_sane_bound(point: float, quantiles: dict, train: pd.Series) -> tuple[float, dict]:
    """See SANITY_BOUND_MULTIPLIER's own comment for why this exists.
    A no-op (returns point/quantiles unchanged) whenever training has no
    positive history to bound against -- nothing sane to compare a
    forecast to for a series that never showed a positive value."""
    if len(train) == 0:
        return point, quantiles
    bound = float(train.max()) * SANITY_BOUND_MULTIPLIER
    if bound <= 0:
        return point, quantiles
    return min(point, bound), {q: min(v, bound) for q, v in quantiles.items()}


def _fit_and_forecast(model, train: pd.Series, horizon: int, quantiles) -> dict:
    if len(train) < MIN_PERIODS:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}

    mdf = pd.DataFrame({
        "unique_id": "x",
        "ds": pd.date_range("2000-01-01", periods=len(train), freq="W"),
        "y": train.to_numpy(dtype=float),
    })
    try:
        sf = StatsForecast(models=[model], freq="W", n_jobs=1)
        fc = sf.forecast(df=mdf, h=horizon, level=[60, 80, 90])
    except Exception:
        # AutoETS/Theta can raise on pathological series (e.g. all-zero,
        # or too little effective variation for the optimizer) -- a flat
        # zero forecast beats crashing the whole backtest run over one
        # article, same "degrade, don't crash" principle as the rest of
        # this module.
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}

    name = model.alias
    row = fc.iloc[-1]  # constant point forecast repeated per horizon step; last row = full horizon
    point = max(float(row[name]), 0.0)
    q = _quantiles_from_levels(
        point,
        lo80=float(row[f"{name}-lo-80"]), hi80=float(row[f"{name}-hi-80"]),
        lo90=float(row[f"{name}-lo-90"]), hi90=float(row[f"{name}-hi-90"]),
        hi60=float(row[f"{name}-hi-60"]),
        quantiles=quantiles,
    )
    point, q = _clip_to_sane_bound(point, q, train)
    return {"point": point, "quantiles": q}


def ets_forecast(train: pd.Series, horizon: int, quantiles=DEFAULT_QUANTILES) -> dict:
    """AutoETS (trend + level, no seasonality here -- season_length=1;
    weekly-seasonal ETS needs 2+ years of history per
    analysis/demand_forecast.py's own MIN_PERIODS_FOR_SEASONAL_ETS
    precedent, not worth the extra fit cost for a Phase 4 baseline
    candidate). Below MIN_PERIODS: flat zero, matching AutoETS's own
    documented behaviour of refusing rather than degrading below that
    floor (see analysis/demand_forecast.py:forecast_ets)."""
    return _fit_and_forecast(AutoETS(season_length=1), train, horizon, quantiles)


def theta_forecast(train: pd.Series, horizon: int, quantiles=DEFAULT_QUANTILES) -> dict:
    """Theta method (Assimakopoulos & Nikolopoulos 2000) -- decomposes the
    series into long-term trend and local curvature "theta lines",
    combines them. Consistently strong in the M3/M4 forecasting
    competitions for smooth series specifically, which is why the spec
    names it alongside ETS for that segment rather than as a general
    replacement."""
    return _fit_and_forecast(Theta(season_length=1), train, horizon, quantiles)
