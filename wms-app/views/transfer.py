"""Lagerflytt: flytta en artikel mellan två lagerplatser, oberoende av
mottagning. Samma "skanna -> bekräfta"-flöde som receive.py och pick.py.

Detta är samma mekanik som receive.py redan använder internt (txn_type
'putaway', from_location -> to_location) -- den funktionen fanns redan i
db.record_transaction, bara inte exponerad som ett fristående verktyg för
omplacering/cykelräkningskorrigeringar som inte har med en mottagning att
göra.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import auth
import db
from components.barcode_input import barcode_scan_form
from components.flash import flash, render_flash
from components.sv import rename_columns

_PENDING_KEY = "transfer_pending"


def _stock_by_location(conn: sqlite3.Connection, sku: str) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT location_code, qty FROM stock WHERE sku = ? AND qty > 0 ORDER BY location_code",
        conn, params=(sku,),
    )


def _locations(conn: sqlite3.Connection) -> list[str]:
    return [r["code"] for r in conn.execute("SELECT code FROM locations ORDER BY code").fetchall()]


def _items_with_stock(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT DISTINCT i.sku, i.description FROM items i "
        "JOIN stock s ON s.sku = i.sku WHERE s.qty > 0 ORDER BY i.sku"
    ).fetchall()


def _render_scan_step(conn: sqlite3.Connection) -> None:
    st.subheader("1. Välj artikel")
    code = barcode_scan_form("transfer_scan")
    if code is not None:
        item = db.find_item_by_code(conn, code)
        if item is None:
            st.error(f"Ingen artikel hittades för '{code}'.")
            return
        st.session_state[_PENDING_KEY] = {"sku": item["sku"], "description": item["description"]}
        st.rerun()

    items = _items_with_stock(conn)
    if not items:
        return
    st.caption("Eller välj manuellt ur listan, utan att skriva SKU:")
    options = {f"{r['sku']} — {r['description'] or '(ingen beskrivning)'}": r["sku"] for r in items}
    label = st.selectbox("Artikel", list(options.keys()), key="transfer_manual_select")
    if st.button("Välj artikel"):
        row = next(r for r in items if r["sku"] == options[label])
        st.session_state[_PENDING_KEY] = {"sku": row["sku"], "description": row["description"]}
        st.rerun()


def _render_confirm_step(conn: sqlite3.Connection, user: auth.User) -> None:
    pending = st.session_state[_PENDING_KEY]
    sku = pending["sku"]
    st.subheader("2. Bekräfta flytt")
    st.info(f"**{sku}** — {pending['description'] or '(ingen beskrivning)'}")

    stock_df = _stock_by_location(conn, sku)
    if stock_df.empty:
        st.warning(f"{sku} har inget saldo på någon plats — inget att flytta.")
        if st.button("Avbryt"):
            del st.session_state[_PENDING_KEY]
            st.rerun()
        return

    st.dataframe(rename_columns(stock_df), width="stretch", hide_index=True)

    from_locations = stock_df["location_code"].tolist()
    all_locations = _locations(conn)

    with st.form("transfer_confirm"):
        col1, col2 = st.columns(2)
        from_location = col1.selectbox("Från plats", from_locations)
        to_location = col2.selectbox("Till plats", all_locations)
        qty = st.number_input("Mängd", min_value=0.0, step=1.0, value=1.0)
        reference = st.text_input("Referens/anledning (valfritt)", placeholder="t.ex. omplacering, inventering")
        col_confirm, col_cancel = st.columns(2)
        confirmed = col_confirm.form_submit_button("Bekräfta flytt", type="primary")
        cancelled = col_cancel.form_submit_button("Avbryt")

    if cancelled:
        del st.session_state[_PENDING_KEY]
        st.rerun()

    if confirmed:
        if qty <= 0:
            st.error("Mängden måste vara större än noll.")
            return
        if from_location == to_location:
            st.error("Från- och till-plats kan inte vara samma.")
            return
        try:
            db.record_transaction(
                conn, "putaway", sku, qty,
                from_location=from_location, to_location=to_location,
                reference=reference or None, user_email=user.email,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        conn.commit()
        del st.session_state[_PENDING_KEY]
        flash(f"Flyttat: {qty:g} st {sku} från {from_location} till {to_location}.")
        st.rerun()


def render(user: auth.User) -> None:
    st.title("Flytta")
    render_flash()

    conn = db.get_tenant_conn(user.company_slug)
    try:
        has_stock = conn.execute("SELECT 1 FROM stock WHERE qty > 0 LIMIT 1").fetchone() is not None
        if not has_stock:
            st.info("Inget saldo att flytta ännu. Ta emot något under 'Ta emot' först.")
            return

        if _PENDING_KEY in st.session_state:
            _render_confirm_step(conn, user)
        else:
            _render_scan_step(conn)
    finally:
        conn.close()
