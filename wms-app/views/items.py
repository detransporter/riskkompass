"""Artikel- och platsmasterdata (CRUD). No transactions here -- this page
only defines what items and locations exist, not how much of anything is
where (see pages/stock.py for balances)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
from components.sv import rename_columns

LOCATION_TYPES = ["receiving", "picking", "bulk"]


def _items_df(conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT sku, barcode, description, unit_cost, currency, supplier, "
        "category, lead_time_days, created_at FROM items ORDER BY sku",
        conn,
    )


def _locations_df(conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT code, zone, location_type FROM locations ORDER BY code", conn
    )


def _render_items_tab(conn) -> None:
    st.subheader("Lägg till artikel")
    with st.form("add_item_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        sku = col1.text_input("SKU *")
        barcode = col2.text_input("Streckkod")
        description = col3.text_input("Beskrivning")

        col4, col5, col6 = st.columns(3)
        unit_cost = col4.number_input("Enhetskostnad", min_value=0.0, step=1.0)
        currency = col5.text_input("Valuta", value="SEK")
        lead_time_days = col6.number_input("Ledtid (dagar)", min_value=0, step=1)

        col7, col8 = st.columns(2)
        supplier = col7.text_input("Leverantör")
        category = col8.text_input("Kategori")

        submitted = st.form_submit_button("Spara artikel")

    if submitted:
        if not sku.strip():
            st.error("SKU krävs.")
        else:
            try:
                conn.execute(
                    """
                    INSERT INTO items
                        (sku, barcode, description, unit_cost, currency, supplier,
                         category, lead_time_days, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sku.strip(), barcode.strip() or None, description.strip() or None,
                        unit_cost or None, currency.strip() or "SEK", supplier.strip() or None,
                        category.strip() or None, int(lead_time_days) if lead_time_days else None,
                        db.now_iso(),
                    ),
                )
                conn.commit()
                st.success(f"Artikel {sku} sparad.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - surface the DB error directly
                st.error(f"Kunde inte spara: {exc}")

    st.divider()
    st.subheader(f"Artiklar")
    df = _items_df(conn)
    st.dataframe(rename_columns(df), width="stretch", hide_index=True)
    st.caption(f"{len(df)} artiklar")


def _render_locations_tab(conn) -> None:
    st.subheader("Lägg till lagerplats")
    with st.form("add_location_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        code = col1.text_input("Platskod * (t.ex. A-01-03)")
        zone = col2.text_input("Zon")
        location_type = col3.selectbox("Typ", LOCATION_TYPES, index=2)
        submitted = st.form_submit_button("Spara plats")

    if submitted:
        if not code.strip():
            st.error("Platskod krävs.")
        else:
            try:
                conn.execute(
                    "INSERT INTO locations (code, zone, location_type) VALUES (?, ?, ?)",
                    (code.strip(), zone.strip() or None, location_type),
                )
                conn.commit()
                st.success(f"Plats {code} sparad.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Kunde inte spara: {exc}")

    st.divider()
    st.subheader("Lagerplatser")
    df = _locations_df(conn)
    st.dataframe(rename_columns(df), width="stretch", hide_index=True)
    st.caption(f"{len(df)} platser")


def render(user: auth.User) -> None:
    st.title("Artiklar & platser")
    conn = db.get_tenant_conn(user.company_slug)
    try:
        tab_items, tab_locations = st.tabs(["Artiklar", "Lagerplatser"])
        with tab_items:
            _render_items_tab(conn)
        with tab_locations:
            _render_locations_tab(conn)
    finally:
        conn.close()
