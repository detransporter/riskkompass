"""Per-segment model selection and combination (docs/FORECAST_SPEC.md
Phase 4): "Combination forecasts; per-segment model selection decided by
backtest, stored with the result."

Two separate, deliberately simple mechanisms, not one blended "ensemble"
algorithm:

1. score_models_by_segment / select_best_model_per_segment -- decide,
   from backtest.py's own output, which single model wins each segment
   (Syntetos-Boylan class, ABC, or any other article_id -> label mapping
   the caller supplies). Selection metric is pinball loss at q=0.9,
   matching the exact quantile docs/FORECAST_SPEC.md Phase 4's acceptance
   criterion is stated against -- picking a model that is best at q=0.5
   but worse at q=0.9 would optimize the wrong number for a safety-stock
   decision, which lives at the high quantiles, not the median.

2. combine_forecasts -- a plain equal-weight average across several
   model_fn results, for callers who want a blend rather than a single
   winner. Not backtest-weighted: weighting by backtest performance is
   exactly what per-segment selection already does, so this stays a
   simple average rather than reimplementing that.

Neither function trains anything -- both operate on the outputs of
forecasting/backtest.py and forecasting/models/*.py's own model_fn
contract.
"""

from __future__ import annotations

import pandas as pd

from forecasting.metrics import pinball_loss

SELECTION_QUANTILE = 0.9
FALLBACK_MODEL = "naive"


def score_models_by_segment(backtest_results: pd.DataFrame, segment_lookup: pd.Series,
                            quantile: float = SELECTION_QUANTILE) -> pd.DataFrame:
    """One row per (segment, model): pinball loss at `quantile` aggregated
    over every backtest row belonging to that segment, plus how many
    observations that score rests on (a segment/model pair scored on 8
    rows deserves less trust than one scored on 8,000 -- shown, not
    hidden, per the working agreement's "never claim an improvement
    without numbers").

    segment_lookup: article_id -> label Series (e.g.
    forecasting.segmentation.build_segment_table()'s sbc_class column,
    indexed by article_id) -- passed in rather than recomputed here, this
    module has no opinion on which segmentation a caller wants to score
    against.
    """
    q_col = f"q{int(round(quantile * 100))}"
    loss_col = f"pinball_q{int(round(quantile * 100))}"
    if backtest_results.empty or q_col not in backtest_results.columns:
        return pd.DataFrame(columns=["segment", "model", loss_col, "n_observations"])

    df = backtest_results.copy()
    df["segment"] = df["article_id"].map(segment_lookup)
    df = df.dropna(subset=["segment", q_col, "actual"])

    rows = []
    for (segment, model), g in df.groupby(["segment", "model"]):
        rows.append({
            "segment": segment,
            "model": model,
            loss_col: pinball_loss(g["actual"], g[q_col], quantile),
            "n_observations": len(g),
        })
    return pd.DataFrame(rows).sort_values(["segment", loss_col]).reset_index(drop=True)


def select_best_model_per_segment(scores: pd.DataFrame,
                                  quantile: float = SELECTION_QUANTILE) -> dict[str, str]:
    """{segment: model_name}, the lowest-pinball-loss model per segment.
    An empty `scores` (e.g. no backtest results yet) returns an empty
    dict -- callers must handle a missing segment themselves (see
    forecast_with_selection's FALLBACK_MODEL).

    Ties are broken alphabetically by model name, deterministically --
    NOT left to pandas' default sort. Several baselines routinely tie
    EXACTLY on this codebase's own demo data (e.g. naive/moving_average/
    seasonal_naive/ses all score 4.520776 on the lumpy segment, a real,
    already-documented Phase 4 finding, not a rare edge case) and plain
    `sort_values` uses quicksort by default, which pandas does NOT
    guarantee is stable -- two runs of this exact function against the
    exact same input were observed to pick a DIFFERENT winner among a
    tied group purely from run-to-run sort order, not from any real
    difference in score. That is a genuine reproducibility bug for a
    number this project reports to a user (views/forecast_demo.py shows
    the winning model's name on screen) -- the working agreement's "same
    seed -> identical output" rule extends to this too, even though no
    randomness is involved here, just an unstable sort.
    """
    loss_col = f"pinball_q{int(round(quantile * 100))}"
    if scores.empty:
        return {}
    best = scores.sort_values([loss_col, "model"], kind="stable").groupby("segment", as_index=False).first()
    return dict(zip(best["segment"], best["model"]))


def forecast_with_selection(train: pd.Series, horizon: int, segment: str, selection: dict[str, str],
                            models: dict, quantiles: tuple[float, ...]) -> dict:
    """The glue between select_best_model_per_segment()'s output and
    forecasting one specific article: look up which model won this
    article's segment, call it. Falls back to FALLBACK_MODEL ("naive",
    always present in a sane `models` dict) when the segment has no
    selection at all -- an unscored segment (too few backtest
    observations) must still produce a forecast, not raise."""
    model_name = selection.get(segment)
    if model_name is None or model_name not in models:
        model_name = FALLBACK_MODEL
    return models[model_name](train, horizon, quantiles=quantiles)


def combine_forecasts(results: list[dict], quantiles: tuple[float, ...]) -> dict:
    """Plain equal-weight average of several model_fn-style {"point",
    "quantiles"} results. Quantiles missing from an individual result
    fall back to that result's own point forecast before averaging (same
    convention forecasting/backtest.py uses when assembling qNN columns),
    so one model lacking a particular quantile does not silently drop out
    of the average and skew it toward the others."""
    if not results:
        return {"point": 0.0, "quantiles": {q: 0.0 for q in quantiles}}
    point = sum(r["point"] for r in results) / len(results)
    combined_q = {
        q: sum(r["quantiles"].get(q, r["point"]) for r in results) / len(results)
        for q in quantiles
    }
    return {"point": point, "quantiles": combined_q}
