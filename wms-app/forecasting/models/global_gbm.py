"""Global LightGBM model across all items (docs/FORECAST_SPEC.md Phase 4).

Every other model in forecasting/models/ is fit per article, independently,
using only that article's own history -- fine for an item with years of
steady demand, hopeless for one with eight weeks of history. A single
model trained across the WHOLE panel (article x period rows) pools
information across items instead: a brand-new item still gets a sensible
forecast from what similar items (same category, similar cost, similar
lead time) have done, without any separate "cold-start" branch -- the
spec's "hierarchical pooling (category -> article)" falls out of using
category as an ordinary feature, not as a separate mechanism.

Direct multi-horizon quantile regression: one LightGBM model per (horizon,
quantile) pair, not one model that recurses forward -- avoids compounding
one-step errors across a 26-week horizon, standard practice for this kind
of panel forecasting. This module owns feature engineering and model
fit/predict only; forecasting/backtest.py:run_global_backtest owns the
rolling-origin loop and output-row bookkeeping (kept separate because the
per-article backtest loop in that file cannot express "train once, predict
for every article" -- see that function's docstring).

Deliberately try/except around the lightgbm import, matching
requirements-forecast.txt's comment: ARM (the eventual deploy target)
compatibility for lightgbm's native library is unverified, so a missing
import must degrade (skip the global model, keep the rest of the backtest
running) rather than crash the whole run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from forecasting.data import swedish_public_holidays

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

LAGS = (1, 2, 4, 8, 13)
ROLL_WINDOWS = (4, 13)
DEFAULT_QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
MIN_TRAIN_ROWS = 200  # below this, a global model has nothing meaningful to pool from

LGB_PARAMS = dict(
    num_leaves=15,
    min_data_in_leaf=20,
    learning_rate=0.1,
    n_estimators=150,
    verbosity=-1,
)

ITEM_ATTR_COLS = ["unit_cost_sek", "lead_time_days", "moq", "order_multiple"]


def _holiday_counts_by_period(periods: pd.Series) -> dict:
    """Number of Swedish public holidays falling inside each distinct
    weekly period [period, period+6d] -- computed once per DISTINCT period
    (a few hundred at most, not once per panel row) since the same week is
    shared by every article."""
    unique_periods = periods.drop_duplicates()
    if unique_periods.empty:
        return {}
    holidays = swedish_public_holidays(unique_periods.dt.year.min(), unique_periods.dt.year.max())
    counts = {}
    for p in unique_periods:
        week_days = pd.date_range(p, periods=7)
        counts[p] = sum(1 for d in week_days if d in holidays)
    return counts


def build_panel_features(series: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """One row per (article_id, period): lag/rolling demand features,
    calendar features, and item attributes. Returns the panel with a
    `feature_cols` set of columns ready to hand to LightGBM, plus the
    original article_id/period/qty_ordered columns.

    Leakage rule: every lag/rolling value at period p uses only periods
    strictly before p. Rolling stats are computed on qty_ordered.shift(1)
    (shift BEFORE rolling), so the window never includes the row's own
    period -- the panel-wide version of the same rule
    forecasting/backtest.py's per-article origin slicing already enforces.
    This function itself does not truncate by origin; callers (see
    forecasting/backtest.py:run_global_backtest) truncate the returned
    panel to period <= origin before training on it.
    """
    df = series.sort_values(["article_id", "period"]).reset_index(drop=True).copy()
    grouped = df.groupby("article_id")["qty_ordered"]

    for lag in LAGS:
        df[f"lag_{lag}"] = grouped.shift(lag)
    for window in ROLL_WINDOWS:
        df[f"roll_mean_{window}"] = grouped.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean())
        df[f"roll_std_{window}"] = grouped.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=2).std())

    df["month"] = df["period"].dt.month
    df["quarter"] = df["period"].dt.quarter
    df["iso_week"] = df["period"].dt.isocalendar().week.astype(int)
    df["is_summer"] = df["month"].isin([6, 7, 8]).astype(int)
    holiday_counts = _holiday_counts_by_period(df["period"])
    df["holidays_in_week"] = df["period"].map(holiday_counts).fillna(0).astype(int)

    item_cols = ["article_id", "category", "created_date"] + \
        [c for c in ITEM_ATTR_COLS if c in items.columns]
    df = df.merge(items[item_cols], on="article_id", how="left")
    df["periods_since_created"] = (
        (df["period"] - df["created_date"]).dt.days / 7.0
    ).clip(lower=0)
    df["category"] = df["category"].astype("category")

    return df


def feature_columns(panel: pd.DataFrame) -> list[str]:
    lag_cols = [f"lag_{lag}" for lag in LAGS]
    roll_cols = [f"roll_mean_{w}" for w in ROLL_WINDOWS] + [f"roll_std_{w}" for w in ROLL_WINDOWS]
    calendar_cols = ["month", "quarter", "iso_week", "is_summer", "holidays_in_week"]
    attr_cols = [c for c in ITEM_ATTR_COLS if c in panel.columns] + ["category", "periods_since_created"]
    return [c for c in lag_cols + roll_cols + calendar_cols + attr_cols if c in panel.columns]


def fit_predict_quantiles(train_df: pd.DataFrame, predict_df: pd.DataFrame, target_col: str,
                          feature_cols: list[str], quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
                          ) -> dict[float, np.ndarray] | None:
    """Fits one LightGBM quantile-regression model per quantile on
    train_df, predicts on predict_df. Returns {quantile: predictions
    array} in the same row order as predict_df, or None if lightgbm is
    unavailable, there is too little training data, or predict_df is
    empty -- callers degrade to "no global forecast this origin" rather
    than crash (see run_global_backtest).

    Quantile crossing (a known issue with independently fit quantile
    models -- q10 predicted above q50 for some row) is corrected by
    sorting predictions across quantiles per row; a real but minor
    approximation for a Phase 4 baseline, not the conformal calibration
    Phase 5 is responsible for.
    """
    if not LIGHTGBM_AVAILABLE or len(train_df) < MIN_TRAIN_ROWS or predict_df.empty:
        return None

    X_train = train_df[feature_cols]
    y_train = train_df[target_col]
    X_pred = predict_df[feature_cols]

    raw: dict[float, np.ndarray] = {}
    for q in quantiles:
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, **LGB_PARAMS)
        model.fit(X_train, y_train)
        raw[q] = np.clip(model.predict(X_pred), 0.0, None)

    sorted_q = sorted(quantiles)
    stacked = np.vstack([raw[q] for q in sorted_q])
    stacked = np.maximum.accumulate(stacked, axis=0)  # enforce monotonic quantiles per row
    return {q: stacked[i] for i, q in enumerate(sorted_q)}
