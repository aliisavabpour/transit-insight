"""
Transit Insight — Home
Fleet overview, architecture summary, and agency status.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from utils.db import init_db
from utils.real_data import (
    parquet_available,
    load_route_summary,
    cache_scope,
    get_parquet_snapshot_info,
    snapshot_source_caption,
)
from utils.parquet_date import render_agency_sidebar
from utils.agency_config import (
    AGENCIES,
    ACTIVE_AGENCY_IDS,
    SHARED_ANALYSIS_LABEL,
    agency_data_available,
    agency_gtfs_available,
    DEFAULT_SNAPSHOT_DATE,
)
from utils.agency_loader import get_current_agency_id


@st.cache_resource
def bootstrap():
    init_db()


bootstrap()

with st.sidebar:
    st.markdown("## Transit Insight")
    st.caption("DuckDB · S3 parquet · shared May 2026 window")
    st.markdown("---")
    render_agency_sidebar()

st.title("Transit Insight")
st.markdown(
    "Multi-agency GTFS-RT analytics with optimized partitioned-parquet querying "
    "and schedule deviation indicators. **TTC**, **TransLink**, and **Edmonton** "
    f"share the same **May analysis window ({SHARED_ANALYSIS_LABEL})**."
)
st.markdown("---")

summary = None
if parquet_available():
    get_parquet_snapshot_info()
    st.caption(snapshot_source_caption())
    try:
        with st.spinner("Loading fleet summary…"):
            summary = load_route_summary(cache_scope())
    except Exception as exc:
        st.error(f"Could not load route summary: {exc}")
        summary = None

    if summary is not None and not summary.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Routes in snapshot", f"{len(summary)}")
        c2.metric(
            "Vehicles counted across routes",
            f"{summary['vehicles'].sum():,}",
            help="Sum of per-route distinct vehicle counts. A vehicle on multiple routes may be counted more than once.",
        )
        c3.metric("GPS pings (24 h)", f"{summary['records'].sum():,}")
        _eff = summary["effective_avg_speed_kmh"].dropna()
        c4.metric(
            "Avg route speed",
            f"{_eff.mean():.1f} km/h" if not _eff.empty else "N/A",
            help="Unweighted mean of each route's average speed (GPS-derived for TransLink). "
            "Not an official agency fleet average.",
        )
        st.caption(
            "Route-summary aggregates from the snapshot — not official agency fleet totals."
        )
        st.markdown("---")

st.subheader("Suggested workflow")
st.markdown(
    """
1. **Reliability** — headway comparison heatmap and per-route deviation charts  
2. **Realtime** — fleet GPS map by route  
3. Expand **Methodology** on Reliability for assumptions and data quality notes  
"""
)

st.markdown("---")
st.subheader("Architecture")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**GTFS-RT layer**")
    st.markdown(
        "DuckDB `httpfs` reads hive-partitioned parquet on S3. "
        "Column pruning + route/date filters pushed in SQL."
    )
with col2:
    st.markdown("**GTFS static**")
    st.markdown(
        "Per-agency local GTFS for direction recovery "
        "and scheduled headway by hour."
    )
with col3:
    st.markdown("**Primary metrics**")
    st.markdown(
        "Observed headway · scheduled headway · "
        "absolute deviation · relative deviation."
    )

st.markdown("---")
st.subheader("Agency status")
st.caption(f"Validation probe date: **{DEFAULT_SNAPSHOT_DATE}** · window: **{SHARED_ANALYSIS_LABEL}**")

active_cols = st.columns(len(ACTIVE_AGENCY_IDS))
for col, aid in zip(active_cols, ACTIVE_AGENCY_IDS):
    cfg = AGENCIES[aid]
    with col:
        ok = agency_data_available(aid)
        st.markdown(f"#### {'✅' if ok else '⚠️'} {cfg['short_name']}")
        st.caption(cfg["city"])
        st.caption(f"GTFS: {'OK' if agency_gtfs_available(aid) else 'missing'}")

if parquet_available() and summary is not None and not summary.empty:
    st.markdown("---")
    st.subheader("Route summary (snapshot)")
    st.caption(f"{snapshot_source_caption()} · {AGENCIES[get_current_agency_id()]['short_name']}")
    disp = summary[
        ["route_id", "route_name", "vehicles", "records", "effective_avg_speed_kmh"]
    ].copy()
    disp.columns = ["Route", "Name", "Vehicles", "Pings", "Avg km/h"]
    st.dataframe(
        disp.sort_values("Avg km/h", ascending=False, na_position="last"),
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    f"Docs: `README.md`, `docs/AGENCY_DATA_AUDIT.md` · "
    f"Shared May analysis window: **{SHARED_ANALYSIS_LABEL}**"
)
