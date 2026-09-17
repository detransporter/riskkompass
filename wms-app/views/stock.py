"""Live stock balances + manual adjustment.

Manual adjustment exists here (not just via receive/pick flows added in
milestone 2) because a WMS always needs a way to correct a count without
faking a fictional receipt or pick -- it goes through db.record_transaction
with txn_type='adjust' so it lands in the same audit log the IHA analysis
reads, same as every other movement.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
from components.export import excel_download_button
from components.sv import rename_columns


def _stock_df(conn) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT s.sku, i.description, s.location_code, l.zone, s.qty
        FROM stock s
        JOIN items i ON i.sku = s.sku
        JOIN locations l ON l.code = s.location_code
        WHERE s.qty > 0
        ORDER BY s.sku, s.location_code
        """,
        conn,
    )


def _skus(conn) -> list[str]:
    return [r["sku"] for r in conn.execute("SELECT sku FROM items ORDER BY sku").fetchall()]


def _locations(conn) -> list[str]:
    return [r["code"] for r in conn.execute("SELECT code FROM locations ORDER BY code").fetchall()]


def _render_adjust_form(conn, user: auth.User) -> None:
    st.subheader("Saldojustering")
    skus = _skus(conn)
    locations = _locations(conn)
    if not skus or not locations:
        st.info("Lägg till minst en artikel och en lagerplats under 'Artiklar & platser' först.")
        return

    with st.form("adjust_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        sku = col1.selectbox("SKU", skus)
        location_code = col2.selectbox("Plats", locations)
        delta = col3.number_input(
            "Ändring (+/-)", step=1.0,
            help="Positivt tal ökar saldot, negativt minskar det.",
        )
        reference = st.text_input("Referens/anledning (valfritt)")
        submitted = st.form_submit_button("Justera saldo")

    if submitted:
        if delta == 0:
            st.error("Ange en ändring skild från noll.")
            return
        try:
            db.record_transaction(
                conn, "adjust", sku, delta,
                to_location=location_code, reference=reference or None,
                user_email=user.email,
            )
            conn.commit()
            st.success(f"Saldo för {sku} vid {location_code} justerat med {delta:+g}.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def render(user: auth.User) -> None:
    st.title("Lagersaldo")
    conn = db.get_tenant_conn(user.company_slug)
    try:
        df = _stock_df(conn)
        if df.empty:
            st.info("Inget saldo registrerat ännu.")
        else:
            totals = df.groupby(["sku", "description"], as_index=False)["qty"].sum()
            totals = totals.rename(columns={"qty": "totalt_saldo"})
            st.subheader("Totalt per artikel")
            st.dataframe(rename_columns(totals), width="stretch", hide_index=True)
            excel_download_button(rename_columns(totals), "lagersaldo_totalt.xlsx", key="export_totals")

            st.subheader("Per lagerplats")
            st.dataframe(rename_columns(df), width="stretch", hide_index=True)
            excel_download_button(rename_columns(df), "lagersaldo_per_plats.xlsx", key="export_per_location")

        st.divider()
        _render_adjust_form(conn, user)
    finally:
        conn.close()
