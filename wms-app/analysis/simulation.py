"""
analysis/simulation.py
Phase 5 — what happens to the capital if we change the policy?

The bridge (phase 4) says what the inventory should be under today's rules.
This says what it would be under different ones, which is the question that
turns a one-off assessment into an ongoing engagement: every quarter the
parameters drift, and someone has to re-run the trade-off.

Four levers, because these are the four things a client can actually change:

    service level        the promise made to customers, per ABC class
    lead time            how long suppliers take
    lead-time reliability  how much that varies — usually the cheaper fix
    batch size           how often you order, which sets the cycle stock

The simulation recomputes REQUIRED capital, not stock on hand. Excess and dead
stock are a separate decision (clear them or not); mixing the two would let a
policy change take credit for a warehouse clean-out.

Honesty rules baked in:
  • Raising a service level costs capital. That shows as a positive number.
  • Levers are attributed one at a time in a fixed order, so the waterfall adds
    up exactly and the order is stated rather than hidden.
"""

from statistics import NormalDist

import numpy as np
import pandas as pd

# Service level per ABC class as the tool plans today (dos_calculator._SL_MAP).
DEFAULT_SERVICE_LEVELS = {"A": 0.98, "B": 0.95, "C": 0.80}

# Applying levers in a fixed order makes the attribution reproducible. Interaction
# effects land on whichever lever is applied later, which is why the order is
# stated in the UI rather than left implicit.
LEVER_ORDER = ["service_level", "lead_time", "lead_time_reliability", "batch_size"]

LEVER_LABELS = {
    "service_level": "Service level",
    "lead_time": "Lead time",
    "lead_time_reliability": "Lead-time reliability",
    "batch_size": "Order batch size",
}


def z_for(service_level: float) -> float:
    """Safety factor for a service level. Uses the inverse normal directly so
    any level works, not only the handful in the lookup table."""
    sl = min(max(float(service_level), 0.500001), 0.999999)
    return NormalDist().inv_cdf(sl)


