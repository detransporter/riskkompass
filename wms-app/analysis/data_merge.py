# Trimmed vendor copy of iha-saas/analysis/data_merge.py. Only
# sales_statistics() and aggregate_inbound() (plus the helpers they call)
# are kept -- everything else in the source file (guess_mapping,
# detect_role, SYNONYMS, build_canonical/merge_mapped) exists there to solve
# messy-Excel-column-name problems that wms-app's own analysis_bridge.py
# does not have, since it reads a SQLite schema with known column names
# directly. See wms-app/CLAUDE.md "IHA integration".
#
# The functions kept below are otherwise byte-for-byte identical to the
# source -- do not "clean them up" independently of the original, since a
# future re-vendor (e.g. after a bugfix upstream) diffs against this file.

import re

import numpy as np
import pandas as pd

MIN_PERIODS_FOR_SIGMA = 3   # below this, a standard deviation is noise
TREND_WINDOW = 3            # periods compared against the preceding 3

# Columns sales_statistics always returns, so callers can rely on the shape.
_SALES_STAT_COLS = ["sku", "avg_daily_demand", "std_daily", "demand_cv",
                    "demand_months", "months_with_demand", "last_movement_date",
                    "demand_monthly", "demand_monthly_full",
                    "demand_recent_avg", "demand_prior_avg"]

_ISO_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def parse_dates(series: pd.Series) -> pd.Series:
    """Date parsing that detects year-first (ISO) dates instead of guessing.

    pd.to_datetime(..., dayfirst=True) is meant for Swedish DD/MM/YYYY files,
    but customers also export YYYY-MM-DD. When both the month and day
    components are <= 12 that is ambiguous, and dayfirst=True resolves it
    silently wrong. A 4-digit year at the front is unambiguous regardless of
    dayfirst, so detecting that from the data and parsing year-first dates as
    such (while still trusting dayfirst=True for everything else) removes
    the guess.
    """
    s = series.astype(str).str.strip()
    sample = s[s.notna() & (s != "nan") & (s != "")]
    looks_iso = sample.str.match(_ISO_DATE_RE).mean() > 0.5 if len(sample) else False
    return pd.to_datetime(series, errors="coerce", dayfirst=not looks_iso)


def _norm(s) -> str:
    return re.sub(r"[\s_\-./]", "", str(s).lower())


def _to_sku(series) -> pd.Series:
    return series.astype(str).str.strip()


def _period_days(columns) -> float:
    """Infer how many days each wide-format period column represents."""
    sample = " ".join(_norm(c) for c in columns)
    if re.search(r"(vecka|week|^v\d|w\d)", sample):
        return 7.0
    if re.search(r"\d{4}\d{2}$|\d{4}[-/]\d{1,2}$", sample) or \
       re.search(r"(jan|feb|mar|apr|maj|jun|jul|aug|sep|okt|nov|dec|month|månad|manad)", sample):
        return 30.44
    return 1.0  # assume daily


_DATE_HDR = re.compile(
    r"^\s*(\d{4}[-/]\d{1,2}([-/]\d{1,2})?|"          # 2024-01 / 2024-01-15
    r"(v|w|vecka|week)\s*\d{1,2}|"                    # v12 / week 12
    r"(jan|feb|mar|apr|maj|may|jun|jul|aug|sep|okt|oct|nov|dec)\w*|"
    r"\d{1,2}[-/]\d{4})\s*$", re.I)                   # 01-2024


def _looks_like_period_cols(columns) -> list:
    return [c for c in columns if _DATE_HDR.match(str(c))]


def _stats_from_matrix(mat: pd.DataFrame, period_days: float) -> pd.DataFrame:
    """Per-SKU statistics from a SKU × period quantity matrix.

    mat may hold NaN for periods before a SKU's own first transaction (it
    didn't exist yet — not a zero-demand period); pandas mean/std already
    skip NaN, but the period *counts* below must too, so a SKU launched
    late in the file's date range is judged against its own real history,
    not the calendar span of every other SKU in the file.

    Variance scales with time under independent periods, so the period standard
    deviation converts to a daily one by dividing by sqrt(period length). That
    is what the safety-stock formula (Z x sigma_d x sqrt(LT)) expects.
    """
    n_periods = mat.notna().sum(axis=1)
    mean_p = mat.mean(axis=1)

    enough_for_sigma = n_periods >= MIN_PERIODS_FOR_SIGMA
    std_p = mat.std(axis=1, ddof=1)
    std_daily = (std_p / np.sqrt(max(period_days, 1.0))).where(enough_for_sigma)
    demand_cv = (std_p / mean_p.where(mean_p > 0)).replace([np.inf, -np.inf], np.nan).where(enough_for_sigma)

    # Recent vs preceding window — the raw material for trend classification.
    # Computed here, while the full matrix (including zero months) still exists;
    # demand_monthly drops zero months to stay compact, so a later reader could
    # not tell "no sales in June" from "June not in the file".
    enough_for_trend = n_periods >= 2 * TREND_WINDOW
    recent = mat.iloc[:, -TREND_WINDOW:].mean(axis=1).where(enough_for_trend)
    prior = mat.iloc[:, -2 * TREND_WINDOW:-TREND_WINDOW].mean(axis=1).where(enough_for_trend)

    return pd.DataFrame({
        "std_daily": std_daily,
        "demand_cv": demand_cv,
        "demand_months": n_periods,
        "months_with_demand": (mat > 0).sum(axis=1),
        "demand_recent_avg": recent,
        "demand_prior_avg": prior,
        "demand_monthly": [
            {str(c): round(float(v), 3) for c, v in row.items() if pd.notna(v) and v}
            for _, row in mat.iterrows()
        ],
        # Zero periods kept (unlike demand_monthly, which compacts them away
        # to stay small) — but NaN (pre-launch, not yet observed) is dropped
        # from both, so this preserves exactly the distinction: "no demand
        # this period" vs "period not in the file".
        "demand_monthly_full": [
            {str(c): round(float(v), 3) for c, v in row.items() if pd.notna(v)}
            for _, row in mat.iterrows()
        ],
    }, index=mat.index)


