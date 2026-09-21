"""Monitoring and alerts (docs/FORECAST_SPEC.md Phase 8): rolling forecast
error/bias, drift detection, an auto-retrain trigger, a manual-override
log with Forecast Value Added of human overrides vs. the model, and
exception-based alerts (persistent bias, coverage breach, unexpected
demand shift, obsolescence risk).

Every metric here is computed from tables forecasting/backtest.py,
forecasting/probabilistic.py, and forecasting/segmentation.py already
produce -- this module adds no new forecasting logic of its own, only
turns their outputs into "does a human need to look at this article"
signals. Same CSV/DataFrame-first scope as the rest of forecasting/ (see
forecasting/data.py's own docstring) -- no database access here; a live
override log against wms-app's SQLite tenant schema is a separate adapter
for whoever wires this into the Streamlit UI, not built here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from forecasting.metrics import bias as bias_metric
from forecasting.metrics import wape as wape_metric

DEFAULT_BIAS_THRESHOLD = 0.20
DEFAULT_MIN_CONSECUTIVE = 3
DEFAULT_COVERAGE_TOLERANCE = 0.05
OBSOLESCENCE_NEAR_ZERO = 0.5  # forecast point below this counts as "near zero" for risk categorization


# ── Rolling error / persistent bias ──────────────────────────────────────

def rolling_error_by_origin(backtest_results: pd.DataFrame, window: int = 4) -> pd.DataFrame:
    """Per (article_id, model), sorted by origin_period: rolling WAPE and
    bias over the trailing `window` origins (fewer than `window` origins
    seen so far: computed over however many are available -- min_periods=1,
    an early rolling estimate is still better than none, an article does
    not need `window` origins of history before it gets a first number).

    Only single-horizon rows should be passed in for a clean per-origin
    trend (a mix of e.g. 4-week and 26-week horizon rows in the same
    window would blend errors that are not on the same footing) --
    callers filter `backtest_results` to one horizon before calling this,
    same convention forecasting/backtest.py's own callers already follow
    when they want a single, comparable slice.
    """
    if backtest_results.empty:
        return pd.DataFrame(columns=["article_id", "model", "origin_period", "rolling_wape", "rolling_bias"])

    rows = []
    for (article_id, model), g in backtest_results.groupby(["article_id", "model"]):
        g = g.sort_values("origin_period").reset_index(drop=True)
        for i in range(len(g)):
            lo = max(0, i - window + 1)
            g_window = g.iloc[lo:i + 1]
            rows.append({
                "article_id": article_id, "model": model, "origin_period": g.loc[i, "origin_period"],
                "rolling_wape": wape_metric(g_window["actual"], g_window["forecast"]),
                "rolling_bias": bias_metric(g_window["actual"], g_window["forecast"]),
            })
    return pd.DataFrame(rows)


def detect_persistent_bias(rolling_df: pd.DataFrame, bias_threshold: float = DEFAULT_BIAS_THRESHOLD,
                           min_consecutive: int = DEFAULT_MIN_CONSECUTIVE) -> pd.DataFrame:
    """Flags (article_id, model) where rolling_bias has stayed beyond
    +-bias_threshold, in the SAME direction, for at least
    `min_consecutive` consecutive origins in a row -- a single noisy
    origin crossing the threshold is not persistent bias, a streak is.
    Returns one row per flagged (article_id, model) with the streak
    length and direction ("over" = systematically over-forecasting,
    "under" = systematically under-forecasting).
    """
    if rolling_df.empty:
        return pd.DataFrame(columns=["article_id", "model", "direction", "streak_length"])

    rows = []
    for (article_id, model), g in rolling_df.groupby(["article_id", "model"]):
        g = g.sort_values("origin_period")
        direction = g["rolling_bias"].apply(
            lambda b: "over" if b > bias_threshold else ("under" if b < -bias_threshold else None))
        streak = 0
        streak_dir = None
        max_streak = 0
        max_streak_dir = None
        for d in direction:
            if d is not None and d == streak_dir:
                streak += 1
            elif d is not None:
                streak_dir = d
                streak = 1
            else:
                streak = 0
                streak_dir = None
            if streak > max_streak:
                max_streak = streak
                max_streak_dir = streak_dir
        if max_streak >= min_consecutive:
            rows.append({"article_id": article_id, "model": model,
                        "direction": max_streak_dir, "streak_length": max_streak})
    return pd.DataFrame(rows)


# ── Coverage breach ───────────────────────────────────────────────────────

def detect_coverage_breach(coverage_events: pd.DataFrame, lo_col: str, hi_col: str,
                           nominal: float, tolerance: float = DEFAULT_COVERAGE_TOLERANCE,
                           group_col: str = "segment") -> pd.DataFrame:
    """Empirical coverage per group (segment, or article_id, whatever
    `group_col` is), flagged when it falls outside
    [nominal-tolerance, nominal+tolerance] -- same shape as
    scripts/run_phase5_coverage.py's own per-segment reporting, exposed
    here as a reusable function instead of duplicated print logic so a
    monitoring pipeline can call it directly rather than parsing that
    script's stdout."""
    if coverage_events.empty:
        return pd.DataFrame(columns=[group_col, "empirical_coverage", "breach_direction"])

    rows = []
    for group, g in coverage_events.groupby(group_col):
        cov = ((g["actual"] >= g[lo_col]) & (g["actual"] <= g[hi_col])).mean()
        if cov < nominal - tolerance:
            rows.append({group_col: group, "empirical_coverage": cov, "breach_direction": "under"})
        elif cov > nominal + tolerance:
            rows.append({group_col: group, "empirical_coverage": cov, "breach_direction": "over"})
    return pd.DataFrame(rows)


