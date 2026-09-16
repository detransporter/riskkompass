"""Mottagning: scan/type an item, confirm qty + location(s).

Combined receive+putaway in one operator action per plan (byggordning steg 2).
If the operator picks the same location for "mottagningsplats" and "slutlig
lagerplats" (the common case for a small warehouse with no separate dock),
only a single `receive` transaction is recorded -- a putaway from a location
to itself would net to zero stock change but still add a confusing extra log
row, so it is skipped rather than recorded as a no-op.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

import auth
import db
from components.barcode_input import barcode_scan_form
from components.flash import flash, render_flash

_PENDING_KEY = "receive_pending"


def _locations(conn: sqlite3.Connection) -> list[str]:
    return [r["code"] for r in conn.execute("SELECT code FROM locations ORDER BY code").fetchall()]


def _render_scan_step(conn: sqlite3.Connection) -> None:
    st.subheader("1. Skanna artikel")
    code = barcode_scan_form("receive_scan")
    if code is None:
        return
    item = db.find_item_by_code(conn, code)
    if item is None:
        st.error(f"Ingen artikel hittades för '{code}'.")
        return
    st.session_state[_PENDING_KEY] = {"sku": item["sku"], "description": item["description"]}
    st.rerun()


def _render_confirm_step(conn: sqlite3.Connection, user: auth.User) -> None:
    pending = st.session_state[_PENDING_KEY]
    st.subheader("2. Bekräfta mottagning")
    st.info(f"**{pending['sku']}** — {pending['description'] or '(ingen beskrivning)'}")

    locations = _locations(conn)
    with st.form("receive_confirm"):
        qty = st.number_input("Mängd", min_value=0.0, step=1.0, value=1.0)
        col1, col2 = st.columns(2)
        dock = col1.selectbox("Mottagningsplats", locations)
        putaway_location = col2.selectbox("Slutlig lagerplats", locations)
        reference = st.text_input("Referens (PO-nummer, valfritt)")
        col_confirm, col_cancel = st.columns(2)
        confirmed = col_confirm.form_submit_button("Bekräfta mottagning", type="primary")
        cancelled = col_cancel.form_submit_button("Avbryt")

    if cancelled:
        del st.session_state[_PENDING_KEY]
        st.rerun()

    if confirmed:
        if qty <= 0:
            st.error("Mängden måste vara större än noll.")
            return
        sku = pending["sku"]
        db.record_transaction(
            conn, "receive", sku, qty,
            to_location=dock, reference=reference or None, user_email=user.email,
        )
        if putaway_location != dock:
            db.record_transaction(
                conn, "putaway", sku, qty,
                from_location=dock, to_location=putaway_location,
                reference=reference or None, user_email=user.email,
            )
        conn.commit()
        del st.session_state[_PENDING_KEY]
        flash(f"Mottaget: {qty:g} st {sku} till {putaway_location}.")
        st.rerun()


def render(user: auth.User) -> None:
    st.title("Ta emot")
    render_flash()

    conn = db.get_tenant_conn(user.company_slug)
    try:
        has_items = conn.execute("SELECT 1 FROM items LIMIT 1").fetchone() is not None
        has_locations = conn.execute("SELECT 1 FROM locations LIMIT 1").fetchone() is not None
        if not has_items or not has_locations:
            st.info("Lägg till minst en artikel och en lagerplats under 'Artiklar & platser' först.")
            return

        if _PENDING_KEY in st.session_state:
            _render_confirm_step(conn, user)
        else:
            _render_scan_step(conn)
    finally:
        conn.close()
