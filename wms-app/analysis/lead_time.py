# Vendored from iha-saas/analysis/lead_time.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration". NOTE: wms-app's analysis_bridge.py
# does not currently pass order_date_col/promised_col to aggregate_inbound
# (the WMS schema has no PO-order-date tracking yet -- see CLAUDE.md), so in
# practice lead_time_used here almost always falls back to "master" (the
# item's own lead_time_days) rather than "sku_measured"/"supplier_measured".
# That is an honest MVP limitation, not a bug in this file.
"""
Phase 3 — stop trusting the ERP's lead-time field, and buffer against the
variability that field never captured.

Two problems are solved here.

1. WHICH LEAD TIME TO USE
   lead_time_days in master data is what someone typed in once. The receipt
   history says what suppliers actually do. Where the two disagree, the data
   wins — but the substitution is always recorded in lead_time_source so the
   change is explainable, never silent.

   Priority: measured on the SKU → measured on its supplier → promised on open
   POs → master data. A SKU with too few receipts of its own can still borrow
   its supplier's measured variability, which is usually the same process.

2. VARIABILITY IN LEAD TIME
   The old safety stock formula was SS = Z x sigma_d x sqrt(LT). That covers
   demand varying during a *fixed* lead time. It silently assumes deliveries
   always arrive exactly on day LT — which is the assumption that breaks on
   long offshore lead times, precisely where stockouts hurt most.

   The correct form adds the lead-time term:

       SS = Z x sqrt( LT x sigma_d^2  +  d^2 x sigma_LT^2 )

   When sigma_LT is unknown it is zero and the formula collapses back to the
   old one exactly — so items without measured lead-time variability keep the
   safety stock they had. Nothing moves without evidence behind it.
"""

import numpy as np
import pandas as pd

MIN_LT_SAMPLES = 3          # below this, a lead-time mean is anecdote
# A standard deviation needs more evidence than a mean. Safety stock scales
# with sigma_LT squared, so an inflated sigma from three data points would
# multiply the recommended buffer several times over on nothing but noise.
# Below this threshold the mean is still used but sigma_LT is left at 0, which
# collapses the formula back to the demand-only term.
MIN_LT_SIGMA_SAMPLES = 5
MIN_SUPPLIER_SAMPLES = 5    # a supplier-level proxy needs a bit more
CONCENTRATION_LIMIT = 0.40  # >40% of inventory value with one supplier = risk
ON_TIME_TARGET = 0.95       # OTIF target for A suppliers


def _supplier_col(df: pd.DataFrame) -> str | None:
    return next((c for c in df.columns
                 if c in ("supplier", "leverantor", "leverantör", "vendor")), None)


