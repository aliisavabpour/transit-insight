"""Shared sidebar navigation copy (informational; primary nav is Streamlit pages)."""
from __future__ import annotations

import streamlit as st


def render_app_nav(current: str = "overview") -> None:
    st.caption("Pages: **Home** · **Realtime** · **Reliability**")
