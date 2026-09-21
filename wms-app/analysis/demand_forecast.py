"""
analysis/demand_forecast.py
Phase 5 (forecasting) — SBC (Syntetos-Boylan-Croston) demand-pattern
classification.

This answers a different question from xyz_class in segmentation.py.
xyz_class measures variability of demand *size* across every period, with
zero periods counting as zero-sized demand — it answers "how hard is this
SKU to plan". SBC classification splits that into two separate measures:

  ADI (average inter-demand interval) — how RARE demand is: periods observed
      divided by periods that actually had demand. High ADI means demand is
      infrequent, which is what makes flat models over-forecast between
      occurrences.

  CV² — how VARIABLE the size is, but only across the periods where demand
      DID occur (zero periods are excluded here, deliberately — a period
      with no demand isn't a "small order", it's absence, and folding it
      into the size statistic understates true variability when it happens).

The combination decides whether Croston-family methods are needed at all,
and which variant (model selection is phase 5's next step, not this one).
The two classifications are meant to coexist, not replace one another.
"""

import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import CrostonClassic, CrostonSBA, AutoETS, TSB
from statsforecast.utils import ConformalIntervals

from analysis.dos_calculator import DOS_DEAD, DOS_SLOW

# Syntetos & Boylan (2005) thresholds.
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49

# Below these, ADI/CV² are noise rather than a measurement — same bar
# segmentation.py uses for demand_cv (MIN_PERIODS_FOR_SIGMA = 3).
MIN_PERIODS_FOR_ADI = 3
MIN_OCCURRENCES_FOR_CV2 = 2   # a standard deviation needs at least 2 points


def classify_sbc(history: pd.DataFrame) -> pd.DataFrame:
    """SBC demand-pattern classification per SKU.

    history: long-format (sku, period, qty), zero periods included — e.g.
    from sku_demand_history or analysis.data_merge.demand_history_rows().
    A period absent from the frame means "not observed", not "zero" — same
    distinction sku_demand_history exists to preserve, so this function must
    not be fed a compacted series (demand_monthly) that already dropped it.

    Returns one row per SKU present in `history`:
        sku, n_periods, occurrences, adi, cv2, sbc_class

    sbc_class is one of smooth / intermittent / erratic / lumpy, or:
        no_demand  — occurrences == 0 (in scope, but never sold)
        None       — not enough data to trust ADI/CV² (never a guessed class)
    """
    cols = ["sku", "n_periods", "occurrences", "adi", "cv2", "sbc_class"]
    if history.empty:
        return pd.DataFrame(columns=cols)

    h = history.copy()
    h["qty"] = pd.to_numeric(h["qty"], errors="coerce").fillna(0)

    n_periods = h.groupby("sku")["period"].nunique().rename("n_periods")

    occurred = h[h["qty"] > 0]
    occurrences = occurred.groupby("sku")["qty"].count().rename("occurrences")
    mean_size = occurred.groupby("sku")["qty"].mean().rename("mean_size")
    std_size = occurred.groupby("sku")["qty"].std(ddof=1).rename("std_size")

    out = n_periods.to_frame().join(occurrences, how="left")
    out["occurrences"] = out["occurrences"].fillna(0).astype(int)
    out = out.join(mean_size, how="left").join(std_size, how="left").reset_index()

    out["adi"] = out["n_periods"] / out["occurrences"].where(out["occurrences"] > 0)
    out["cv2"] = (out["std_size"] / out["mean_size"].where(out["mean_size"] > 0)) ** 2

    measurable = (
        (out["n_periods"] >= MIN_PERIODS_FOR_ADI)
        & (out["occurrences"] >= MIN_OCCURRENCES_FOR_CV2)
        & out["adi"].notna()
        & out["cv2"].notna()
    )
    adi_high = out["adi"] > ADI_THRESHOLD
    cv2_high = out["cv2"] > CV2_THRESHOLD

    sbc = pd.Series(pd.NA, index=out.index, dtype="object")
    sbc[measurable & ~adi_high & ~cv2_high] = "smooth"
    sbc[measurable & adi_high & ~cv2_high]  = "intermittent"
    sbc[measurable & ~adi_high & cv2_high]  = "erratic"
    sbc[measurable & adi_high & cv2_high]   = "lumpy"
    # Never sold in the observed window at all — absence of demand, not a
    # demand *pattern*, so it gets its own label rather than sliding into
    # "not measurable" (which would wrongly suggest more data might help).
    sbc[out["occurrences"] == 0] = "no_demand"

    out["sbc_class"] = sbc.where(sbc.notna(), None)
    return out[cols]


