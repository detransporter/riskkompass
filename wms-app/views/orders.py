"""Utleveransordrar: skapa order, lägg till rader, se status.

order_no is free text (David's call, not app-generated) -- it usually mirrors
a number already assigned in Fortnox or the customer's own ERP, and forcing
a second parallel numbering scheme would just create a mapping problem.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import auth
import db


def _open_orders(conn: sqlite3.Connection) -> list[str]:
    return [
        r["order_no"] for r in conn.execute(
            "SELECT order_no FROM orders WHERE order_type = 'outbound' "
            "AND status IN ('open', 'picking') ORDER BY created_at DESC"
        ).fetchall()
    ]


def _next_line_no(conn: sqlite3.Connection, order_no: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(line_no), 0) AS n FROM order_lines WHERE order_no = ?", (order_no,)
    ).fetchone()
    return row["n"] + 1


def _suggest_location(conn: sqlite3.Connection, sku: str) -> str | None:
    row = conn.execute(
        "SELECT location_code FROM stock WHERE sku = ? AND qty > 0 ORDER BY qty DESC LIMIT 1",
        (sku,),
    ).fetchone()
    return row["location_code"] if row else None


def _render_create_tab(conn: sqlite3.Connection) -> None:
    st.subheader("Skapa order")
    with st.form("create_order_form", clear_on_submit=True):
        order_no = st.text_input("Ordernummer *")
        reference = st.text_input("Kundreferens (valfritt)")
        submitted = st.form_submit_button("Skapa order")

    if submitted:
        if not order_no.strip():
            st.error("Ordernummer krävs.")
        else:
            try:
                conn.execute(
                    "INSERT INTO orders (order_no, order_type, status, reference, created_at) "
                    "VALUES (?, 'outbound', 'open', ?, ?)",
                    (order_no.strip(), reference.strip() or None, db.now_iso()),
                )
                conn.commit()
                st.success(f"Order {order_no} skapad.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error(f"Ordernummer {order_no} finns redan.")


def _render_lines_tab(conn: sqlite3.Connection) -> None:
    st.subheader("Lägg till orderrader")
    orders = _open_orders(conn)
    skus = [r["sku"] for r in conn.execute("SELECT sku FROM items ORDER BY sku").fetchall()]

    if not orders:
        st.info("Inga öppna ordrar. Skapa en order under fliken 'Skapa order' först.")
        return
    if not skus:
        st.info("Inga artiklar. Lägg till artiklar under 'Artiklar & platser' först.")
        return

    order_no = st.selectbox("Order", orders)

    with st.form("add_line_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        sku = col1.selectbox("SKU", skus)
        qty_ordered = col2.number_input("Antal", min_value=0.0, step=1.0, value=1.0)
        submitted = st.form_submit_button("Lägg till rad")

    if submitted:
        if qty_ordered <= 0:
            st.error("Antal måste vara större än noll.")
        else:
            line_no = _next_line_no(conn, order_no)
            location_code = _suggest_location(conn, sku)
            conn.execute(
                "INSERT INTO order_lines (order_no, line_no, sku, qty_ordered, location_code) "
                "VALUES (?, ?, ?, ?, ?)",
                (order_no, line_no, sku, qty_ordered, location_code),
            )
            conn.commit()
            st.success(f"Rad {line_no} ({sku} x{qty_ordered:g}) tillagd på {order_no}.")
            st.rerun()

    st.divider()
    st.subheader(f"Rader på {order_no}")
    lines = pd.read_sql(
        "SELECT ol.line_no, ol.sku, i.description, ol.qty_ordered, ol.qty_done, ol.location_code "
        "FROM order_lines ol JOIN items i ON i.sku = ol.sku "
        "WHERE ol.order_no = ? ORDER BY ol.location_code, ol.line_no",
        conn, params=(order_no,),
    )
    st.dataframe(lines, width="stretch", hide_index=True)


def _render_all_orders_tab(conn: sqlite3.Connection) -> None:
    st.subheader("Alla utleveransordrar")
    df = pd.read_sql(
        "SELECT order_no, status, reference, created_at FROM orders "
        "WHERE order_type = 'outbound' ORDER BY created_at DESC",
        conn,
    )
    st.dataframe(df, width="stretch", hide_index=True)

    packed = df.loc[df["status"] == "packed", "order_no"].tolist() if not df.empty else []
    if packed:
        st.divider()
        st.subheader("Markera som skickad")
        order_no = st.selectbox("Packad order", packed, key="ship_select")
        if st.button("Markera som skickad"):
            conn.execute(
                "UPDATE orders SET status = 'shipped' WHERE order_no = ?", (order_no,)
            )
            conn.commit()
            st.success(f"{order_no} markerad som skickad.")
            st.rerun()


def render(user: auth.User) -> None:
    st.title("Ordrar")
    conn = db.get_tenant_conn(user.company_slug)
    try:
        tab_create, tab_lines, tab_all = st.tabs(["Skapa order", "Orderrader", "Alla ordrar"])
        with tab_create:
            _render_create_tab(conn)
        with tab_lines:
            _render_lines_tab(conn)
        with tab_all:
            _render_all_orders_tab(conn)
    finally:
        conn.close()
