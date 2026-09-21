"""M3 competition dataset loader (docs/FORECAST_SPEC.md Phase 10):
Makridakis, S., Hibon, M., 2000. "The M3-Competition: results,
conclusions and implications." International Journal of Forecasting
16(4), 451-476.

Self-contained .tsf ("Monash Time Series Forecasting Repository" format)
parser -- deliberately NOT the `datasetsforecast` PyPI package (which
already implements the same M3 loader): installing a new, previously-
unvetted third-party dependency for something this small was flagged as
an unnecessary supply-chain risk, so this instead downloads the same
Zenodo-hosted file directly (curl, a specific real URL, not invented --
see scripts/run_phase10_m3_validation.py for the download step) and
parses the couple dozen lines of format this needs itself.

No `items`/`inbound`/`stock` data exists for M3 at all -- it is a bare
demand-series benchmark, nothing else. That means Phases 5-7 (lead-time
demand, policy, simulation) genuinely CANNOT be validated against this
dataset; only Phases 2-4's forecasting/segmentation machinery can. Stated
here, not glossed over, and restated in the Phase 10 report.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_m3_monthly_tsf(path: Path | str) -> pd.DataFrame:
    """Parses the M3 monthly .tsf file into (article_id, period,
    qty_ordered) -- the same long-format shape
    forecasting/data.py:build_demand_series() produces, so
    forecasting/backtest.py:run_backtest() and
    forecasting/segmentation.py's classify_sbc() (via
    analysis/demand_forecast.py, which only ever needs (sku, period, qty))
    accept it unmodified.

    One real, minor data-quality note handled explicitly, not silently:
    1 of the 1,428 series (a economic/financial series in the M3
    competition's own mix of domains) contains a negative value -- not a
    meaningful "demand quantity" for this project's inventory context, so
    that one series is dropped, not clipped (clipping would fabricate a
    value that was never actually observed).

    The .tsf format: header lines starting with `#`/`@` (metadata, e.g.
    `@frequency monthly`), then one line per series after `@data`:
    `<series_id>:<start_timestamp>:<v1>,<v2>,<v3>,...`. Encoded latin-1,
    not utf-8 -- the source file's own header comment has a non-utf8 en
    dash character (an en-dash lost in the original dataset's own
    encoding history, not something this loader introduces).
    """
    rows = []
    in_data = False
    with open(path, encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if line == "@data":
                in_data = True
                continue
            if not in_data or not line:
                continue
            series_id, start_ts, values_str = line.split(":")
            start_date = pd.Timestamp(start_ts.split(" ")[0])
            values = [float(v) for v in values_str.split(",")]
            if any(v < 0 for v in values):
                continue  # the one non-demand-like series, see docstring
            periods = pd.date_range(start_date, periods=len(values), freq="MS")
            for period, qty in zip(periods, values):
                rows.append({"article_id": series_id, "period": period, "qty_ordered": qty})
    return pd.DataFrame(rows)