# ── Obsolescence risk ─────────────────────────────────────────────────────

def obsolescence_risk(is_currently_obsolete: bool, recent_forecast_point: float,
                      near_zero_threshold: float = OBSOLESCENCE_NEAR_ZERO) -> str:
    """One of "emerging" / "confirmed" / "recovering" / "none" -- same
    four-way shape as analysis/demand_forecast.py:forecast_dead_stock_risk()
    (current status vs. a forward-looking forecast), reimplemented against
    THIS module's own segmentation (forecasting/segmentation.py's
    is_becoming_obsolete flag) and forecast (any forecasting/models/*.py
    model_fn's point forecast) rather than reusing that function directly
    -- it expects a different upstream shape (select_forecast_method()'s
    output columns), from the older, since-superseded forecasting engine
    (see wms-app/CLAUDE.md's "Superseded 2026-09-21" note). Same idea,
    consistent with this module's own contracts instead of bridging two
    different ones.

    emerging   -- not currently flagged obsolete, but the forecast is
                  near zero -- a signal nothing in today's trailing status
                  shows yet.
    confirmed  -- currently flagged obsolete AND the forecast agrees.
    recovering -- currently flagged obsolete, but the forecast shows real
                  demand ahead.
    none       -- forecast agrees with "not obsolete"; nothing to flag.
    """
    forecast_near_zero = recent_forecast_point < near_zero_threshold
    if is_currently_obsolete and forecast_near_zero:
        return "confirmed"
    if is_currently_obsolete and not forecast_near_zero:
        return "recovering"
    if not is_currently_obsolete and forecast_near_zero:
        return "emerging"
    return "none"


# ── Auto-retrain trigger ──────────────────────────────────────────────────

def should_retrain(persistent_bias: bool, coverage_breach: bool, demand_shift: bool) -> bool:
    """Any ONE of the three drift signals is enough to trigger a retrain
    -- a deliberately simple OR, not a weighted score: each signal is
    already its own considered threshold (see the functions above), a
    second layer of scoring on top would just be a second set of
    thresholds to justify without more evidence that a blend outperforms
    the simple rule."""
    return bool(persistent_bias or coverage_breach or demand_shift)


# ── Manual overrides + Forecast Value Added of human judgement ──────────

