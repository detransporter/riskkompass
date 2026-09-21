"""Baseline forecasting methods (docs/FORECAST_SPEC.md Phase 2): naive,
seasonal naive, moving average, SES. Pure pandas/numpy -- no
statsforecast/statsmodels dependency, per Phase 1-3's "pandas, numpy,
scipy only" scope (those heavier libraries are pinned in
requirements-forecast.txt for the already-vendored analysis/demand_forecast.py
engine, a separate concern this phase does not need to pull in just to
get a baseline running).

See forecasting/models/__init__.py for the shared model_fn(train, horizon)
-> {"point", "quantiles"} contract every function here follows.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_QUANTILES = (0.5, 0.8, 0.9, 0.95)


def _empirical_band(train: pd.Series, point_forecast: float, quantiles) -> dict:
    """Naive prediction interval for a baseline with no native
    distribution: residuals of the training series against ITS OWN point
    forecast (as if `point_forecast` had been predicted throughout),
    empirical quantiles of those residuals added back to the point
    forecast. Crude but honest -- meant to be beaten by better-calibrated
    methods in a later phase (conformal calibration, Phase 5), not
    presented as a competitive interval on its own. Clipped at 0: a
    negative demand quantile is not a meaningful forecast for this
    domain."""
    if len(train) < 2:
        return {q: max(point_forecast, 0.0) for q in quantiles}
    residuals = train - point_forecast
    return {q: max(point_forecast + float(residuals.quantile(q)), 0.0) for q in quantiles}


def naive_forecast(train: pd.Series, horizon: int, quantiles=DEFAULT_QUANTILES) -> dict:
    """Forecast = last observed value, repeated for the whole horizon --
    the simplest possible baseline, and the one Forecast Value Added is
    measured against by convention (docs/FORECAST_SPEC.md working
    agreement)."""
    point = float(train.iloc[-1]) if len(train) else 0.0
    return {"point": point, "quantiles": _empirical_band(train, point, quantiles)}


def seasonal_naive_forecast(train: pd.Series, horizon: int, season_length: int = 52,
                            quantiles=DEFAULT_QUANTILES) -> dict:
    """Forecast = the value observed `season_length` periods ago (52 weeks
    = same week last year, at the default weekly frequency). Falls back to
    naive_forecast when there isn't a full season of training history yet
    -- a "seasonal" comparison against data that doesn't span a season is
    not actually seasonal, it would just be naive with extra steps and a
    misleading name."""
    if len(train) <= season_length:
        return naive_forecast(train, horizon, quantiles)
    point = float(train.iloc[-season_length])
    return {"point": point, "quantiles": _empirical_band(train, point, quantiles)}


def moving_average_forecast(train: pd.Series, horizon: int, window: int = 8,
                            quantiles=DEFAULT_QUANTILES) -> dict:
    """Forecast = mean of the last `window` observed periods."""
    tail = train.iloc[-window:] if len(train) else train
    point = float(tail.mean()) if len(tail) else 0.0
    return {"point": point, "quantiles": _empirical_band(train, point, quantiles)}


def ses_forecast(train: pd.Series, horizon: int, alpha: float = 0.3,
                 quantiles=DEFAULT_QUANTILES) -> dict:
    """Simple Exponential Smoothing: level_t = alpha*y_t + (1-alpha)*level_{t-1}.
    Forecast = the final smoothed level, repeated for the whole horizon --
    SES has no trend component by design (that is what ETS in
    analysis/demand_forecast.py adds; a Phase 4 concern, not this
    baseline)."""
    if len(train) == 0:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}
    level = float(train.iloc[0])
    for y in train.iloc[1:]:
        level = alpha * float(y) + (1 - alpha) * level
    return {"point": level, "quantiles": _empirical_band(train, level, quantiles)}
