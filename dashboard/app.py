"""
Transit Insight — entrypoint with explicit navigation (Home, Realtime, Reliability).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

st.set_page_config(
    page_title="Transit Insight — GTFS-RT Analytics",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

home = st.Page("home_page.py", title="Home", default=True, icon="🏠")
realtime = st.Page("pages/01_Realtime.py", title="Realtime")
reliability = st.Page("pages/03_Reliability.py", title="Reliability")

pg = st.navigation([home, realtime, reliability])
pg.run()