# ── Forecasting ───────────────────────────────────────────────────────────
#
# Two model families, because they need different amounts of history for
# different reasons — verified empirically, not assumed:
#
#   Croston family (CrostonClassic, CrostonSBA) — statsforecast has no native
#   interval for these; ConformalIntervals holds out n_windows*h points to
#   calibrate one, and refuses below that (a ValueError, not a soft degrade).
#   With h=3, n_windows=2 that floor is 7 periods. Below it, the point
#   forecast itself still runs fine — only the interval is skipped.
#
#   AutoETS — has a native interval via level=, no extra windows needed. But
#   it raises outright (NotImplementedError, or an uglier IndexError on very
#   short input) below 7 periods too — for ETS that floor blocks the *point*
#   forecast, not just the interval, so there is no degraded mode to fall
#   into. The model selector below is what falls back to SBA in that case.
#
# In both families, a SKU that never sold in the observed window doesn't get
# a model run at all — there's nothing to fit — it gets a flat zero forecast.
# A SKU with fewer than MIN_PERIODS_FOR_FORECAST observed periods is dropped
# entirely: there isn't even a demand interval to measure.

FORECAST_N_WINDOWS = 2
MIN_PERIODS_FOR_FORECAST = 2          # need at least one interval to measure
MIN_PERIODS_FOR_INTERVAL = FORECAST_N_WINDOWS * 3 + 1   # =7, against the default horizon of 3
MIN_PERIODS_FOR_ETS = 7               # verified empirically; below this AutoETS itself raises

# Holt-Winters seasonality needs ~2 full cycles to tell a real seasonal
# pattern from noise — fit it on less and AutoETS is finding 12 seasonal
# indices from less than two observations per month-of-year, dressing up
# noise as a pattern. Below this, force season_length=1 (non-seasonal)
# instead; AutoETS's own AIC-based model selection still decides trend vs.
# flat within either search space.
MIN_PERIODS_FOR_SEASONAL_ETS = 24
ETS_SEASON_LENGTH = 12                # monthly data — see the history gate above

_FORECAST_COLS = ["sku", "period", "horizon", "forecast", "lo", "hi", "method"]


