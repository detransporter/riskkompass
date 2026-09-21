"""Data-access layer for the forecasting module (docs/FORECAST_SPEC.md
Phase 1). Loads the canonical outbound/inbound/items/stock data contract
(spec section 2) from CSV files -- the shape datagen/v1/generera_lagerdata.py
produces -- and builds a zero-filled demand series per article at a given
frequency, using a Swedish business-day calendar for holiday-aware framing.

CSV-first, not DB-first, on purpose: a live wms-app tenant has at most a few
weeks of real history right now (the app itself is mid-deployment), nowhere
near enough to develop or validate a forecasting pipeline against. The
datagen/ synthetic estate (and later, real data -- Phase 10) is the actual
development target for Phases 1-9. A loader for wms-app's live SQLite
tenant schema is a natural, separate adapter to add once a tenant has
enough history to be worth forecasting (same adapter-not-rewrite pattern
analysis_bridge.py already uses for the IHA pipeline) -- not built here.

No SQLite-only anything here on purpose (the working agreement requires
this to survive a move to Postgres): everything below is plain pandas
reading CSV/DataFrame input, no database calls at all yet.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "forecast.yaml"

_OUTBOUND_COLS = ["order_date", "order_id", "order_line", "article_id",
                   "customer_id", "qty_ordered", "qty_shipped"]
_INBOUND_COLS = ["po_number", "po_line", "po_date", "supplier_id", "article_id",
                  "qty_ordered", "unit_price_sek", "expected_date", "receipt_date",
                  "qty_received", "status"]
_ITEMS_COLS = ["article_id", "description", "category", "uom", "supplier_id",
                "unit_cost_sek", "moq", "order_multiple", "lead_time_days",
                "reorder_point", "safety_stock", "created_date", "status"]
_STOCK_COLS = ["snapshot_date", "article_id", "stock_qty", "stock_value_sek"]


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _require_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"{name}: missing required columns {sorted(missing)}")


def load_outbound(path: Path | str) -> pd.DataFrame:
    """order_date, order_id, order_line, article_id, customer_id,
    qty_ordered, qty_shipped -- one row per order line. Demand is
    qty_ordered (unconstrained), never qty_shipped -- see cleaning.py for
    the censoring flag qty_shipped < qty_ordered exists to preserve."""
    df = pd.read_csv(path, parse_dates=["order_date"])
    _require_columns(df, _OUTBOUND_COLS, "outbound")
    return df[_OUTBOUND_COLS]


def load_inbound(path: Path | str) -> pd.DataFrame:
    """po_number, po_line, po_date, supplier_id, article_id, qty_ordered,
    unit_price_sek, expected_date, receipt_date, qty_received, status --
    one row per purchase-order line. po_date/expected_date/receipt_date are
    what Phase 5's empirical lead-time distribution is built from (receipt
    minus po_date, and expected vs receipt for on-time rate)."""
    df = pd.read_csv(path, parse_dates=["po_date", "expected_date", "receipt_date"])
    _require_columns(df, _INBOUND_COLS, "inbound")
    return df[_INBOUND_COLS]


def load_items(path: Path | str) -> pd.DataFrame:
    """article_id, description, category, uom, supplier_id, unit_cost_sek,
    moq, order_multiple, lead_time_days, reorder_point, safety_stock,
    created_date, status. created_date anchors build_demand_series()'s
    zero-fill start -- an article did not have "zero demand" before it was
    created, it simply did not exist yet (same distinction
    wms-app/analysis/data_merge.py already preserves for the live-WMS
    pipeline, applied here to the synthetic/demo data contract instead)."""
    df = pd.read_csv(path, parse_dates=["created_date"])
    _require_columns(df, _ITEMS_COLS, "items")
    return df[_ITEMS_COLS]


def load_stock(path: Path | str) -> pd.DataFrame:
    """snapshot_date, article_id, stock_qty, stock_value_sek -- one row per
    article per month-end snapshot."""
    df = pd.read_csv(path, parse_dates=["snapshot_date"])
    _require_columns(df, _STOCK_COLS, "stock")
    return df[_STOCK_COLS]


# ── Swedish business calendar ───────────────────────────────────────────
#
# A minimal, dependency-free implementation (Gauss's Easter algorithm plus
# the fixed and Easter-relative Swedish public holidays) rather than a
# localization library -- keeps requirements-forecast.txt from growing for
# a feature that is a few dozen lines of arithmetic. Covers the holidays
# that matter for demand-calendar effects (a closed business does not
# place or receive orders that day), not employee-scheduling edge cases
# (e.g. this does not distinguish a "red day" from a compressed workday).

def _easter_sunday(year: int) -> pd.Timestamp:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return pd.Timestamp(year, month, day)


def _friday_in_range(year: int, month: int, day_start: int, day_end: int) -> pd.Timestamp:
    """The Friday falling within [day_start, day_end] of `month` --
    Midsummer Eve is always the Friday between June 19-25."""
    for day in range(day_start, day_end + 1):
        d = pd.Timestamp(year, month, day)
        if d.dayofweek == 4:
            return d
    raise AssertionError(f"no Friday found in {year}-{month} [{day_start},{day_end}]")


def _saturday_in_range(year: int, month: int, day_start: int, month2: int, day_end: int) -> pd.Timestamp:
    """All Saints' Day is the Saturday between Oct 31 - Nov 6 (may cross
    the month boundary, hence the two (month, day) endpoints)."""
    d = pd.Timestamp(year, month, day_start)
    end = pd.Timestamp(year, month2, day_end)
    while d <= end:
        if d.dayofweek == 5:
            return d
        d += pd.Timedelta(days=1)
    raise AssertionError(f"no Saturday found in {year}-{month}-{day_start}..{month2}-{day_end}")


def swedish_public_holidays(start_year: int, end_year: int) -> set[pd.Timestamp]:
    """Swedish public holidays (fixed-date + Easter-relative) for every
    year in [start_year, end_year], inclusive."""
    holidays: set[pd.Timestamp] = set()
    for year in range(start_year, end_year + 1):
        holidays |= {
            pd.Timestamp(year, 1, 1),    # Nyarsdagen
            pd.Timestamp(year, 1, 6),    # Trettondedag jul
            pd.Timestamp(year, 5, 1),    # Forsta maj
            pd.Timestamp(year, 6, 6),    # Nationaldagen
            pd.Timestamp(year, 12, 24),  # Julafton (not a statutory red day, but a de facto closure)
            pd.Timestamp(year, 12, 25),  # Juldagen
            pd.Timestamp(year, 12, 26),  # Annandag jul
            pd.Timestamp(year, 12, 31),  # Nyarsafton (de facto closure)
        }
        easter = _easter_sunday(year)
        holidays |= {
            easter - pd.Timedelta(days=2),   # Langfredagen
            easter,                           # Paskdagen
            easter + pd.Timedelta(days=1),   # Annandag pask
            easter + pd.Timedelta(days=39),  # Kristi himmelsfardsdag
            easter + pd.Timedelta(days=49),  # Pingstdagen
        }
        holidays.add(_friday_in_range(year, 6, 19, 25))              # Midsommarafton
        holidays.add(_saturday_in_range(year, 10, 31, 11, 6))        # Alla helgons dag
    return holidays


def is_business_day(dates: pd.Series, start_year: int | None = None,
                    end_year: int | None = None) -> pd.Series:
    """True where `dates` is a Mon-Fri that is not a Swedish public
    holiday. start_year/end_year default to the span of `dates` itself."""
    if dates.empty:
        return pd.Series(dtype=bool)
    start_year = start_year or dates.dt.year.min()
    end_year = end_year or dates.dt.year.max()
    holidays = swedish_public_holidays(start_year, end_year)
    is_weekday = dates.dt.dayofweek < 5
    is_holiday = dates.isin(holidays)
    return is_weekday & ~is_holiday


# ── Demand series ────────────────────────────────────────────────────────

def build_demand_series(outbound: pd.DataFrame, items: pd.DataFrame,
                        freq: str = "W") -> pd.DataFrame:
    """Long-format (article_id, period, qty_ordered, qty_shipped) demand
    series, zero-filled at `freq` resolution.

    Every article's own series starts at its own created_date (from
    `items`), never before -- a period before an article existed is
    absent, not zero (see load_items()'s docstring). Built as a filtered
    cross-join (article x period) rather than a per-article Python loop:
    vectorised, scales to the full 3,000-item/4-year demo set without a
    noticeable pause (see tests/test_data.py for the measured runtime).

    Periods with no outbound rows for an article get qty_ordered=0,
    qty_shipped=0 -- a real "no demand this period" signal, not a gap.
    """
    cols = ["article_id", "period", "qty_ordered", "qty_shipped"]
    if outbound.empty or items.empty:
        return pd.DataFrame(columns=cols)

    ob = outbound.copy()
    ob["period"] = ob["order_date"].dt.to_period(freq).dt.start_time

    agg = (ob.groupby(["article_id", "period"])[["qty_ordered", "qty_shipped"]]
           .sum().reset_index())

    all_periods = pd.period_range(agg["period"].min(), agg["period"].max(), freq=freq).start_time
    periods_df = pd.DataFrame({"period": all_periods})

    scaffold = items[["article_id", "created_date"]].merge(periods_df, how="cross")
    created_period_start = scaffold["created_date"].dt.to_period(freq).dt.start_time
    scaffold = scaffold[scaffold["period"] >= created_period_start]

    out = scaffold.merge(agg, on=["article_id", "period"], how="left")
    out[["qty_ordered", "qty_shipped"]] = out[["qty_ordered", "qty_shipped"]].fillna(0.0)
    return (out[cols]
            .sort_values(["article_id", "period"])
            .reset_index(drop=True))
