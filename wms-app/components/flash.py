"""One-shot success/error message that survives a st.rerun().

st.success()/st.error() calls made right before st.rerun() are wiped by the
rerun before the user ever sees them -- every scan-confirm-rerun flow
(receive, pick) needs to show the result of the PREVIOUS action after the
rerun, so the message is stashed in session_state and rendered once on the
next run instead.
"""

from __future__ import annotations

import streamlit as st

_KEY = "_flash"


def flash(message: str, kind: str = "success") -> None:
    st.session_state[_KEY] = (kind, message)


def render_flash() -> None:
    entry = st.session_state.pop(_KEY, None)
    if not entry:
        return
    kind, message = entry
    getattr(st, kind)(message)
