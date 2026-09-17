"""Påfyllning: vad som bör beställas nu, sorterat efter brådska.

Körs på samma pipeline som IHA-rapporten (analysis_bridge.run_analysis) men
visar bara raderna där compute_replenishment redan föreslagit en
orderkvantitet > 0 -- ingen ny beräkning, bara ett annat filter och en annan
sortering på data som redan finns.

Viktigt att veta: "frisk" status (dos_calculator.py) och "behöver beställas"
(den här sidan) är INTE samma fråga. En artikel kan ha en fullt normal DOS
och ändå ligga under sitt påfyllningsmål (rop + 30 dagars buffert) -- se
SKU-A2 i test_analysis_bridge.py för ett verifierat exempel. Statusfärgen på
IHA-rapporten svarar "säljer det här normalt?", den här sidan svarar
"behöver jag beställa mer just nu?". Två olika frågor, två olika svar,
avsiktligt.

Ren rådgivande lista -- appen har ingen "markera som beställd"-funktion
(det skulle kräva öppna-PO-spårning som schemat inte har än, se CLAUDE.md).
Samma artikel dyker upp igen imorgon om inget beställs eller tas emot.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
from analysis_bridge import build_canonical, run_analysis
from components.export import excel_download_button
from components.sv import STATUS_LABELS, rename_columns


def _sek(value: float) -> str:
    return f"{value:,.0f} SEK".replace(",", " ")


def reorder_df(df: pd.DataFrame) -> pd.DataFrame:
    """Filtrerar till artiklar med en föreslagen orderkvantitet > 0 och
    sorterar efter brådska: stockout-risk först, sedan minst lagerdagar
    kvar, sedan störst SEK-påverkan. Ren funktion, inget Streamlit-anrop --
    testbar direkt, se test_analysis_bridge.py."""
    need = df[df["order_qty"] > 0].copy()
    if need.empty:
        return need
    need["order_value_sek"] = need["order_qty"] * need["unit_cost"].fillna(0)
    need["_dos_sort"] = need["dos"].replace([float("inf")], 1e9)
    need = need.sort_values(
        by=["stockout_risk", "_dos_sort", "order_value_sek"],
        ascending=[False, True, False],
    ).drop(columns="_dos_sort")
    return need


def _render_summary(need: pd.DataFrame) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Artiklar att beställa", len(need))
    col2.metric("Varav stockout-risk", int(need["stockout_risk"].sum()))
    col3.metric("Totalt ordervärde", _sek(need["order_value_sek"].sum()))


def _render_by_supplier(need: pd.DataFrame) -> None:
    if "supplier" not in need.columns or need["supplier"].isna().all():
        return
    st.subheader("Per leverantör")
    grouped = (
        need.assign(supplier=need["supplier"].fillna("(okänd leverantör)"))
        .groupby("supplier")
        .agg(skus=("sku", "count"), order_value_sek=("order_value_sek", "sum"))
        .reset_index()
        .sort_values("order_value_sek", ascending=False)
    )
    st.dataframe(rename_columns(grouped), width="stretch", hide_index=True)


def _render_list(need: pd.DataFrame) -> None:
    st.subheader("Föreslagna beställningar")
    st.caption(
        "Sorterat efter brådska: stockout-risk först, sedan minst lagerdagar "
        "kvar, sedan störst ordervärde."
    )
    cols = [
        "sku", "description", "supplier", "status", "stock_qty", "safety_stock",
        "rop", "order_qty", "order_value_sek", "lead_time_used", "dos",
    ]
    cols = [c for c in cols if c in need.columns]
    table = need[cols].copy()
    table["status"] = table["status"].map(STATUS_LABELS).fillna(table["status"])
    table["dos"] = table["dos"].replace([float("inf")], None)
    st.dataframe(rename_columns(table), width="stretch", hide_index=True)
    excel_download_button(rename_columns(table), "paafyllningslista.xlsx", key="export_reorder")


def render(user: auth.User) -> None:
    st.title("Påfyllning")
    conn = db.get_tenant_conn(user.company_slug)
    try:
        df, _note = build_canonical(conn)
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

        df, _bridge = run_analysis(df)
        need = reorder_df(df)

        if need.empty:
            st.success("Inget behöver beställas just nu — alla artiklar har tillräckligt saldo.")
            return

        _render_summary(need)
        st.divider()
        _render_by_supplier(need)
        st.divider()
        _render_list(need)
    finally:
        conn.close()
