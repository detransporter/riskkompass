"""Excel export button, shared by every page that shows a table worth
downloading. Same io.BytesIO + st.download_button pattern iha-saas already
uses in pages/results.py and pages/forecast.py -- df.to_excel needs openpyxl
as its engine (see requirements.txt)."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st


def excel_download_button(
    df: pd.DataFrame,
    filename: str,
    label: str = "⬇ Exportera till Excel",
    key: str | None = None,
) -> None:
    if df.empty:
        return
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        label,
        data=buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )
