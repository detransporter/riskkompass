"""IHA-rapport: hälsopoäng, ABC/XYZ/trend, DOS/status, leverantörsanalys,
ledtidsavstämning, lagerbrygga och rotorsaker -- körd direkt mot den levande
transaktionsloggen istället för en uppladdad fil. Se analysis_bridge.py och
CLAUDE.md "IHA integration".

All visningstext är på svenska -- de vendrade analysmodulerna har engelska
kolumnnamn/statusvärden/prosa i sin källa, så översättningen sker via
components/sv.py precis innan rendering, aldrig i analysis/*.py själva."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
from analysis.health_scorer import summary_stats
from analysis.inventory_bridge import root_cause_summary
from analysis.lead_time import lead_time_reconciliation, supplier_scorecard
from analysis.segmentation import matrix_summary
from analysis_bridge import build_canonical, run_analysis
from components.export import excel_download_button
from components.sv import (
    POLICY_LABELS,
    ROOT_CAUSE_ACTIONS,
    ROOT_CAUSE_LABELS,
    STATUS_LABELS,
    STATUS_REASON_LABELS,
    TREND_LABELS,
    rename_columns,
    supplier_flags_sv,
    translate_demand_note,
)


def _sek(value: float) -> str:
    return f"{value:,.0f} SEK".replace(",", " ")


def _render_health_score(df: pd.DataFrame) -> None:
    stats = summary_stats(df)
    col1, col2, col3 = st.columns([1, 1, 2])
    col1.metric("Lagerhälsopoäng", f"{stats['health_score']:.1f} / 100")
    col2.metric("Antal artiklar", stats["total_skus"])
    col3.caption(
        "Viktat mot ABC-klass — en död A-artikel väger tyngre än en död C-artikel. "
        "100 = allt friskt, 0 = allt dött."
    )


def _render_kpis(bridge: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Totalt lagervärde", _sek(bridge["total_value"]))
    col2.metric("Dött lager", _sek(bridge["dead"]))
    col3.metric("Överlager", _sek(bridge["excess"]))
    col4.metric("Frigörbart kapital", _sek(bridge["releasable"]))

    col5, col6 = st.columns(2)
    col5.metric("Underskott (kräver påfyllning)", _sek(bridge["deficit"]))
    col6.metric("Årlig lagerkostnadsbesparing", _sek(bridge["annual_holding_saving"]))


def _render_status_breakdown(df: pd.DataFrame) -> None:
    st.subheader("Status")
    labeled = df["status"].map(STATUS_LABELS).fillna(df["status"])
    counts = labeled.value_counts()
    value_by_status = df.groupby(labeled)["value_sek"].sum()
    out = pd.DataFrame({"antal_artiklar": counts, "lagervärde": value_by_status}).reset_index()
    out.columns = ["status", "antal_artiklar", "lagervärde"]
    st.dataframe(out.sort_values("lagervärde", ascending=False), width="stretch", hide_index=True)


def _render_trend_breakdown(df: pd.DataFrame) -> None:
    if "trend_class" not in df.columns or df["trend_class"].isna().all():
        return
    known = df[df["trend_class"].notna()]
    st.subheader("Trend")
    labeled = known["trend_class"].map(TREND_LABELS).fillna(known["trend_class"])
    counts = labeled.value_counts()
    value_by_trend = known.groupby(labeled)["value_sek"].sum()
    out = pd.DataFrame({"antal_artiklar": counts, "lagervärde": value_by_trend}).reset_index()
    out.columns = ["trend", "antal_artiklar", "lagervärde"]
    st.dataframe(out.sort_values("lagervärde", ascending=False), width="stretch", hide_index=True)
    unclassified = len(df) - len(known)
    if unclassified:
        st.caption(f"{unclassified} artiklar har för kort historik för att klassificeras.")


def _render_supplier_analysis(df: pd.DataFrame) -> None:
    scorecard = supplier_scorecard(df)
    if scorecard.empty:
        return
    st.subheader("Leverantörsanalys")
    display_cols = [c for c in scorecard.columns if c not in ("dead_value_sek",)]
    st.dataframe(rename_columns(scorecard[display_cols]), width="stretch", hide_index=True)
    excel_download_button(rename_columns(scorecard), "leverantorsanalys.xlsx", key="export_suppliers")

    for flag in supplier_flags_sv(scorecard):
        st.warning(flag)


def _render_lead_time_reconciliation(df: pd.DataFrame) -> None:
    recon = lead_time_reconciliation(df)
    if not recon or recon.get("measured_skus", 0) == 0:
        st.subheader("Ledtidsavstämning")
        st.caption(
            "Ingen uppmätt ledtid ännu — kräver flera mottagningar per artikel över tid. "
            "Beräkningarna använder tills vidare artikelns angivna ledtid."
        )
        return

    st.subheader("Ledtidsavstämning")
    col1, col2, col3 = st.columns(3)
    col1.metric("Uppmätta artiklar", recon["measured_skus"])
    col2.metric("Snittavvikelse (dagar)", f"{recon['mean_gap']:+.0f}")
    col3.metric("Underskattade artiklar", recon["understated_skus"])
    st.caption(
        f"Angiven ledtid underskattar den verkliga med mer än 5 dagar på "
        f"{recon['understated_skus']} artiklar, värda {_sek(recon['understated_value'])}."
    )
    worst = recon.get("worst")
    if worst is not None and not worst.empty:
        st.dataframe(rename_columns(worst), width="stretch", hide_index=True)


def _render_item_table(df: pd.DataFrame) -> None:
    st.subheader("Artiklar")
    cols = [
        "sku", "description", "abc_class", "xyz_class", "trend_class", "status", "status_reason",
        "stock_qty", "value_sek", "dos", "safety_stock", "rop", "order_qty",
    ]
    cols = [c for c in cols if c in df.columns]
    table = df[cols].sort_values("value_sek", ascending=False).copy()
    table["dos"] = table["dos"].replace([float("inf")], None)
    table["status"] = table["status"].map(STATUS_LABELS).fillna(table["status"])
    table["status_reason"] = table["status_reason"].map(STATUS_REASON_LABELS).fillna(table["status_reason"])
    table["trend_class"] = table["trend_class"].map(TREND_LABELS).fillna(table["trend_class"])
    st.dataframe(rename_columns(table), width="stretch", hide_index=True)
    excel_download_button(rename_columns(table), "iha_rapport.xlsx", key="export_items")


def _render_root_causes(df: pd.DataFrame) -> None:
    summary = root_cause_summary(df)
    if summary.empty:
        return
    st.subheader("Rotorsaker (dött lager & trögrörligt)")
    for _, row in summary.iterrows():
        label = ROOT_CAUSE_LABELS.get(row["root_cause"], row["label"])
        action = ROOT_CAUSE_ACTIONS.get(row["root_cause"], row["action"])
        with st.expander(f"{label} — {row['skus']} artiklar, {_sek(row['value_sek'])}"):
            st.write(action)


def _render_matrix(df: pd.DataFrame) -> None:
    matrix = matrix_summary(df)
    if matrix.empty:
        return
    st.subheader("ABC × XYZ")
    matrix = matrix.copy()
    matrix["policy"] = matrix["policy"].map(POLICY_LABELS).fillna(matrix["policy"])
    st.dataframe(
        rename_columns(matrix.sort_values("value_sek", ascending=False)),
        width="stretch", hide_index=True,
    )


def render(user: auth.User) -> None:
    st.title("IHA-rapport")
    conn = db.get_tenant_conn(user.company_slug)
    try:
        df, demand_note = build_canonical(conn)
        if df.empty:
            st.info("Lägg till artiklar under 'Artiklar & platser' först.")
            return

        has_txns = conn.execute("SELECT 1 FROM transactions LIMIT 1").fetchone() is not None
        if not has_txns:
            st.info(
                "Inga transaktioner registrerade ännu. Ta emot eller plocka något "
                "under 'Ta emot' / 'Plocka' för att analysen ska ha något att räkna på."
            )
            return

        df, bridge = run_analysis(df)

        _render_health_score(df)
        st.divider()
        _render_kpis(bridge)
        st.divider()
        _render_status_breakdown(df)
        st.divider()
        _render_trend_breakdown(df)
        st.divider()
        _render_matrix(df)
        st.divider()
        _render_supplier_analysis(df)
        st.divider()
        _render_lead_time_reconciliation(df)
        st.divider()
        _render_root_causes(df)
        st.divider()
        _render_item_table(df)

        st.caption(f"Efterfrågedata: {translate_demand_note(demand_note)}")
    finally:
        conn.close()
