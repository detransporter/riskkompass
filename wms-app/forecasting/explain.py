"""Plain-language Swedish explanations for a computed policy
(docs/FORECAST_SPEC.md Phase 6): "produces a one-paragraph Swedish
explanation per item that references real drivers (variability,
lead-time uncertainty, intermittency)".

Pure string formatting from already-computed numbers -- this module
computes nothing itself, it only explains forecasting/policy.py's output
and the segment/lead-time context that went into it. Every driver named
in a sentence is a real number from the caller, not a template filled
with a guess: if a driver isn't available, its sentence is left out
rather than printed with a placeholder.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENT_LABELS_SV = {
    "smooth": "jämn",
    "erratic": "oregelbunden",
    "intermittent": "intermittent (glesa order)",
    "lumpy": "klumpig (glesa och ojämnt stora order)",
    "no_demand": "utan efterfrågan",
    "unclassifiable": "för kort historik för att klassificera",
}


def _demand_cv(demand_history: pd.Series) -> float | None:
    recent = demand_history.iloc[-52:]
    if len(recent) < 2 or recent.mean() == 0:
        return None
    return float(recent.std() / recent.mean())


def explain_policy(article_id: str, description: str | None, policy: dict,
                   sbc_class: str | None, demand_history: pd.Series,
                   lead_time_days_samples: np.ndarray) -> str:
    """One paragraph, Swedish, referencing: the target service level and
    why (margin-based vs. ABC fallback), the demand pattern (SBC segment
    plus coefficient of variation when computable), and lead-time
    uncertainty (spread of the supplier's own delivery history) when
    there is enough of it to characterize."""
    label = description or article_id
    service_pct = round(policy["target_service_level"] * 100)

    if policy["margin_based"]:
        service_reason = f"baserat på artikelns marginal mot lagerhållningskostnaden"
    else:
        service_reason = "baserat på ABC-klass (ingen marginaldata tillgänglig för denna artikel)"

    segment_label = SEGMENT_LABELS_SV.get(sbc_class, "okänt mönster")
    cv = _demand_cv(demand_history)
    if cv is not None:
        demand_sentence = (
            f"Efterfrågan är {segment_label} (variationskoefficient {cv:.2f} de senaste 52 veckorna)."
        )
    else:
        demand_sentence = f"Efterfrågan är {segment_label}."

    n_lead = len(lead_time_days_samples)
    if n_lead >= 2:
        lead_min, lead_max = float(np.min(lead_time_days_samples)), float(np.max(lead_time_days_samples))
        lead_std = float(np.std(lead_time_days_samples))
        lead_sentence = (
            f"Leverantörens ledtid har varierat mellan {lead_min:.0f} och {lead_max:.0f} dagar "
            f"(std {lead_std:.1f} dagar) baserat på {n_lead} tidigare leveranser."
        )
    else:
        lead_sentence = "Leverantörens ledtidshistorik är för kort för att uppskatta spridning ännu."

    return (
        f"{label}: målservicenivå {service_pct}% ({service_reason}). {demand_sentence} {lead_sentence} "
        f"Beställningspunkt {policy['reorder_point']:.0f} st, varav säkerhetslager "
        f"{policy['safety_stock']:.0f} st utöver förväntad efterfrågan under ledtiden "
        f"({policy['expected_lead_time_demand']:.0f} st). Rekommenderad orderkvantitet "
        f"{policy['order_quantity']:.0f} st."
    )
