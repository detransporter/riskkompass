# Vendored from iha-saas/analysis/health_scorer.py (unchanged). See
# wms-app/CLAUDE.md "IHA integration".

import pandas as pd


STATUS_WEIGHTS = {
    "healthy": 100,
    "slow_mover": 50,
    "stockout_risk": 30,
    "dead_stock": 0,
}

ABC_WEIGHTS = {"A": 3, "B": 2, "C": 1}


def compute_health_score(df: pd.DataFrame) -> float:
    """
    Weighted inventory health score 0–100.
    Weight = ABC priority × status score.
    """
    if df.empty:
        return 0.0

    df = df.copy()
    df["_status_score"] = df["status"].map(STATUS_WEIGHTS).fillna(50)
    df["_abc_weight"] = df["abc_class"].map(ABC_WEIGHTS).fillna(1)
    df["_weighted_score"] = df["_status_score"] * df["_abc_weight"]

    max_possible = df["_abc_weight"].sum() * 100
    if max_possible == 0:
        return 0.0

    score = df["_weighted_score"].sum() / max_possible * 100
    return round(score, 1)


def summary_stats(df: pd.DataFrame) -> dict:
    """Return key KPIs as a dict for dashboard display."""
    total_value = df["value_sek"].sum()
    dead = df[df["status"] == "dead_stock"]
    slow = df[df["status"] == "slow_mover"]
    risk = df[df["status"] == "stockout_risk"]

    return {
        "total_skus": len(df),
        "total_value_sek": total_value,
        "dead_stock_skus": len(dead),
        "dead_stock_value_sek": dead["value_sek"].sum(),
        "slow_mover_skus": len(slow),
        "slow_mover_value_sek": slow["value_sek"].sum(),
        "stockout_risk_skus": len(risk),
        "health_score": compute_health_score(df),
    }
