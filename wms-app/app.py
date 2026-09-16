"""WMS-app -- own router, same pattern as iha-defense/app/streamlit_app.py.

views/ modules are imported and called directly (render(user)), not
Streamlit's automatic pages/ directory convention. The directory is
deliberately NOT named "pages" -- Streamlit auto-populates a native sidebar
nav from any folder with that exact name next to the entry script, which
would duplicate the radio nav below (confirmed locally: renaming pages/ to
views/ was the fix, kept in views/ from the start here).
"""

from __future__ import annotations

import streamlit as st

import auth
import db
from views import items as page_items
from views import stock as page_stock
from views import receive as page_receive
from views import orders as page_orders
from views import pick as page_pick
from views import iha_report as page_iha_report

st.set_page_config(page_title="WMS", page_icon="📦", layout="wide")

db.init_directory_db()

PAGES = {
    "Artiklar & platser": page_items,
    "Lagersaldo": page_stock,
    "Ta emot": page_receive,
    "Ordrar": page_orders,
    "Plocka": page_pick,
    "IHA-rapport": page_iha_report,
}


def _login_register_screen() -> None:
    st.title("📦 WMS")
    tab_login, tab_register = st.tabs(["Logga in", "Registrera företag"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("E-post")
            password = st.text_input("Lösenord", type="password")
            submitted = st.form_submit_button("Logga in")
        if submitted:
            user, error = auth.login(email, password)
            if error:
                st.error(error)
            else:
                st.session_state["user"] = user
                st.rerun()

    with tab_register:
        with st.form("register_form"):
            company_name = st.text_input("Företagsnamn")
            reg_email = st.text_input("E-post", key="reg_email")
            reg_password = st.text_input("Lösenord (minst 8 tecken)", type="password", key="reg_password")
            reg_submitted = st.form_submit_button("Skapa konto")
        if reg_submitted:
            if not company_name.strip():
                st.error("Ange ett företagsnamn.")
            else:
                user, error = auth.register_company(company_name, reg_email, reg_password)
                if error:
                    st.error(error)
                else:
                    st.session_state["user"] = user
                    st.success(f"Klart! Databas skapad för {user.company_name}.")
                    st.rerun()


def _app_screen(user: auth.User) -> None:
    with st.sidebar:
        st.markdown(f"**{user.company_name}**")
        st.caption(user.email)
        page_name = st.radio("Meny", list(PAGES.keys()), label_visibility="collapsed")
        st.divider()
        if st.button("Logga ut"):
            del st.session_state["user"]
            st.rerun()

    PAGES[page_name].render(user)


def main() -> None:
    user = st.session_state.get("user")
    if user is None:
        _login_register_screen()
    else:
        _app_screen(user)


if __name__ == "__main__":
    main()
