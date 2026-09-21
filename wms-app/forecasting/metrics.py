"""Forecast accuracy metrics (docs/FORECAST_SPEC.md Phase 2): WAPE, bias,
MASE, pinball loss, interval coverage.

Every function here is pure -- arrays/Series in, a float out, no DataFrame
merging or per-article grouping (backtest.py owns that). Kept this way so
each metric can be unit-tested against a hand-computed value in isolation,
and so nothing here has an opinion about *which* rows belong together --
that is backtest.py's job (per-origin, per-horizon, per-article, or rolled
up per-segment).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wape(actual: pd.Series, forecast: pd.Series) -> float:
    """Weighted Absolute Percentage Error: sum(|actual-forecast|) /
    sum(|actual|). Preferred over plain MAPE for intermittent demand --
    MAPE divides by each individual actual (blows up or is undefined on
    zero-demand periods, which are the norm for lumpy/intermittent
    articles); WAPE divides by the SUM, so zero periods just contribute
    zero to both numerator and denominator instead of a division by zero.

    Undefined (NaN) when actual is all zero -- there is no "percentage of
    nothing", except the corner case where the forecast was also all zero
    (a perfect, if trivial, no-demand call), returned as 0.0."""
    denom = actual.abs().sum()
    if denom == 0:
        return 0.0 if forecast.abs().sum() == 0 else float("nan")
    return float((actual - forecast).abs().sum() / denom)


def bias(actual: pd.Series, forecast: pd.Series) -> float:
    """Signed percentage bias: sum(forecast-actual) / sum(actual).
    Positive = systematic over-forecasting, negative = under-forecasting.
    Same zero-actual handling as wape() (0.0 only if forecast is also all
    zero, NaN otherwise -- there is no meaningful "bias" against nothing)."""
    denom = actual.sum()
    if denom == 0:
        return 0.0 if forecast.sum() == 0 else float("nan")
    return float((forecast - actual).sum() / denom)


def mase(actual: pd.Series, forecast: pd.Series, train_actual: pd.Series,
         seasonality: int = 1) -> float:
    """Mean Absolute Scaled Error (Hyndman & Koehler 2006): MAE of the
    forecast, divided by the in-sample MAE of a naive (or seasonal-naive,
    via `seasonality`) forecast on the TRAINING data -- the same data the
    model itself was allowed to see at the origin, never the held-out
    actuals `actual` is scored against, or this would leak the answer into
    its own scale.

    MASE < 1 means the model beat naive on the training data's own error
    scale; MASE > 1 means naive would have done better. Undefined (NaN)
    when the naive scale itself is zero (a perfectly flat training
    series -- naive is a perfect fit there, nothing to usefully divide
    by)."""
    mae_forecast = (actual - forecast).abs().mean()
    naive_errors = train_actual.diff(seasonality).abs().dropna()
    scale = naive_errors.mean()
    if not scale or pd.isna(scale):
        return float("nan")
    return float(mae_forecast / scale)


def pinball_loss(actual: pd.Series, forecast_q: pd.Series, q: float) -> float:
    """Pinball (quantile) loss at quantile `q`, averaged over all rows.
    Asymmetric by design: under-predicting a high quantile (q close to 1,
    e.g. the level a safety-stock decision is based on) is penalized more
    than over-predicting it, and vice versa for a low quantile -- exactly
    the asymmetry a real inventory decision has (running out is not the
    same cost as holding a bit extra). q=0.5 reduces to half the mean
    absolute error, the symmetric special case."""
    diff = actual.to_numpy() - forecast_q.to_numpy()
    loss = np.where(diff >= 0, q * diff, (q - 1) * diff)
    return float(np.mean(loss))


def coverage(actual: pd.Series, lower: pd.Series, upper: pd.Series) -> float:
    """Fraction of `actual` values falling within [lower, upper]. A
    nominal 90% interval should show empirical coverage near 0.90 in a
    backtest -- systematically lower means the interval is too narrow
    (overconfident), systematically higher means it is wider than it
    needs to be (see docs/FORECAST_SPEC.md Phase 5's 87-93% acceptance
    band for the 90% case)."""
    within = (actual >= lower) & (actual <= upper)
    return float(within.mean())
