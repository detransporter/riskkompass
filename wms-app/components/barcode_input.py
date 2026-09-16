"""Shared scan-input widget for receive.py and pick.py.

No camera code. A USB/Bluetooth barcode scanner behaves like a keyboard: it
types the encoded value into whatever field has focus and sends Enter. A
single-widget st.form already submits on Enter in Streamlit, so this needs
no JS glue -- point the scanner at the field, physically scan, done. The
button exists for the fallback case of typing a SKU by hand.
"""

from __future__ import annotations

import streamlit as st


def barcode_scan_form(form_key: str, label: str = "Skanna streckkod eller ange SKU") -> str | None:
    """Renders a scan-input form. Returns the scanned/typed code (stripped),
    or None if nothing was submitted this run."""
    with st.form(form_key, clear_on_submit=True):
        code = st.text_input(label, key=f"{form_key}_input")
        submitted = st.form_submit_button("Sök")
    if submitted and code.strip():
        return code.strip()
    return None