def record_override(overrides: list[dict], article_id: str, period, model_forecast: float,
                    override_value: float, user: str, reason: str,
                    timestamp: str | None = None) -> list[dict]:
    """Appends one override entry -- a plain list of dicts, not a
    database table (see module docstring: forecasting/ stays CSV/
    DataFrame-first, a live-DB-backed override log is a separate adapter
    for the Streamlit integration). Returns a NEW list (the caller's own
    list is never mutated in place), matching this module's pure-function
    style throughout."""
    entry = {
        "article_id": article_id, "period": period, "model_forecast": model_forecast,
        "override_value": override_value, "user": user, "reason": reason,
        "timestamp": timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return overrides + [entry]


def compute_override_fva(overrides: list[dict] | pd.DataFrame, actuals: pd.Series) -> pd.DataFrame:
    """FVA of each override once its outcome is known: positive means the
    human override ended up closer to what actually happened than the
    model's own forecast, negative means the override made things worse.
    `actuals` is indexed by (article_id, period) -- the same key an
    override was recorded against. Overrides whose actual isn't known yet
    (period hasn't happened) are dropped, not given a fabricated score.
    """
    df = pd.DataFrame(overrides) if not isinstance(overrides, pd.DataFrame) else overrides.copy()
    if df.empty:
        return pd.DataFrame(columns=["article_id", "period", "model_forecast", "override_value",
                                     "actual", "model_error", "override_error", "fva"])

    df["actual"] = df.apply(
        lambda r: actuals.get((r["article_id"], r["period"])), axis=1)
    df = df.dropna(subset=["actual"])
    if df.empty:
        return pd.DataFrame(columns=["article_id", "period", "model_forecast", "override_value",
                                     "actual", "model_error", "override_error", "fva"])

    df["model_error"] = (df["actual"] - df["model_forecast"]).abs()
    df["override_error"] = (df["actual"] - df["override_value"]).abs()
    df["fva"] = df["model_error"] - df["override_error"]
    return df[["article_id", "period", "model_forecast", "override_value", "actual",
              "model_error", "override_error", "fva"]]


# ── Alerts ────────────────────────────────────────────────────────────────

def generate_alerts(article_id: str, description: str | None, persistent_bias_row: dict | None,
                    coverage_breach_row: dict | None, demand_shift_flagged: bool,
                    obs_risk: str) -> list[dict]:
    """One alert dict per triggered condition for this article -- an
    article can have zero, one, or several alerts at once (a persistent
    bias and an obsolescence risk are independent signals, both can fire
    together). Each alert carries a short Swedish explanation, same
    plain-language spirit as forecasting/explain.py, kept separate from
    that module since this explains ALERTS, not a POLICY."""
    label = description or article_id
    alerts = []

    if persistent_bias_row is not None:
        direction_sv = "överskattat" if persistent_bias_row["direction"] == "over" else "underskattat"
        alerts.append({
            "article_id": article_id, "type": "persistent_bias", "severity": "warning",
            "message": f"{label}: prognosen har {direction_sv} efterfrågan i "
                       f"{persistent_bias_row['streak_length']} perioder i rad "
                       f"(modell: {persistent_bias_row['model']}).",
        })

    if coverage_breach_row is not None:
        direction_sv = "för smala" if coverage_breach_row["breach_direction"] == "under" else "onödigt breda"
        alerts.append({
            "article_id": article_id, "type": "coverage_breach", "severity": "warning",
            "message": f"{label}: prognosintervallen har varit {direction_sv} "
                       f"(faktisk täckning {coverage_breach_row['empirical_coverage']:.0%}).",
        })

    if demand_shift_flagged:
        alerts.append({
            "article_id": article_id, "type": "demand_shift", "severity": "info",
            "message": f"{label}: en varaktig nivåförändring i efterfrågan har upptäckts -- "
                       f"värt en snabb manuell koll.",
        })

    if obs_risk in ("emerging", "confirmed"):
        risk_sv = "Ny risk" if obs_risk == "emerging" else "Bekräftad risk"
        alerts.append({
            "article_id": article_id, "type": "obsolescence_risk", "severity": "critical",
            "message": f"{label}: {risk_sv} för föråldrad artikel -- prognosen pekar mot "
                       f"nästan ingen efterfrågan framöver.",
        })
    elif obs_risk == "recovering":
        alerts.append({
            "article_id": article_id, "type": "obsolescence_recovering", "severity": "info",
            "message": f"{label}: tidigare flaggad som föråldrad, men prognosen visar tecken "
                       f"på återhämtning.",
        })

    return alerts
