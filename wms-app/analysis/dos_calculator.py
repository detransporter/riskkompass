# Vendored from iha-saas/analysis/dos_calculator.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration" for why this is a copy, not a shared
# package, and analysis_bridge.py for how it is fed from SQLite.

import numpy as np
import pandas as pd

DOS_DEAD = 120
DOS_SLOW = 60

_SL_MAP   = {"A": 0.98, "B": 0.95, "C": 0.80}
_Z_SCORES = {0.98: 2.054, 0.95: 1.645, 0.90: 1.282, 0.85: 1.036, 0.80: 0.842}


def calculate_dos(df: pd.DataFrame,
                  stock_col: str = "stock_qty",
                  demand_col: str = "avg_daily_demand") -> pd.DataFrame:
    df = df.copy()
    df["dos"] = np.where(
        df[demand_col] > 0,
        df[stock_col] / df[demand_col],
        np.inf,
    )
    return df


def classify_status(df: pd.DataFrame,
                    lead_time_col: str = "lead_time_days") -> pd.DataFrame:
    df = df.copy()
    lt = df[lead_time_col] if lead_time_col in df.columns else 0
    lt_thresh = (lt * 1.2).where(lt > 0, 30) if hasattr(lt, "where") else 30

    status = pd.Series("healthy", index=df.index)
    status[(df["avg_daily_demand"] == 0) & (df["stock_qty"] > 0)] = "dead_stock"
    status[(df["stock_qty"] == 0) & (df["avg_daily_demand"] > 0)] = "stockout_risk"
    status[(df["dos"] >= DOS_SLOW) & (df["dos"] != np.inf)] = "slow_mover"
    status[(df["dos"] >= DOS_DEAD) & (df["dos"] != np.inf)] = "dead_stock"

    df["status"] = status

    # Stockout risk flag (dos < lead_time × 1.2, with 30-day fallback)
    df["stockout_risk"] = (df["dos"] < lt_thresh) & (df["avg_daily_demand"] > 0)

    # Stockout date
    today = pd.Timestamp.today().normalize()
    df["stockout_date"] = pd.NaT
    has_cons = (df["avg_daily_demand"] > 0) & (df["dos"] != np.inf)
    dos_capped = df.loc[has_cons, "dos"].clip(upper=3650).round(0).astype(int)
    df.loc[has_cons, "stockout_date"] = today + pd.to_timedelta(dos_capped, unit="D")
    df.loc[df["status"] == "stockout_risk", "stockout_date"] = today

    return df


def compute_replenishment(df: pd.DataFrame,
                           std_daily_col: str = "std_daily") -> pd.DataFrame:
    """
    Adds safety_stock, rop, order_qty columns.
    Requires: abc_class, status, avg_daily_demand, lead_time_days, stock_qty,
    and optionally std_daily.
    """
    df = df.copy()

    if "lead_time_days" not in df.columns:
        df["lead_time_days"] = 30

    # Real demand variability comes from the sales file (see data_merge.
    # sales_statistics). Where it is missing we fall back to a flat CV of 0.30,
    # which makes safety stock a fixed multiple of mean demand rather than a
    # statistical figure. Flag it so reports can say so instead of implying a
    # precision the data does not support.
    if std_daily_col not in df.columns:
        df["std_daily"] = df["avg_daily_demand"] * 0.30
        df["std_daily_estimated"] = True
    else:
        real = pd.to_numeric(df[std_daily_col], errors="coerce")
        df["std_daily_estimated"] = real.isna() | (real <= 0)
        df["std_daily"] = real.where(~df["std_daily_estimated"],
                                     df["avg_daily_demand"] * 0.30)

    df["service_level"] = df["abc_class"].map(_SL_MAP).fillna(0.95)

    def _z(sl):
        return _Z_SCORES.get(sl, 1.645)

    df["_z"] = df["service_level"].map(_z)

    # Plan with the measured lead time when lead_time.resolve_lead_time() has
    # run; otherwise with whatever master data says.
    if "lead_time_used" in df.columns:
        lt = pd.to_numeric(df["lead_time_used"], errors="coerce").fillna(0).clip(lower=1)
    else:
        lt = df["lead_time_days"].clip(lower=1)

    # Safety stock must cover two independent sources of uncertainty:
    #
    #     SS = Z x sqrt( LT x sigma_d^2  +  d^2 x sigma_LT^2 )
    #                    \___________/     \_____________/
    #                    demand varies      delivery date varies
    #
    # The second term was missing before, which assumed every delivery lands
    # exactly on day LT. On long lead times that term usually dominates, so its
    # absence systematically under-buffered the items whose stockouts hurt most.
    # sigma_LT is 0 when lead-time variability was never measured, and the
    # formula then reduces exactly to the previous Z x sigma_d x sqrt(LT).
    if "lead_time_sigma" in df.columns:
        lt_sigma = pd.to_numeric(df["lead_time_sigma"], errors="coerce").fillna(0)
    else:
        lt_sigma = 0.0

    demand_var = lt * df["std_daily"] ** 2
    lead_time_var = (df["avg_daily_demand"] ** 2) * (lt_sigma ** 2)

    df["safety_stock"] = (df["_z"] * np.sqrt(demand_var + lead_time_var)).round(0)
    df["rop"] = (df["avg_daily_demand"] * lt + df["safety_stock"]).round(0)

    # Target = ROP + 30 days buffer (or max_level if provided)
    if "max_level" in df.columns:
        target = np.where(df["max_level"] > 0, df["max_level"], df["rop"] + df["avg_daily_demand"] * 30)
    else:
        target = df["rop"] + df["avg_daily_demand"] * 30

    # Quantity already on order (open purchase orders). Without it the tool
    # recommends re-ordering goods that are already inbound — the first thing a
    # buyer notices. Populated by the "open_po" file role in data_merge; 0 when
    # the customer has not supplied a purchase-order file.
    if "open_po_qty" in df.columns:
        open_po = pd.to_numeric(df["open_po_qty"], errors="coerce").fillna(0)
    else:
        open_po = 0
    net_need = target - df["stock_qty"] - open_po

    # Dead stock must never generate an order, full stop -- not "usually zero
    # because net_need usually goes negative." classify_status flags dead
    # stock two ways: zero demand, OR DOS >= 120 on a small-but-nonzero
    # demand. The demand>0 gate below only catches the first case. The second
    # relied on target ending up below stock_qty by coincidence of the math --
    # which a customer-supplied max_level can override, forcing a positive
    # target (and therefore a real order_qty) on an item already flagged dead.
    is_dead = df["status"] == "dead_stock"
    df["order_qty"] = np.where(
        (df["avg_daily_demand"] > 0) & ~is_dead,
        np.maximum(net_need, 0).round(0),
        0,
    )

    df = df.drop(columns=["_z", "service_level"], errors="ignore")
    return df