def resolve_lead_time(df: pd.DataFrame) -> pd.DataFrame:
    """Decide the lead time and lead-time sigma to plan with.

    Adds:
        lead_time_used     days, the figure replenishment should use
        lead_time_sigma    days, 0 when variability could not be measured
        lead_time_source   sku_measured | supplier_measured | promised | master
        lead_time_gap      measured minus master, in days (NaN when unmeasured)
    """
    df = df.copy()
    n = len(df)

    master_lt = pd.to_numeric(df.get("lead_time_days", pd.Series(np.nan, index=df.index)),
                              errors="coerce")

    used = pd.Series(np.nan, index=df.index, dtype=float)
    sigma = pd.Series(np.nan, index=df.index, dtype=float)
    source = pd.Series("master", index=df.index, dtype=object)

    # ── 1. Measured on the SKU itself ────────────────────────────────────────
    if {"lt_actual_mean", "lt_samples"} <= set(df.columns):
        mean = pd.to_numeric(df["lt_actual_mean"], errors="coerce")
        std = pd.to_numeric(df.get("lt_actual_std", np.nan), errors="coerce")
        samples = pd.to_numeric(df["lt_samples"], errors="coerce").fillna(0)

        ok = mean.notna() & (samples >= MIN_LT_SAMPLES)
        used[ok] = mean[ok]
        source[ok] = "sku_measured"
        # Sigma only where there are enough deliveries to estimate one.
        sigma_ok = ok & (samples >= MIN_LT_SIGMA_SAMPLES)
        sigma[sigma_ok] = std[sigma_ok].fillna(0)
        sigma[ok & ~sigma_ok] = 0.0

    # ── 2. Borrow the supplier's measured lead time ──────────────────────────
    sup_col = _supplier_col(df)
    if sup_col and "lt_actual_mean" in df.columns:
        w = df.assign(
            _m=pd.to_numeric(df["lt_actual_mean"], errors="coerce"),
            _sd=pd.to_numeric(df.get("lt_actual_std", np.nan), errors="coerce"),
            _n=pd.to_numeric(df.get("lt_samples", 0), errors="coerce").fillna(0),
        ).dropna(subset=["_m"])

        if not w.empty:
            # Pooled within-SKU variance, NOT the spread of per-SKU averages.
            # The latter measures how much lead time differs between articles
            # from this supplier — a different question, and typically far
            # smaller, which would quietly understate the buffer.
            w["_dof"] = (w["_n"] - 1).clip(lower=0)
            w["_ss"] = w["_dof"] * w["_sd"].fillna(0) ** 2

            per_supplier = w.groupby(sup_col).agg(
                sup_mean=("_m", "mean"), sup_samples=("_n", "sum"),
                _ss=("_ss", "sum"), _dof=("_dof", "sum"))
            per_supplier["sup_sigma"] = np.sqrt(
                per_supplier["_ss"] / per_supplier["_dof"].where(per_supplier["_dof"] > 0))
            per_supplier = per_supplier[per_supplier["sup_samples"] >= MIN_SUPPLIER_SAMPLES]

            if not per_supplier.empty:
                mapped_mean = df[sup_col].map(per_supplier["sup_mean"])
                mapped_std = df[sup_col].map(per_supplier["sup_sigma"])
                fill = used.isna() & mapped_mean.notna()
                used[fill] = mapped_mean[fill]
                sigma[fill] = mapped_std[fill].fillna(0)
                source[fill] = "supplier_measured"

    # ── 3. What the open purchase orders promise ─────────────────────────────
    if "promised_lt_days" in df.columns:
        promised = pd.to_numeric(df["promised_lt_days"], errors="coerce")
        fill = used.isna() & promised.notna()
        used[fill] = promised[fill]
        sigma[fill] = 0.0
        source[fill] = "promised"

    # ── 4. Fall back to master data ──────────────────────────────────────────
    fill = used.isna()
    used[fill] = master_lt[fill]
    sigma[fill] = 0.0
    source[fill] = "master"

    df["lead_time_used"] = used.fillna(0)
    df["lead_time_sigma"] = sigma.fillna(0)
    df["lead_time_source"] = source
    df["lead_time_gap"] = np.where(
        source.isin(["sku_measured", "supplier_measured"]), used - master_lt, np.nan)

    return df


def lead_time_reconciliation(df: pd.DataFrame) -> dict:
    """Headline comparison of the ERP's lead times against measured reality."""
    if "lead_time_gap" not in df.columns:
        return {}

    gap = pd.to_numeric(df["lead_time_gap"], errors="coerce")
    measured = df[gap.notna()]
    if measured.empty:
        return {"measured_skus": 0}

    master = pd.to_numeric(measured.get("lead_time_days", np.nan), errors="coerce")
    actual = pd.to_numeric(measured["lead_time_used"], errors="coerce")
    understated = measured[gap > 5]

    return {
        "measured_skus": len(measured),
        "master_mean": float(master.mean()) if master.notna().any() else None,
        "actual_mean": float(actual.mean()),
        "mean_gap": float(gap.mean()),
        "understated_skus": len(understated),
        "understated_value": float(understated.get("value_sek", pd.Series(dtype=float)).sum()),
        "worst": measured.nlargest(10, "lead_time_gap")[
            [c for c in ["sku", "description", "supplier", "lead_time_days",
                         "lead_time_used", "lead_time_sigma", "lead_time_gap", "value_sek"]
             if c in measured.columns]
        ],
    }