def _prep_history(history: pd.DataFrame) -> pd.DataFrame:
    h = history.copy()
    h["qty"] = pd.to_numeric(h["qty"], errors="coerce").fillna(0)
    h["ds"] = pd.to_datetime(h["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    return h.dropna(subset=["ds"]).sort_values(["sku", "ds"])


def _split_by_data_sufficiency(h: pd.DataFrame, skus=None,
                               min_periods_for_interval: int = MIN_PERIODS_FOR_INTERVAL):
    """(no_demand, too_short, with_interval, point_only) SKU lists, from
    counts alone — shared by every Croston-family method, since the data
    requirement is about periods and occurrences, not which variant runs.

    min_periods_for_interval must scale with the actual horizon being
    requested (ConformalIntervals needs n_windows*h+1 periods to calibrate —
    the module constant is only correct for the default horizon=3). Callers
    forecasting at a different horizon must pass the matching value or
    ConformalIntervals raises instead of degrading.
    """
    if skus is not None:
        h = h[h["sku"].isin(skus)]
    n_periods = h.groupby("sku")["ds"].nunique()
    occurrences = h[h["qty"] > 0].groupby("sku").size()

    no_demand = [s for s in n_periods.index if occurrences.get(s, 0) == 0]
    too_short = [s for s in n_periods.index
                if s not in no_demand and n_periods[s] < MIN_PERIODS_FOR_FORECAST]
    with_interval = [s for s in n_periods.index
                     if s not in no_demand and s not in too_short
                     and n_periods[s] >= min_periods_for_interval]
    point_only = [s for s in n_periods.index
                 if s not in no_demand and s not in too_short and s not in with_interval]
    return no_demand, too_short, with_interval, point_only


def _no_demand_rows(h: pd.DataFrame, skus: list, horizon: int) -> list:
    rows = []
    for sku in skus:
        last_ds = h.loc[h["sku"] == sku, "ds"].max()
        for step in range(1, horizon + 1):
            fut = last_ds + pd.DateOffset(months=step)
            rows.append({"sku": sku, "ds": fut, "forecast": 0.0, "lo": 0.0, "hi": 0.0,
                        "method": "no_demand"})
    return rows


def _finish(rows: list) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=_FORECAST_COLS)
    out = out.sort_values(["sku", "ds"])
    out["horizon"] = out.groupby("sku").cumcount() + 1
    out["period"] = out["ds"].dt.date.astype(str)
    return out[_FORECAST_COLS].reset_index(drop=True)


def _forecast_intermittent(history: pd.DataFrame, model_factory, output_col: str,
                           method_name: str, horizon: int = 3, level: int = 80,
                           skus: list = None) -> pd.DataFrame:
    """Shared engine for every Croston-family model (CrostonClassic,
    CrostonSBA, TSB — anything with the same "no native interval, needs
    ConformalIntervals" shape; `only_conformal_intervals` in statsforecast's
    own terms). `skus` restricts to a subset (used by the model selector's
    ETS-insufficient-history fallback); None means all SKUs in `history`.

    model_factory: callable taking a ConformalIntervals (or None) and
    returning a configured model instance — a factory rather than a bare
    class because TSB needs alpha_d/alpha_p bound in first, which a plain
    class reference can't carry.
    output_col: the column statsforecast names its forecast after (the
    model's `alias`, which for every method used here matches its class name
    — kept as an explicit param rather than read off the instance, since
    that needs an extra throwaway instantiation for no benefit).

    method in the output is f"{method_name}" (interval) or
    f"{method_name}_no_interval" (point only), so callers can always see
    which variant actually ran, not just which family.
    """
    if history.empty:
        return pd.DataFrame(columns=_FORECAST_COLS)

    h = _prep_history(history)
    min_periods_for_interval = FORECAST_N_WINDOWS * horizon + 1
    no_demand, too_short, with_interval, point_only = _split_by_data_sufficiency(
        h, skus, min_periods_for_interval)

    rows = _no_demand_rows(h, no_demand, horizon)

    def _add(sku_list, with_intervals, method):
        if not sku_list:
            return
        mdf = h[h["sku"].isin(sku_list)][["sku", "ds", "qty"]].rename(
            columns={"sku": "unique_id", "qty": "y"})
        if with_intervals:
            intervals = ConformalIntervals(h=horizon, n_windows=FORECAST_N_WINDOWS)
            sf = StatsForecast(models=[model_factory(intervals)], freq="MS", n_jobs=1)
            fc = sf.forecast(df=mdf, h=horizon, level=[level])
        else:
            sf = StatsForecast(models=[model_factory(None)], freq="MS", n_jobs=1)
            fc = sf.forecast(df=mdf, h=horizon)

        lo_col, hi_col = f"{output_col}-lo-{level}", f"{output_col}-hi-{level}"
        for _, r in fc.iterrows():
            rows.append({
                "sku": r["unique_id"],
                "ds": r["ds"],
                "forecast": max(float(r[output_col]), 0.0),
                "lo": max(float(r[lo_col]), 0.0) if with_intervals else None,
                "hi": max(float(r[hi_col]), 0.0) if with_intervals else None,
                "method": method,
            })

    _add(with_interval, True, method_name)
    _add(point_only, False, f"{method_name}_no_interval")

    return _finish(rows)


def forecast_croston(history: pd.DataFrame, horizon: int = 3, level: int = 80) -> pd.DataFrame:
    """Croston (classic) point forecast + prediction interval, per SKU.

    history: long-format (sku, period, qty), one row per SKU per OBSERVED
    period — same shape classify_sbc takes. Periods must already form a
    complete, gap-free monthly sequence per SKU (sku_demand_history's upsert
    keeps it that way as long as every import covers the months in between —
    a customer who stops uploading for a stretch leaves a real gap this
    function does not currently detect or fill; flagged as a known
    limitation, not solved here).

    Returns: sku, period (ISO date), horizon (1..horizon), forecast, lo, hi,
    method — croston_classic / croston_classic_no_interval / no_demand.
    lo/hi are None where there wasn't enough history for a calibrated
    interval — never fabricated. See module header for the exact data
    requirements each tier needs.
    """
    return _forecast_intermittent(history, lambda pi: CrostonClassic(prediction_intervals=pi),
                                  "CrostonClassic", "croston_classic", horizon, level)


def forecast_sba(history: pd.DataFrame, horizon: int = 3, level: int = 80) -> pd.DataFrame:
    """Croston-SBA (Syntetos-Boylan Approximation) — same shape as
    forecast_croston, but corrects classic Croston's known ~5% systematic
    over-forecast bias. Same data requirements, same output shape, method is
    croston_sba / croston_sba_no_interval / no_demand.
    """
    return _forecast_intermittent(history, lambda pi: CrostonSBA(prediction_intervals=pi),
                                  "CrostonSBA", "croston_sba", horizon, level)


# Fixed smoothing constants, not auto-optimized (unlike CrostonOptimized,
# statsforecast's TSB has no auto-tuned variant). 0.1 is the standard
# starting point in the intermittent-demand literature (Teunter, Syntetos &
# Babai's own paper and most reference implementations use this as a
# reasonable default rather than fitting it per series). Revisit with a real
# grid search once there's enough accumulated history to backtest against.
TSB_ALPHA_D = 0.1
TSB_ALPHA_P = 0.1


def forecast_tsb(history: pd.DataFrame, horizon: int = 3, level: int = 80) -> pd.DataFrame:
    """TSB (Teunter-Syntetos-Babai) — same shape as forecast_croston/_sba,
    but structurally different: Croston and SBA only update on periods with
    actual demand, so their forecast for a SKU that stops selling stays flat
    forever — nothing in the method itself can make it decay. TSB instead
    smooths the demand *probability* every period (occurrence or not), so a
    SKU whose sales are fading toward obsolescence gets a forecast that fades
    with it. That is the whole point of the method (Teunter, Syntetos &
    Babai 2011 frame it explicitly as "linking forecasting to inventory
    obsolescence") — directly relevant to IHA's dead-stock story.

    Same data requirements, same output shape, method is
    tsb / tsb_no_interval / no_demand.
    """
    return _forecast_intermittent(
        history,
        lambda pi: TSB(alpha_d=TSB_ALPHA_D, alpha_p=TSB_ALPHA_P, prediction_intervals=pi),
        "TSB", "tsb", horizon, level)


def forecast_ets(history: pd.DataFrame, horizon: int = 3, level: int = 80) -> pd.DataFrame:
    """AutoETS (trend + level, seasonal once there's enough history — see
    MIN_PERIODS_FOR_SEASONAL_ETS) point forecast + native prediction
    interval, per SKU.

    Unlike the Croston family, AutoETS has no degraded "point forecast only"
    mode: below MIN_PERIODS_FOR_ETS it does not run at all (verified
    empirically — it raises, it does not return a worse answer). Those SKUs
    are simply absent from the output; the model selector below is what
    decides what a "smooth" SKU without enough history for ETS should fall
    back to.

    Two separate AutoETS runs, not one call with a per-row season_length —
    statsforecast takes one season_length per model instance for the whole
    batch, so a SKU with 24+ months and one with 8 can't share a call.
    method reports which search space actually ran: ets_seasonal / ets.

    Returns: sku, period, horizon, forecast, lo, hi, method.
    """
    if history.empty:
        return pd.DataFrame(columns=_FORECAST_COLS)

    h = _prep_history(history)
    n_periods = h.groupby("sku")["ds"].nunique()
    eligible = [s for s in n_periods.index if n_periods[s] >= MIN_PERIODS_FOR_ETS]
    if not eligible:
        return pd.DataFrame(columns=_FORECAST_COLS)

    seasonal = [s for s in eligible if n_periods[s] >= MIN_PERIODS_FOR_SEASONAL_ETS]
    non_seasonal = [s for s in eligible if s not in seasonal]

    rows = []

    def _run(sku_list, season_length, method_name):
        if not sku_list:
            return
        mdf = h[h["sku"].isin(sku_list)][["sku", "ds", "qty"]].rename(
            columns={"sku": "unique_id", "qty": "y"})
        sf = StatsForecast(models=[AutoETS(season_length=season_length)], freq="MS", n_jobs=1)
        fc = sf.forecast(df=mdf, h=horizon, level=[level])
        lo_col, hi_col = f"AutoETS-lo-{level}", f"AutoETS-hi-{level}"
        for _, r in fc.iterrows():
            rows.append({
                "sku": r["unique_id"], "ds": r["ds"],
                "forecast": max(float(r["AutoETS"]), 0.0),
                "lo": max(float(r[lo_col]), 0.0),
                "hi": max(float(r[hi_col]), 0.0),
                "method": method_name,
            })

    _run(seasonal, ETS_SEASON_LENGTH, "ets_seasonal")
    _run(non_seasonal, 1, "ets")

    return _finish(rows)


# ── Model selector ────────────────────────────────────────────────────────
# smooth SKUs get ETS (captures trend, which every Croston-family method
# ignores entirely — they only ever track average interval and average
# size). intermittent stays on SBA: interval and size are both being
# measured as genuinely stable there, which is exactly what SBA is for, and
# it strictly dominates classic Croston (same mechanism, corrected bias) —
# no reason to ever pick plain Croston once SBA exists. erratic and lumpy
# route to TSB instead: those are the two SBC cells with either high size
# variability or high ADI (often both, for lumpy), which is where "is this
# SKU actually dying, or just naturally erratic" is the real question — and
# TSB is the one method here built specifically to answer it, since it's the
# only one whose forecast can decay toward zero on its own.
#
# This split is a reasoned default, not a backtested one — the brief's own
# framing left erratic/lumpy as "TSB or SBA, whichever tests better", and no
# real accuracy backtest exists yet (would need held-out actuals and an error
# metric, a separate piece of work). Swapping is a one-line change here.
SBC_METHOD = {
    "smooth":       "ets",
    "intermittent": "croston_sba",
    "erratic":      "tsb",
    "lumpy":        "tsb",
    # Every Croston-family engine detects "occurrences == 0" itself and short-
    # circuits to a flat zero forecast (method="no_demand" in the output,
    # regardless of which family function got called) — so which one a
    # no_demand SKU is routed through here is arbitrary, it never actually
    # reaches the model. Needs an entry anyway: SBC_METHOD.get() with no
    # match would silently drop these SKUs instead of giving them their
    # (correct, trivial) zero forecast.
    "no_demand":    "croston_sba",
}

# name -> (forecast_* function, engine used for the ETS-style "insufficient
# history" fallback). Every non-ETS method here shares the same Croston-
# family engine, so the fallback is always "give SBA those SKUs instead".
_METHOD_FORECASTERS = {
    "croston_sba": lambda history, horizon, level, skus: _forecast_intermittent(
        history, lambda pi: CrostonSBA(prediction_intervals=pi),
        "CrostonSBA", "croston_sba", horizon, level, skus=skus),
    "tsb": lambda history, horizon, level, skus: _forecast_intermittent(
        history, lambda pi: TSB(alpha_d=TSB_ALPHA_D, alpha_p=TSB_ALPHA_P, prediction_intervals=pi),
        "TSB", "tsb", horizon, level, skus=skus),
}


def select_forecast_method(history: pd.DataFrame, sbc: pd.DataFrame,
                           horizon: int = 3, level: int = 80) -> pd.DataFrame:
    """The model selector: routes each SKU to the method its sbc_class calls
    for (SBC_METHOD), and forecasts it.

    history: long-format (sku, period, qty) — same input classify_sbc and
    every forecast_* function take.
    sbc: classify_sbc(history)'s output (or anything with sku + sbc_class
    columns). SKUs with sbc_class None (not measurable) or missing from
    `sbc` entirely are not forecast — there's no pattern to route on.

    A "smooth" SKU without enough history for ETS (< MIN_PERIODS_FOR_ETS)
    falls back to SBA rather than being dropped — a degraded forecast beats
    none, and it still gets a real interval once it has enough history for
    that instead of ETS's native one.

    Returns the same shape as the forecast_* functions, with method showing
    exactly what ran: ets / croston_sba(_no_interval) / tsb(_no_interval) /
    no_demand.
    """
    if history.empty or sbc.empty:
        return pd.DataFrame(columns=_FORECAST_COLS)

    routed = sbc[sbc["sbc_class"].notna()][["sku", "sbc_class"]].copy()
    routed["method"] = routed["sbc_class"].map(SBC_METHOD)

    ets_skus = routed.loc[routed["method"] == "ets", "sku"].tolist()
    fallback_skus = ets_skus[:]   # SKUs routed to ETS that couldn't run it

    parts = []
    if ets_skus:
        ets_result = forecast_ets(history[history["sku"].isin(ets_skus)], horizon, level)
        parts.append(ets_result)
        fallback_skus = list(set(ets_skus) - set(ets_result["sku"]))

    for method_name, forecaster in _METHOD_FORECASTERS.items():
        skus = routed.loc[routed["method"] == method_name, "sku"].tolist()
        # ETS silently excludes SKUs below its minimum — anything routed to
        # "ets" that didn't come back gets SBA instead of just vanishing.
        if method_name == "croston_sba":
            skus = skus + fallback_skus
        if skus:
            parts.append(forecaster(history, horizon, level, skus))

    if not parts:
        return pd.DataFrame(columns=_FORECAST_COLS)
    return pd.concat(parts, ignore_index=True).sort_values(["sku", "horizon"]).reset_index(drop=True)


# ── Phase 6: forecast × current stock → forward-looking dead-stock risk ─────
#
# This is the connection the brief calls the most important one: today's
# status (dos_calculator.classify_status) is entirely backward-looking — it
# is a verdict on what already happened. A SKU whose demand just started
# fading (the exact case forecast_tsb decays on) can sit at status="healthy"
# right up until the trailing DOS window catches up with it, weeks or months
# after the forecast already knew.
#
# The forecast side reuses DOS_DEAD/DOS_SLOW from dos_calculator.py rather
# than inventing a second definition — this project already resolved that
# exact mistake once (see CLAUDE.md: DOS-signal vs recency-signal both had to
# stay because they caught different failures; a THIRD independent threshold
# here would be the same trap again, just quieter).

DAYS_PER_MONTH = 30.44   # same conversion used throughout dos_calculator.py


def forecast_dead_stock_risk(forecasts: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Combine a forecast with today's stock level into a forward-looking
    risk signal, per SKU.

    forecasts: select_forecast_method()'s output (or forecast_croston/_sba/
        _ets/_tsb directly) — sku, period, horizon, forecast, lo, hi, method.
    current: one row per SKU with at least sku, stock_qty, and status (today's
        classify_status() verdict) — status is what lets this tell a NEW risk
        apart from one that is already flagged.

    Returns one row per SKU present in BOTH inputs (a SKU without a current
    stock level can't have a DOS computed, and one without a forecast has
    nothing to project):

        sku, forecast_avg_daily_demand, forecast_dos, forecast_months_cover,
        forecast_status, current_status, risk

    forecast_avg_daily_demand: mean of `forecast` across the forecast horizon,
        converted to a daily rate — the same avg_daily_demand convention used
        everywhere else in this project (total / days), just fed by the
        forecast instead of the trailing history.
    forecast_dos: stock_qty / forecast_avg_daily_demand — the existing DOS
        formula, forward-looking. inf when forecast demand is 0 (nothing
        projected to consume the stock at all).
    forecast_status: forecast_dos run through DOS_DEAD/DOS_SLOW — the SAME
        thresholds dos_calculator.py already uses on trailing DOS.
    forecast_months_cover: forecast_dos in months — the "X months" figure
        the brief's example asks for, directly. None when forecast_dos is inf
        (nothing forecast to consume the stock — not "a very large number of
        months", genuinely unmeasurable).
    risk:
        emerging    — current_status is healthy or stockout_risk, but
                      forecast_status is slow_mover or dead_stock. Nothing in
                      today's trailing numbers shows this yet — the signal
                      this function exists for.
        confirmed   — current_status is already slow_mover/dead_stock AND
                      the forecast agrees.
        recovering  — current_status is slow_mover/dead_stock, but the
                      forecast says demand is picking back up.
        none        — forecast agrees with today's status; no new signal.
    """
    cols = ["sku", "forecast_avg_daily_demand", "forecast_dos", "forecast_months_cover",
            "forecast_status", "current_status", "risk"]
    if forecasts.empty or current.empty:
        return pd.DataFrame(columns=cols)

    avg_fc = forecasts.groupby("sku")["forecast"].mean().rename("forecast_avg_daily_demand")
    avg_fc = avg_fc / DAYS_PER_MONTH

    cur = current[["sku", "stock_qty", "status"]].drop_duplicates("sku").set_index("sku")
    out = avg_fc.to_frame().join(cur, how="inner").reset_index()
    if out.empty:
        return pd.DataFrame(columns=cols)

    out["forecast_dos"] = (out["stock_qty"] / out["forecast_avg_daily_demand"]
                           .where(out["forecast_avg_daily_demand"] > 0))
    out["forecast_dos"] = out["forecast_dos"].fillna(float("inf"))

    fstatus = pd.Series("healthy", index=out.index)
    # Zero forecast demand with stock on hand is the most severe case, not a
    # DOS of infinity slipping through as "healthy" — same special case
    # dos_calculator.classify_status already needs for the trailing view
    # (nothing forecast to consume it at all beats "will take a very long
    # time to consume").
    fstatus[(out["forecast_avg_daily_demand"] == 0) & (out["stock_qty"] > 0)] = "dead_stock"
    fstatus[(out["forecast_dos"] >= DOS_SLOW) & (out["forecast_dos"] != float("inf"))] = "slow_mover"
    fstatus[(out["forecast_dos"] >= DOS_DEAD) & (out["forecast_dos"] != float("inf"))] = "dead_stock"
    out["forecast_status"] = fstatus
    out["current_status"] = out["status"]

    out["forecast_months_cover"] = (out["forecast_dos"] / DAYS_PER_MONTH).round(1)
    out.loc[out["forecast_dos"] == float("inf"), "forecast_months_cover"] = None

    _AT_RISK = {"slow_mover", "dead_stock"}
    cur_bad = out["current_status"].isin(_AT_RISK)
    fc_bad = out["forecast_status"].isin(_AT_RISK)

    risk = pd.Series("none", index=out.index)
    risk[~cur_bad & fc_bad] = "emerging"
    risk[cur_bad & fc_bad] = "confirmed"
    risk[cur_bad & ~fc_bad] = "recovering"
    out["risk"] = risk

    return out[cols]
