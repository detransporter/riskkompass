"""Forecasting models (docs/FORECAST_SPEC.md Phase 2 baselines, Phase 4
per-segment models). Every model function shares one contract:

    model_fn(train: pd.Series, horizon: int, **params) -> dict

    train    the training series (already filtered to <= origin by the
             caller -- backtest.py owns the point-in-time cut, models here
             have no opinion about dates)
    horizon  how many periods ahead the point forecast covers (baselines
             return one constant value for the whole horizon; a later
             phase's per-period forecast would return an array instead --
             not needed yet, every model here is flat over its horizon)

    Returns {"point": float, "quantiles": {q: float, ...}} -- "quantiles"
    always has 0.5/0.8/0.9/0.95 unless the caller asked for a different
    set, so metrics.pinball_loss/coverage can score every model the same
    way regardless of whether it has a "real" probabilistic form.
"""
