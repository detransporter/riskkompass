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
from components.i18n import get_lang, language_switcher, t
from views import items as page_items
from views import import_data as page_import
from views import stock as page_stock
from views import receive as page_receive
from views import transfer as page_transfer
from views import orders as page_orders
from views import pick as page_pick
from views import reorder as page_reorder
from views import iha_report as page_iha_report
from views import forecast_demo as page_forecast_demo

st.set_page_config(page_title="WMS", page_icon="📦", layout="wide")

db.init_directory_db()

# Keyed by a stable id, not the display label -- the label is looked up
# through t() at render time so switching language doesn't need to touch
# which module st.radio's selection maps to.
PAGES = {
    "items": page_items,
    "import": page_import,
    "stock": page_stock,
    "receive": page_receive,
    "transfer": page_transfer,
    "orders": page_orders,
    "pick": page_pick,
    "reorder": page_reorder,
    "iha": page_iha_report,
    "forecast_demo": page_forecast_demo,
}


def _login_register_screen() -> None:
    language_switcher()
    st.title(t("app.brand"))
    tab_login, tab_register = st.tabs([t("app.login_tab"), t("app.register_tab")])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input(t("app.email_label"))
            password = st.text_input(t("app.password_label"), type="password")
            submitted = st.form_submit_button(t("app.login_button"))
        if submitted:
            user, error = auth.login(email, password, lang=get_lang())
            if error:
                st.error(error)
            else:
                st.session_state["user"] = user
                st.rerun()

    with tab_register:
        with st.form("register_form"):
            company_name = st.text_input(t("app.company_name_label"))
            reg_email = st.text_input(t("app.email_label"), key="reg_email")
            reg_password = st.text_input(
                t("app.password_register_label"), type="password", key="reg_password",
            )
            reg_submitted = st.form_submit_button(t("app.register_button"))
        if reg_submitted:
            if not company_name.strip():
                st.error(t("app.company_name_required_error"))
            else:
                user, error = auth.register_company(
                    company_name, reg_email, reg_password, lang=get_lang(),
                )
                if error:
                    st.error(error)
                else:
                    st.session_state["user"] = user
                    st.success(t("app.register_success", name=user.company_name))
                    st.rerun()


def _app_screen(user: auth.User) -> None:
    with st.sidebar:
        st.markdown(f"**{user.company_name}**")
        st.caption(user.email)
        language_switcher()

        # current_page_id is *our* source of truth, independent of whatever
        # Streamlit does internally with the radio widget's own state. The
        # widget's key is deliberately re-derived from (language, current
        # page): even index-based options weren't enough to keep the visual
        # selection in sync after a language switch (reproduced live --
        # the correct page still rendered, but no radio circle showed as
        # selected). Changing the key forces Streamlit to treat it as a
        # brand-new widget on every language switch or page change, which
        # always honors the explicit index= we pass instead of trying to
        # reconcile stale frontend state against newly-translated labels.
        page_ids = list(PAGES.keys())
        lang = get_lang()
        current = st.session_state.get("current_page_id", page_ids[0])
        current_idx = page_ids.index(current) if current in page_ids else 0
        selected_idx = st.radio(
            t("app.menu_label"), range(len(page_ids)), index=current_idx,
            format_func=lambda i: t(f"nav.{page_ids[i]}"),
            label_visibility="collapsed", key=f"nav_radio_{lang}_{current}",
        )
        page_id = page_ids[selected_idx]
        st.session_state["current_page_id"] = page_id
        st.divider()
        if st.button(t("app.logout_button")):
            del st.session_state["user"]
            st.rerun()

    PAGES[page_id].render(user)


def main() -> None:
    user = st.session_state.get("user")
    if user is None:
        _login_register_screen()
    else:
        _app_screen(user)


if __name__ == "__main__":
    main()