def supplier_scorecard(df: pd.DataFrame) -> pd.DataFrame:
    """One row per supplier: exposure, reliability and what it ties up.

    Concentration, lead-time reliability and dead stock in one table is the
    view that turns "our supplier is fine" into a number.
    """
    sup_col = _supplier_col(df)
    if not sup_col:
        return pd.DataFrame()

    d = df[df[sup_col].notna()].copy()
    if d.empty:
        return pd.DataFrame()

    total_value = df["value_sek"].sum()

    agg = {
        "skus": ("sku", "count"),
        "value_sek": ("value_sek", "sum"),
    }
    out = d.groupby(sup_col).agg(**agg)

    if "lead_time_used" in d.columns:
        out["lt_days"] = d.groupby(sup_col)["lead_time_used"].mean()
    if "lead_time_sigma" in d.columns:
        out["lt_sigma"] = d.groupby(sup_col)["lead_time_sigma"].mean()
    if "on_time_rate" in d.columns:
        ot = pd.to_numeric(d["on_time_rate"], errors="coerce")
        out["on_time_rate"] = ot.groupby(d[sup_col]).mean()
    if "status" in d.columns:
        dead = d[d["status"] == "dead_stock"]
        out["dead_value_sek"] = dead.groupby(sup_col)["value_sek"].sum()
        out["dead_value_sek"] = out["dead_value_sek"].fillna(0)

    out["value_share"] = out["value_sek"] / total_value if total_value else 0
    out["dead_share"] = (out.get("dead_value_sek", 0) / out["value_sek"].where(out["value_sek"] > 0))

    # Lead-time reliability: sigma relative to the lead time itself. A 10-day
    # spread on a 90-day lead time is ordinary; on a 5-day lead time it is chaos.
    if {"lt_days", "lt_sigma"} <= set(out.columns):
        out["lt_cv"] = out["lt_sigma"] / out["lt_days"].where(out["lt_days"] > 0)

    return out.sort_values("value_sek", ascending=False).reset_index()


def supplier_flags(scorecard: pd.DataFrame) -> list[str]:
    """Plain-language risks worth putting in front of a client."""
    if scorecard.empty:
        return []

    flags = []
    top = scorecard.iloc[0]
    if top["value_share"] > CONCENTRATION_LIMIT:
        flags.append(
            f"**Concentration risk** — {top.iloc[0]} holds "
            f"{top['value_share']*100:.0f}% of inventory value "
            f"({top['value_sek']/1e6:.1f} MSEK). Above {CONCENTRATION_LIMIT*100:.0f}% "
            "a single supplier failure becomes a business continuity problem."
        )

    if "on_time_rate" in scorecard.columns:
        late = scorecard[(scorecard["on_time_rate"].notna())
                         & (scorecard["on_time_rate"] < ON_TIME_TARGET)]
        late = late.nlargest(3, "value_sek")
        for _, r in late.iterrows():
            flags.append(
                f"**{r.iloc[0]}** delivers on time {r['on_time_rate']*100:.0f}% of the "
                f"time (target {ON_TIME_TARGET*100:.0f}%), on {r['value_sek']/1e6:.1f} MSEK "
                "of inventory. Every late delivery is paid for with safety stock."
            )

    if "lt_cv" in scorecard.columns:
        erratic = scorecard[(scorecard["lt_cv"] > 0.5) & (scorecard["value_sek"] > 0)]
        erratic = erratic.nlargest(3, "value_sek")
        for _, r in erratic.iterrows():
            flags.append(
                f"**{r.iloc[0]}** has an unpredictable lead time — "
                f"{r['lt_days']:.0f} days on average but a spread of ±{r['lt_sigma']:.0f} days. "
                "Unpredictability, not length, is what forces the buffer up."
            )

    if "dead_share" in scorecard.columns:
        dead = scorecard[(scorecard["dead_share"] > 0.30)
                         & (scorecard["value_sek"] > scorecard["value_sek"].sum() * 0.05)]
        for _, r in dead.nlargest(3, "dead_value_sek").iterrows():
            flags.append(
                f"**{r.iloc[0]}** — {r['dead_share']*100:.0f}% of what you hold from this "
                f"supplier is dead stock ({r['dead_value_sek']/1e6:.1f} MSEK). "
                "Look at minimum order quantities before renegotiating price."
            )

    return flags
