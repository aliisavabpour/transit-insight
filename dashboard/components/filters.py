"""Sidebar filter widgets shared across pages."""
import streamlit as st
import pandas as pd
from utils.db import get_connection


@st.cache_data(ttl=300)
def _get_route_options() -> list[tuple[str, str]]:
    con = get_connection()
    df = con.execute(
        "SELECT route_id, route_short_name FROM routes ORDER BY route_short_name"
    ).df()
    con.close()
    return [(row.route_id, row.route_short_name) for row in df.itertuples()]


def route_multiselect(label: str = "Routes", default_all: bool = True) -> list[str]:
    options = _get_route_options()
    if not options:
        st.sidebar.warning("No routes loaded yet.")
        return []
    ids = [o[0] for o in options]
    labels = {o[0]: o[1] for o in options}
    display = [f"{labels[i]} ({i})" for i in ids]
    default = display if default_all else []
    selected_display = st.sidebar.multiselect(label, display, default=default)
    selected_ids = [ids[display.index(d)] for d in selected_display]
    return selected_ids


def agency_route_selectbox(label: str = "Route") -> str | None:
    """Selectbox for configured or auto-discovered network routes for the active agency."""
    from utils.agency_loader import get_current_agency_id
    from utils.route_config import get_network_routes_for_agency

    routes = get_network_routes_for_agency(get_current_agency_id())
    if not routes:
        st.sidebar.warning("No routes available for network detail view.")
        return None

    ids = sorted(routes.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
    labels = {rid: routes[rid].get("full_name", rid) for rid in ids}
    display = [f"{labels[i]} ({i})" for i in ids]
    chosen = st.sidebar.selectbox(label, display)
    return ids[display.index(chosen)]


def ttc_route_selectbox(label: str = "Route") -> str | None:
    """Backward-compatible alias."""
    return agency_route_selectbox(label)


def route_selectbox(label: str = "Route") -> str | None:
    options = _get_route_options()
    if not options:
        st.sidebar.warning("No routes loaded yet.")
        return None
    ids = [o[0] for o in options]
    labels = {o[0]: o[1] for o in options}
    display = [f"{labels[i]} ({i})" for i in ids]
    chosen = st.sidebar.selectbox(label, display)
    return ids[display.index(chosen)]


def hour_range_slider(label: str = "Hour of day") -> tuple[int, int]:
    return st.sidebar.slider(label, min_value=0, max_value=23, value=(6, 22))


def date_filter() -> pd.Timestamp:
    return st.sidebar.date_input("Date", value=pd.Timestamp.today())