def sales_statistics(df, sku_col, qty_col=None, date_col=None,
                     assumed_period_days=365.0) -> tuple[pd.DataFrame, str]:
    """
    Per-SKU demand statistics from a sales/consumption file.

    avg_daily_demand keeps its original definition (total quantity / observed
    window) so existing analyses stay comparable. Everything else exists so
    the analysis is no longer blind to *how* demand behaved:

        std_daily          real daily sigma (not the flat 0.30 x mean guess)
        demand_cv          sigma / mean — the X/Y/Z axis
        last_movement_date the date the SKU last moved
        demand_months      periods observed
        months_with_demand periods with any movement (intermittency)
        demand_monthly     {"2026-01": qty, …} — the series itself, kept

    Statistical columns are NaN/None when the file cannot support them (no
    dates, or fewer than 3 complete months). The caller must then fall back to
    the flat estimate and say so — never present a guess as a measurement.

    Returns (DataFrame, note).
    """
    df = df.copy()
    df[sku_col] = _to_sku(df[sku_col])

    period_cols = _looks_like_period_cols(df.columns)

    # ── Shape 1: wide (one column per period) ────────────────────────────────
    if not qty_col and len(period_cols) >= 2:
        for c in period_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        mat = df.groupby(sku_col)[period_cols].sum().fillna(0)
        pdays = _period_days(period_cols)
        window = max(len(period_cols) * pdays, 1.0)

        out = _stats_from_matrix(mat, pdays)
        out["avg_daily_demand"] = mat.sum(axis=1) / window

        # Last period with movement, as a date when the header parses as one.
        last_col = mat.apply(lambda r: next((c for c in reversed(mat.columns) if r[c] > 0), None), axis=1)
        out["last_movement_date"] = pd.to_datetime(last_col.astype(str), errors="coerce")

        out = out.reset_index().rename(columns={sku_col: "sku"})
        return out.reindex(columns=_SALES_STAT_COLS), (
            f"Wide format: {len(period_cols)} periods ≈ {window:.0f} days window."
        )

    if not qty_col:
        return pd.DataFrame(columns=_SALES_STAT_COLS), \
               "No quantity column found in sales file — demand not derived."

    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    totals = df.groupby(sku_col)[qty_col].sum()

    dates = None
    if date_col and date_col in df.columns:
        df["_date"] = parse_dates(df[date_col])
        dates = df["_date"].dropna()

    # ── Shape 2: long without usable dates — average only ────────────────────
    if dates is None or len(dates) < 2:
        out = (totals / max(assumed_period_days, 1.0)).rename("avg_daily_demand").reset_index()
        out = out.rename(columns={sku_col: "sku"})
        return out.reindex(columns=_SALES_STAT_COLS), (
            f"No dates — assumed a {assumed_period_days/365:.1f}-year window. "
            "Demand variability could not be measured; safety stock will use a flat estimate."
        )

    # ── Shape 3: long with dates — the full picture ──────────────────────────
    dmin, dmax = dates.min(), dates.max()
    span = max((dmax - dmin).days + 1, 1)

    dated = df.dropna(subset=["_date"]).copy()
    dated["_month"] = dated["_date"].dt.to_period("M")

    mat = (dated.pivot_table(index=sku_col, columns="_month", values=qty_col,
                             aggfunc="sum", fill_value=0)
                .reindex(columns=pd.period_range(dmin, dmax, freq="M"), fill_value=0)
                .fillna(0))

    # A SKU's own history starts at its first transaction, not the file's
    # earliest date. Reindexing every SKU to the same [dmin, dmax] range
    # zero-fills the months before it existed — not "no demand", but "wasn't
    # sold yet" — which otherwise inflates its period count (and so ADI,
    # demand_cv, and every threshold that reads it) for any SKU launched
    # after the file's oldest SKU. Mask those cells back to NaN, which
    # mean/std already skip.
    first_period = dated.groupby(sku_col)["_month"].min().reindex(mat.index)
    before_launch = pd.DataFrame(
        {col: (col < first_period) for col in mat.columns}, index=mat.index
    )
    mat = mat.mask(before_launch)

    # Partial months at either end understate demand and inflate sigma, so the
    # statistics use only months the observation window fully covers.
    full_months = [p for p in mat.columns
                   if p.start_time >= dmin.normalize() and p.end_time <= dmax.normalize() + pd.Timedelta(days=1)]
    stat_mat = mat[full_months] if len(full_months) >= MIN_PERIODS_FOR_SIGMA else mat

    out = _stats_from_matrix(stat_mat, 30.44)
    out["avg_daily_demand"] = (totals / span).reindex(out.index).fillna(0)

    moved = dated[dated[qty_col] > 0]
    out["last_movement_date"] = moved.groupby(sku_col)["_date"].max().reindex(out.index)

    out = out.reset_index().rename(columns={sku_col: "sku"})

    note = (f"Observed window: {span} days ({dmin.date()} → {dmax.date()}), "
            f"{len(full_months)} complete months.")
    if len(full_months) < MIN_PERIODS_FOR_SIGMA:
        note += (f" Fewer than {MIN_PERIODS_FOR_SIGMA} complete months — demand variability "
                 "is unreliable and safety stock will use a flat estimate.")
    return out.reindex(columns=_SALES_STAT_COLS), note


