"""Rolling-origin backtest engine (docs/FORECAST_SPEC.md Phase 2).

Walks forward through each article's own demand series, picking a
sequence of origins; at each origin, trains every model on data up to and
including that origin ONLY, forecasts forward, and compares against what
actually happened. This is the harness the working agreement requires
before any model claim is allowed ("never claim an improvement without
backtest numbers") -- everything in forecasting/models/ is scored through
this, never eyeballed.

Horizon is two things per docs/FORECAST_SPEC.md Phase 2, not one: fixed
horizons (4/13/26 weeks) so every article is compared on the same terms,
PLUS a lead-time-aligned horizon (that article's own lead_time_days +
a review period) so the number that actually matters operationally --
"how wrong would this forecast have been over the window we'd actually
have to live with it" -- gets its own row too.
"""

from __future__ import annotations

import math

import pandas as pd

from forecasting.models.global_gbm import build_panel_features, feature_columns, fit_predict_quantiles


def lead_time_horizon_periods(lead_time_days: float, review_period_days: float = 7,
                              period_days: float = 7) -> int:
    """Lead-time-aligned horizon, in periods (weeks at the default
    period_days=7) -- ceil((lead time + review period) / period length),
    minimum 1 period. A zero/missing lead_time_days (data quality gap, not
    a real zero-day supplier) still gets at least the review period's
    worth of horizon, never a zero-length forecast window."""
    days = (lead_time_days or 0) + review_period_days
    return max(1, math.ceil(days / period_days))


def _valid_origin_indices(n_periods: int, min_train_periods: int, max_horizon: int,
                          origin_step: int) -> list[int]:
    """0-based indices into an article's own period-sorted series that are
    valid rolling origins: at least min_train_periods of history before
    them (index min_train_periods-1 is the first origin with exactly that
    many training periods), and at least max_horizon periods still ahead
    of them (so every horizon evaluated at this origin has a real actual
    to compare against -- no origin is used for one horizon but not
    another, keeping every model's comparison on the article on the same
    origins)."""
    last_valid = n_periods - max_horizon - 1
    first_valid = min_train_periods - 1
    if last_valid < first_valid:
        return []
    return list(range(first_valid, last_valid + 1, origin_step))


def run_backtest(series: pd.DataFrame, items: pd.DataFrame, models: dict,
                 fixed_horizons: tuple[int, ...] = (4, 13, 26),
                 min_train_periods: int = 8, origin_step: int = 13,
                 review_period_days: float = 7,
                 quantiles: tuple[float, ...] = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)) -> pd.DataFrame:
    """Long-format backtest results: one row per (article_id, origin,
    horizon, model). Columns: article_id, origin_period, horizon,
    horizon_type ("lead_time" or "{h}w"), model, actual, forecast, plus
    one qNN column per quantile in `quantiles` (e.g. q90).

    series: (article_id, period, qty_ordered) from forecasting.data.build_demand_series.
    items: needs at least article_id, lead_time_days.
    models: {name: callable(train: pd.Series, horizon: int) -> {"point", "quantiles"}}.

    Every model at every origin is trained ONLY on
    series[article]["qty_ordered"] up to and including that origin -- this
    is the point-in-time discipline forecasting/cleaning.py's as_of
    parameter exists for too; a caller that wants cleaned/flagged training
    data must pass an already-as_of-filtered `series` in, this function
    itself does not call cleaning.py (keeps the backtest engine agnostic
    to which cleaning flags, if any, a given run wants applied).
    """
    lead_time_by_article = items.set_index("article_id")["lead_time_days"]
    rows: list[dict] = []

    for article_id, g in series.groupby("article_id"):
        g = g.sort_values("period").reset_index(drop=True)
        qty = g["qty_ordered"]
        n = len(g)

        lt_days = lead_time_by_article.get(article_id)
        lt_horizon = lead_time_horizon_periods(lt_days, review_period_days)
        horizon_labels = {h: f"{h}w" for h in fixed_horizons}
        horizon_labels[lt_horizon] = horizon_labels.get(lt_horizon, "lead_time")
        # If the lead-time horizon happens to coincide with a fixed one,
        # the fixed label wins (more informative than "lead_time" alone)
        # -- reinstate it after the dict-merge above may have overwritten it.
        if lt_horizon in fixed_horizons:
            horizon_labels[lt_horizon] = f"{lt_horizon}w"
        else:
            horizon_labels[lt_horizon] = "lead_time"
        all_horizons = sorted(horizon_labels)

        max_h = max(all_horizons)
        origins = _valid_origin_indices(n, min_train_periods, max_h, origin_step)

        for origin_idx in origins:
            train = qty.iloc[:origin_idx + 1]
            origin_period = g["period"].iloc[origin_idx]

            for h in all_horizons:
                target_idx = origin_idx + h
                if target_idx >= n:
                    continue
                actual = float(qty.iloc[target_idx])

                for model_name, model_fn in models.items():
                    result = model_fn(train, h, quantiles=quantiles)
                    row = {
                        "article_id": article_id,
                        "origin_period": origin_period,
                        "horizon": h,
                        "horizon_type": horizon_labels[h],
                        "model": model_name,
                        "actual": actual,
                        "forecast": result["point"],
                    }
                    for q in quantiles:
                        row[f"q{int(round(q * 100))}"] = result["quantiles"].get(q, result["point"])
                    rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["article_id", "origin_period", "horizon", "horizon_type",
                                     "model", "actual", "forecast"])
    return pd.DataFrame(rows)


