"""
Realtime Vehicle Positions — latest GPS ping per vehicle on a map.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils.real_data import (
    load_realtime_positions,
    load_realtime_route_summary,
    cache_scope,
    parquet_available,
    snapshot_source_caption,
)
from utils.agency_config import SHARED_ANALYSIS_LABEL, AGENCIES
from utils.agency_loader import get_current_agency_id
from utils.parquet_date import render_agency_sidebar
from components.page_guard import require_active_agency

st.set_page_config(page_title="Realtime Positions | Transit Insight", layout="wide")
render_agency_sidebar()
require_active_agency()

_agency = AGENCIES[get_current_agency_id()]
st.title("Realtime Vehicle Positions")
st.markdown(
    f"Latest GPS ping per vehicle · **{_agency['short_name']}** · {snapshot_source_caption()}. "
    f"Shared May window: **{SHARED_ANALYSIS_LABEL}**."
)
st.markdown("---")


with st.sidebar:
    st.header("Filters")

    if not parquet_available():
        st.error("Parquet not found for this agency/day.")
        st.stop()

    _scope = cache_scope()
    summary = load_realtime_route_summary(_scope)
    route_options = summary["route_id"].astype(str).tolist()
    route_labels = dict(zip(route_options, summary["route_name"].astype(str)))
    display_opts = [f"{route_labels[r]} ({r})" for r in route_options]

    selected_display = st.multiselect(
        "Routes", display_opts,
        default=display_opts[:10],
    )
    selected_ids = [r for r in route_options if f"{route_labels[r]} ({r})" in selected_display]

    show_table = st.checkbox("Show data table", value=False)


if not selected_ids:
    st.info("Select at least one route in the sidebar.")
    st.stop()

with st.spinner("Loading vehicle positions…"):
    frames = []
    for rid in selected_ids:
        df = load_realtime_positions(rid, True, _scope)
        if not df.empty:
            frames.append(df)

all_pos = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

if not all_pos.empty:
    name_map = dict(zip(summary["route_id"].astype(str), summary["route_name"].astype(str)))
    all_pos["route_name"] = all_pos["route_id"].astype(str).map(name_map).fillna("Unknown")
    all_pos["label"] = all_pos["route_id"].astype(str) + " " + all_pos["route_name"]


c1, c2, c3 = st.columns(3)
c1.metric("Vehicles on map", len(all_pos))
_eff = all_pos["effective_speed_kmh"].dropna() if not all_pos.empty else pd.Series(dtype=float)
c2.metric(
    "Avg Speed (km/h)",
    f"{_eff.mean():.1f}" if not _eff.empty else ("N/A" if not all_pos.empty else "—"),
)
c3.metric("Routes shown", len(selected_ids))

st.markdown("---")
st.subheader("Vehicle Map — Latest Ping per Vehicle")

if not all_pos.empty:
    map_center = {
        "lat": float(all_pos["latitude"].mean()),
        "lon": float(all_pos["longitude"].mean()),
    }
    fig_map = px.scatter_mapbox(
        all_pos,
        lat="latitude",
        lon="longitude",
        color="label",
        hover_name="vehicle_id",
        hover_data={
            "effective_speed_kmh": True,
            "bearing": True,
            "timestamp": True,
            "latitude": False,
            "longitude": False,
            "label": False,
            "speed_kmh": False,
        },
        zoom=11,
        center=map_center,
        mapbox_style="carto-darkmatter",
    )
    fig_map.update_traces(marker=dict(size=7, opacity=0.85))
    fig_map.update_layout(
        showlegend=True,
        legend_title_text="Route",
        height=520,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="#0D1117",
        font_color="#E6EDF3",
        legend=dict(bgcolor="#161B22"),
    )
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.warning("No vehicle data for selected routes.")

st.subheader("Speed Distribution")
if not all_pos.empty:
    speed_plot = all_pos["effective_speed_kmh"].dropna()
    if speed_plot.empty:
        st.info("No valid speed samples for selected routes (derived speed unavailable).")
    else:
        fig_hist = px.histogram(
            speed_plot,
            nbins=40,
            color_discrete_sequence=["#E53935"],
            labels={"value": "Speed (km/h)"},
        )
        fig_hist.update_layout(
            paper_bgcolor="#161B22",
            plot_bgcolor="#161B22",
            font_color="#E6EDF3",
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Speed (km/h)",
        )
        st.plotly_chart(fig_hist, use_container_width=True)

st.markdown("---")
st.subheader("Route Summary (all routes in dataset)")
disp = summary.rename(
    columns={
        "route_id": "Route ID",
        "route_name": "Name",
        "records": "Pings",
        "vehicles": "Vehicles",
        "effective_avg_speed_kmh": "Avg Speed (km/h)",
        "effective_max_speed_kmh": "Max Speed (km/h)",
        "first_seen": "First Seen",
        "last_seen": "Last Seen",
    }
)
disp_cols = [
    "Route ID", "Name", "Pings", "Vehicles",
    "Avg Speed (km/h)", "Max Speed (km/h)", "First Seen", "Last Seen",
]
st.dataframe(disp[[c for c in disp_cols if c in disp.columns]], use_container_width=True, hide_index=True)

if show_table and not all_pos.empty:
    st.subheader("Raw Position Data")
    _raw = all_pos[
        [
            "vehicle_id",
            "route_id",
            "route_name",
            "latitude",
            "longitude",
            "effective_speed_kmh",
            "bearing",
            "timestamp",
        ]
    ].rename(columns={"effective_speed_kmh": "speed_kmh"})
    st.dataframe(_raw, use_container_width=True, hide_index=True)