def _num(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def _unit_value(df: pd.DataFrame) -> pd.Series:
    unit = pd.Series(np.nan, index=df.index, dtype=float)
    for col in ("unit_price", "unit_cost"):
        if col in df.columns:
            unit = unit.where(unit > 0, pd.to_numeric(df[col], errors="coerce"))
    qty = _num(df, "stock_qty")
    val = _num(df, "value_sek")
    unit = unit.where(unit > 0, (val / qty.where(qty > 0)))
    return unit.fillna(0.0)


def _required(df: pd.DataFrame, sl_map: dict, lt_scale: pd.Series,
              sigma_scale: pd.Series, batch_scale: pd.Series) -> pd.Series:
    """Required inventory value per SKU under the given settings."""
    demand = _num(df, "avg_daily_demand")
    sigma_d = _num(df, "std_daily")
    unit = _unit_value(df)

    lt = (_num(df, "lead_time_used") * lt_scale).clip(lower=1)

    # Shortening a lead time normally shrinks its spread proportionally — the
    # process is the same, just shorter, so the coefficient of variation holds.
    # Treating the two as independent made the lead-time lever look worthless
    # for exactly the suppliers where it matters most. The reliability lever
    # then reduces the spread *further*, which is the separate improvement of
    # making an unchanged lead time more predictable.
    lt_sigma = (_num(df, "lead_time_sigma") * lt_scale * sigma_scale).clip(lower=0)

    abc = df["abc_class"] if "abc_class" in df.columns else pd.Series("C", index=df.index)
    z = abc.map({k: z_for(v) for k, v in sl_map.items()}).fillna(z_for(0.95)).astype(float)

    safety = z * np.sqrt(lt * sigma_d ** 2 + (demand ** 2) * (lt_sigma ** 2))

    # Cycle stock is half the batch. Where the batch was measured from receipts
    # it scales directly; otherwise the stored cycle_stock is scaled instead.
    if "avg_receipt_qty" in df.columns:
        batch = pd.to_numeric(df["avg_receipt_qty"], errors="coerce")
        cycle = (batch * batch_scale / 2)
        cycle = cycle.where(batch.notna(), _num(df, "cycle_stock") * batch_scale)
    else:
        cycle = _num(df, "cycle_stock") * batch_scale

    required = (cycle.fillna(0) + safety.fillna(0)) * unit

    # A dead item requires nothing — no policy change makes it needed again.
    if "status" in df.columns:
        required = required.where(df["status"] != "dead_stock", 0.0)
    return required


def simulate(df: pd.DataFrame,
             service_levels: dict | None = None,
             lt_reduction: float = 0.0,
             lt_sigma_reduction: float = 0.0,
             batch_change: float = 0.0,
             suppliers: list | None = None) -> dict:
    """Recompute required capital under new policy settings.

    lt_reduction / lt_sigma_reduction / batch_change are fractions: 0.20 means
    "20% shorter", "20% less variable", "20% smaller batches".
    suppliers limits the two lead-time levers to a subset — you rarely
    renegotiate with everyone at once.

    Returns baseline, simulated, delta and a per-lever attribution.
    """
    df = df.copy()
    sl_new = {**DEFAULT_SERVICE_LEVELS, **(service_levels or {})}

    ones = pd.Series(1.0, index=df.index)

    # Lead-time levers apply only to the chosen suppliers.
    sup_col = next((c for c in df.columns
                    if c in ("supplier", "leverantor", "leverantör", "vendor")), None)
    if suppliers and sup_col:
        in_scope = df[sup_col].isin(suppliers)
    else:
        in_scope = pd.Series(True, index=df.index)

    lt_scale = ones.where(~in_scope, 1 - lt_reduction)
    sigma_scale = ones.where(~in_scope, 1 - lt_sigma_reduction)
    batch_scale = pd.Series(1 - batch_change, index=df.index)

    baseline = _required(df, DEFAULT_SERVICE_LEVELS, ones, ones, ones)

    # ── Attribution: apply one lever at a time, in a fixed order ─────────────
    settings = {
        "service_level":         (sl_new, ones, ones, ones),
        "lead_time":             (sl_new, lt_scale, ones, ones),
        "lead_time_reliability": (sl_new, lt_scale, sigma_scale, ones),
        "batch_size":            (sl_new, lt_scale, sigma_scale, batch_scale),
    }

    contributions, running = {}, float(baseline.sum())
    for lever in LEVER_ORDER:
        total = float(_required(df, *settings[lever]).sum())
        contributions[lever] = total - running
        running = total

    simulated = _required(df, sl_new, lt_scale, sigma_scale, batch_scale)

    actual_value = float(_num(df, "value_sek").sum())
    base_total = float(baseline.sum())
    sim_total = float(simulated.sum())

    df["required_now"] = baseline
    df["required_simulated"] = simulated
    df["required_delta"] = simulated - baseline

    return {
        "df": df,
        "actual_value": actual_value,
        "baseline_required": base_total,
        "simulated_required": sim_total,
        "delta": sim_total - base_total,
        "contributions": contributions,
        "skus_in_scope": int(in_scope.sum()),
        # Total opportunity = clearing what is not needed AND fixing the policy.
        "gap_to_actual": actual_value - sim_total,
        "annual_holding_delta": (sim_total - base_total) * 0.22,
        "service_levels": sl_new,
    }


def biggest_movers(sim: dict, n: int = 15) -> pd.DataFrame:
    """SKUs where the policy change moves the most capital, either way."""
    df = sim["df"]
    if "required_delta" not in df.columns:
        return pd.DataFrame()
    d = df[df["required_delta"].abs() > 0].copy()
    if d.empty:
        return pd.DataFrame()
    d["abs_delta"] = d["required_delta"].abs()
    cols = [c for c in ["sku", "description", "abc_class", "xyz_class", "supplier",
                        "required_now", "required_simulated", "required_delta"]
            if c in d.columns]
    return d.nlargest(n, "abs_delta")[cols]