def run_global_backtest(series: pd.DataFrame, items: pd.DataFrame,
                        fixed_horizons: tuple[int, ...] = (4, 13, 26),
                        min_train_periods: int = 8, origin_step: int = 13,
                        quantiles: tuple[float, ...] = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95),
                        model_name: str = "global_gbm") -> pd.DataFrame:
    """Same output schema as run_backtest() (so results from the two can be
    concatenated for the per-segment comparison docs/FORECAST_SPEC.md
    Phase 4 asks for), but a structurally different loop -- this is the
    "train once per origin across the whole panel" path run_backtest()'s
    own per-article loop cannot express (each of its model_fn calls only
    ever sees one article's own history).

    Origins are picked from the shared period grid every article sits on
    (build_demand_series zero-fills every article onto the same weekly
    grid), reusing _valid_origin_indices()'s exact rule so the two
    backtests are comparable on the same origins. horizon_type is always
    "{h}w" here -- no per-article lead-time-aligned horizon, since a
    shared global model trained once per origin cannot also be trained
    once per distinct lead_time_days without fragmenting the training set
    per article; a documented Phase 4 limitation, not an oversight (see
    the Phase 4 report for the numbers this costs).

    Degrades to an empty frame (not a crash) wherever
    global_gbm.fit_predict_quantiles declines to fit -- lightgbm missing,
    or too little training data at an early origin.
    """
    if series.empty:
        return pd.DataFrame(columns=["article_id", "origin_period", "horizon", "horizon_type",
                                     "model", "actual", "forecast"])

    panel = build_panel_features(series, items)
    feat_cols = feature_columns(panel)
    actual_lookup = series.set_index(["article_id", "period"])["qty_ordered"]

    all_periods = sorted(series["period"].unique())
    max_h = max(fixed_horizons)
    origin_idxs = _valid_origin_indices(len(all_periods), min_train_periods, max_h, origin_step)

    rows: list[dict] = []
    for origin_idx in origin_idxs:
        origin_period = all_periods[origin_idx]
        predict_rows = panel[panel["period"] == origin_period]
        if predict_rows.empty:
            continue

        for h in fixed_horizons:
            truncated = panel[panel["period"] <= origin_period].copy()
            truncated["_target"] = truncated.groupby("article_id")["qty_ordered"].shift(-h)
            # Only the target needs to exist -- feature NaNs (e.g. lag_13
            # for an article with 4 weeks of history) are left in on
            # purpose, LightGBM routes missing values natively, and
            # dropping those rows would throw away exactly the cold-start
            # rows the global model's pooling is meant to help with.
            train_df = truncated.dropna(subset=["_target"])

            preds = fit_predict_quantiles(train_df, predict_rows, "_target", feat_cols, quantiles)
            if preds is None:
                continue

            article_ids = predict_rows["article_id"].to_numpy()
            for i, article_id in enumerate(article_ids):
                target_period = origin_period + pd.Timedelta(weeks=h)
                key = (article_id, target_period)
                if key not in actual_lookup.index:
                    continue
                actual = float(actual_lookup.loc[key])
                row = {
                    "article_id": article_id,
                    "origin_period": origin_period,
                    "horizon": h,
                    "horizon_type": f"{h}w",
                    "model": model_name,
                    "actual": actual,
                    "forecast": float(preds[0.5][i]) if 0.5 in preds else float(preds[quantiles[0]][i]),
                }
                for q in quantiles:
                    row[f"q{int(round(q * 100))}"] = float(preds[q][i])
                rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["article_id", "origin_period", "horizon", "horizon_type",
                                     "model", "actual", "forecast"])
    return pd.DataFrame(rows)