MAX_PLAUSIBLE_LT = 730   # a "lead time" beyond two years is a data error


def aggregate_inbound(df, sku_col, qty_col=None, date_col=None,
                      order_date_col=None, promised_col=None) -> pd.DataFrame:
    """Per-SKU receipt history, including measured lead time where possible.

    Three levels of insight, depending on what the receipt file carries:

      qty only              → total received
      + receipt date        → cadence: interval between receipts and its spread
      + order date          → the real thing: actual lead time per receipt line,
                              its mean and standard deviation.
      + promised date       → on-time delivery rate
    """
    if not qty_col:
        return pd.DataFrame(columns=["sku", "inbound_qty"])

    df = df.copy()
    df[sku_col] = _to_sku(df[sku_col])
    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

    out = df.groupby(sku_col)[qty_col].sum().rename("inbound_qty").to_frame()
    out["inbound_receipts"] = df[df[qty_col] > 0].groupby(sku_col)[qty_col].count()
    out["inbound_receipts"] = out["inbound_receipts"].fillna(0).astype(int)

    if not (date_col and date_col in df.columns):
        return out.reset_index().rename(columns={sku_col: "sku"})

    d = df.copy()
    d["_date"] = parse_dates(d[date_col])
    d = d.dropna(subset=["_date"])
    d = d[d[qty_col] > 0]
    if d.empty:
        return out.reset_index().rename(columns={sku_col: "sku"})

    out["last_inbound_date"] = d.groupby(sku_col)["_date"].max()

    # Cadence — the spread of the interval between consecutive receipts.
    d = d.sort_values([sku_col, "_date"])
    gaps = d.groupby(sku_col)["_date"].diff().dt.days
    gaps_by_sku = gaps.groupby(d[sku_col])
    out["inbound_interval_mean"] = gaps_by_sku.mean()
    out["inbound_interval_std"] = gaps_by_sku.std(ddof=1)

    # ── Actual lead time: order date → receipt date, per receipt line ────────
    if order_date_col and order_date_col in d.columns:
        d["_ordered"] = parse_dates(d[order_date_col])
        lt = (d["_date"] - d["_ordered"]).dt.days
        # Negative or absurd values mean the columns were mismapped or the ERP
        # back-dated a receipt. Drop them rather than let them poison the mean.
        valid = lt.between(0, MAX_PLAUSIBLE_LT)
        if valid.any():
            lt_by_sku = lt[valid].groupby(d[sku_col][valid])
            out["lt_actual_mean"] = lt_by_sku.mean()
            out["lt_actual_std"] = lt_by_sku.std(ddof=1)
            out["lt_actual_max"] = lt_by_sku.max()
            out["lt_samples"] = lt_by_sku.count()

    # ── On-time delivery ─────────────────────────────────────────────────────
    if promised_col and promised_col in d.columns:
        promised = parse_dates(d[promised_col])
        has_promise = promised.notna()
        if has_promise.any():
            on_time = (d["_date"][has_promise] <= promised[has_promise]).astype(float)
            grp = on_time.groupby(d[sku_col][has_promise])
            out["on_time_rate"] = grp.mean()
            out["delivery_lines"] = grp.count()
            late_days = (d["_date"][has_promise] - promised[has_promise]).dt.days
            out["avg_days_late"] = late_days[late_days > 0].groupby(
                d[sku_col][has_promise][late_days > 0]).mean()

    return out.reset_index().rename(columns={sku_col: "sku"})
