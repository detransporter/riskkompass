"""Orderplock: plocklista sorterad på platskod, skanna-bekräfta per rad.

Two-step scan flow (scan -> confirm qty), same shape as receive.py: a scan
only ever identifies WHICH order line it matches, it never moves stock by
itself -- the operator always confirms a quantity before db.record_transaction
runs, so a mis-scan can't silently move the wrong amount.
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

_PENDING_KEY = "pick_pending"


def _pickable_orders(conn: sqlite3.Connection) -> list[str]:
    return [
        r["order_no"] for r in conn.execute(
            "SELECT order_no FROM orders WHERE order_type = 'outbound' "
            "AND status IN ('open', 'picking') ORDER BY created_at"
        ).fetchall()
    ]


def _pick_list(conn: sqlite3.Connection, order_no: str) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT ol.line_no, ol.sku, i.description, ol.location_code,
               ol.qty_ordered, ol.qty_done,
               (ol.qty_ordered - ol.qty_done) AS remaining
        FROM order_lines ol JOIN items i ON i.sku = ol.sku
        WHERE ol.order_no = ?
        ORDER BY ol.location_code, ol.line_no
        """,
        conn, params=(order_no,),
    )


def _find_open_line(conn: sqlite3.Connection, order_no: str, sku: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT line_no, sku, location_code, qty_ordered, qty_done
        FROM order_lines
        WHERE order_no = ? AND sku = ? AND qty_done < qty_ordered
        ORDER BY location_code, line_no LIMIT 1
        """,
        (order_no, sku),
    ).fetchone()


def _advance_order_status(conn: sqlite3.Connection, order_no: str) -> None:
    conn.execute(
        "UPDATE orders SET status = 'picking' WHERE order_no = ? AND status = 'open'",
        (order_no,),
    )
    remaining = conn.execute(
        "SELECT COALESCE(SUM(qty_ordered - qty_done), 0) AS r FROM order_lines WHERE order_no = ?",
        (order_no,),
    ).fetchone()["r"]
    if remaining <= 0:
        conn.execute("UPDATE orders SET status = 'packed' WHERE order_no = ?", (order_no,))


def _render_scan_step(conn: sqlite3.Connection, order_no: str) -> None:
    st.subheader("Skanna nästa artikel")
    code = barcode_scan_form("pick_scan")
    if code is None:
        return
    item = db.find_item_by_code(conn, code)
    if item is None:
        st.error(f"Ingen artikel hittades för '{code}'.")
        return
    line = _find_open_line(conn, order_no, item["sku"])
    if line is None:
        st.error(f"{item['sku']} finns inte kvar att plocka på denna order.")
        return
    st.session_state[_PENDING_KEY] = {
        "order_no": order_no,
        "line_no": line["line_no"],
        "sku": line["sku"],
        "location_code": line["location_code"],
        "remaining": line["qty_ordered"] - line["qty_done"],
    }
    st.rerun()


def _render_confirm_step(conn: sqlite3.Connection, user: auth.User) -> None:
    pending = st.session_state[_PENDING_KEY]
    st.subheader("Bekräfta plock")
    st.info(
        f"**{pending['sku']}** vid **{pending['location_code']}** — "
        f"kvar att plocka: {pending['remaining']:g}"
    )

    with st.form("pick_confirm"):
        qty = st.number_input(
            "Plockad mängd", min_value=0.0, step=1.0, value=float(pending["remaining"])
        )
        col_confirm, col_cancel = st.columns(2)
        confirmed = col_confirm.form_submit_button("Bekräfta plock", type="primary")
        cancelled = col_cancel.form_submit_button("Avbryt")

    if cancelled:
        del st.session_state[_PENDING_KEY]
        st.rerun()

    if confirmed:
        if qty <= 0:
            st.error("Mängden måste vara större än noll.")
            return
        if qty > pending["remaining"]:
            st.error(f"Kan inte plocka mer än kvarstående {pending['remaining']:g}.")
            return
        try:
            db.record_transaction(
                conn, "pick", pending["sku"], qty,
                from_location=pending["location_code"],
                reference=pending["order_no"], user_email=user.email,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        conn.execute(
            "UPDATE order_lines SET qty_done = qty_done + ? WHERE order_no = ? AND line_no = ?",
            (qty, pending["order_no"], pending["line_no"]),
        )
        _advance_order_status(conn, pending["order_no"])
        conn.commit()
        sku = pending["sku"]
        del st.session_state[_PENDING_KEY]
        flash(f"Plockat: {qty:g} st {sku}.")
        st.rerun()


def render(user: auth.User) -> None:
    st.title("Plocka")
    render_flash()

    conn = db.get_tenant_conn(user.company_slug)
    try:
        orders = _pickable_orders(conn)
        if not orders:
            st.info("Inga ordrar att plocka. Skapa en order under 'Ordrar' först.")
            return

        order_no = st.selectbox("Order", orders)
        st.dataframe(rename_columns(_pick_list(conn, order_no)), width="stretch", hide_index=True)
        st.divider()

        if _PENDING_KEY in st.session_state and st.session_state[_PENDING_KEY]["order_no"] == order_no:
            _render_confirm_step(conn, user)
        else:
            st.session_state.pop(_PENDING_KEY, None)
            _render_scan_step(conn, order_no)
    finally:
        conn.close()
