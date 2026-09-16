"""IHA-rapport: ABC, DOS/status, lagerbrygga och rotorsaker, körd direkt mot
den levande transaktionsloggen istället för en uppladdad fil -- se
analysis_bridge.py och CLAUDE.md "IHA integration"."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
from analysis.inventory_bridge import root_cause_summary
from analysis.segmentation import matrix_summary
from analysis_bridge import build_canonical, run_analysis

_STATUS_LABELS = {
    "healthy": "Frisk",
    "slow_mover": "Trög",
    "dead_stock": "Dött lager",
    "stockout_risk": "Stockout-risk",
}


def _sek(value: float) -> str:
    return f"{value:,.0f} SEK".replace(",", " ")


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
    counts = df["status"].map(_STATUS_LABELS).fillna(df["status"]).value_counts()
    value_by_status = df.groupby(df["status"].map(_STATUS_LABELS).fillna(df["status"]))["value_sek"].sum()
    out = pd.DataFrame({"antal_artiklar": counts, "lagervärde": value_by_status}).reset_index()
    out.columns = ["status", "antal_artiklar", "lagervärde"]
    st.dataframe(out.sort_values("lagervärde", ascending=False), width="stretch", hide_index=True)


def _render_item_table(df: pd.DataFrame) -> None:
    st.subheader("Artiklar")
    cols = [
        "sku", "description", "abc_class", "xyz_class", "status", "status_reason",
        "stock_qty", "value_sek", "dos", "safety_stock", "rop", "order_qty",
    ]
    cols = [c for c in cols if c in df.columns]
    table = df[cols].sort_values("value_sek", ascending=False).copy()
    table["dos"] = table["dos"].replace([float("inf")], None)
    st.dataframe(table, width="stretch", hide_index=True)


def _render_root_causes(df: pd.DataFrame) -> None:
    summary = root_cause_summary(df)
    if summary.empty:
        return
    st.subheader("Rotorsaker (dött lager & trögrörligt)")
    for _, row in summary.iterrows():
        with st.expander(f"{row['label']} — {row['skus']} artiklar, {_sek(row['value_sek'])}"):
            st.write(row["action"])


def _render_matrix(df: pd.DataFrame) -> None:
    matrix = matrix_summary(df)
    if matrix.empty:
        return
    st.subheader("ABC × XYZ")
    st.dataframe(
        matrix.sort_values("value_sek", ascending=False), width="stretch", hide_index=True
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

        _render_kpis(bridge)
        st.divider()
        _render_status_breakdown(df)
        st.divider()
        _render_matrix(df)
        st.divider()
        _render_root_causes(df)
        st.divider()
        _render_item_table(df)

        st.caption(f"Efterfrågedata: {demand_note}")
    finally:
        conn.close()
