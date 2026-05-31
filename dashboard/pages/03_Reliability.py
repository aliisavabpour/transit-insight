"""
Reliability indicators — routes with configured reference points.
Uses real GTFS-RT parquet + GTFS schedule when parquet is present.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.real_data import (
    parquet_available,
    snapshot_source_caption,
)
from utils.reliability import load_network_headway_metrics, compute_data_quality
from components.charts import (
    headway_heatmap,
    headway_deviation_line,
)
from components.filters import agency_route_selectbox, hour_range_slider
from utils.agency_loader import get_current_agency_id
from utils.parquet_date import render_agency_sidebar
from components.page_guard import require_active_agency, run_data_load
from components.reliability_ui import (
    assess_confidence,
    build_network_diagnostics,
    build_route_diagnostics,
    render_confidence_flags,
    render_diagnostics_panel,
    render_limitations_section,
    render_metric_glossary,
    render_methodology_expander,
)

from utils.agency_config import SHARED_ANALYSIS_LABEL
from utils.route_config import get_network_routes_for_agency

st.set_page_config(page_title="Reliability | Transit Insight", layout="wide")
render_agency_sidebar()
require_active_agency()
st.title("Schedule deviation indicators")
st.caption(f"Shared May analysis window: **{SHARED_ANALYSIS_LABEL}**")

_agency_routes = get_network_routes_for_agency(get_current_agency_id())
_route_list = ", ".join(
    f"{rid} ({cfg['name']})"
    for rid, cfg in sorted(_agency_routes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0]))
)
_n_routes_analyzed = len(_agency_routes)

if parquet_available():
    if _n_routes_analyzed:
        st.caption(
            f"{snapshot_source_caption()} · "
            f"**{_n_routes_analyzed} routes analyzed in this view:** {_route_list}"
        )
    else:
        st.caption(f"{snapshot_source_caption()} · Top routes from parquet (auto-selected)")
else:
    st.warning(
        f"Realtime parquet not found. Select a day in the shared May window ({SHARED_ANALYSIS_LABEL})."
    )


# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    selected_route = agency_route_selectbox("Route (detail view)")
    hour_min, hour_max = hour_range_slider("Hour range")
    metric_choice = st.radio(
        "Heatmap metric",
        [
            "Relative deviation",
            "Absolute deviation (sec)",
            "Signed deviation (sec)",
        ],
    )

_METRIC_COL_MAP = {
    "Relative deviation": "relative_deviation",
    "Absolute deviation (sec)": "abs_headway_deviation_sec",
    "Signed deviation (sec)": "headway_deviation_sec",
}


# ── Data loading ──────────────────────────────────────────────────────────────
hw_df = run_data_load(
    "Loading network headway metrics…",
    load_network_headway_metrics,
    hour_min,
    hour_max,
)

# ── Network-wide KPIs ─────────────────────────────────────────────────────────
if not hw_df.empty:
    avg_obs = hw_df["actual_headway_sec"].mean() if "actual_headway_sec" in hw_df.columns else None
    avg_sched = hw_df["scheduled_headway_sec"].mean() if "scheduled_headway_sec" in hw_df.columns else None
    avg_abs = hw_df["abs_headway_deviation_sec"].mean() if "abs_headway_deviation_sec" in hw_df.columns else None
    avg_rel = hw_df["relative_deviation"].mean() if "relative_deviation" in hw_df.columns else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Observed headway (mean)", f"{avg_obs/60:.1f} min" if avg_obs is not None else "—")
    c2.metric("Scheduled headway (mean)", f"{avg_sched/60:.1f} min" if avg_sched is not None else "—")
    c3.metric("Absolute deviation (mean)", f"{avg_abs:.0f}s" if avg_abs is not None else "—")
    c4.metric("Relative deviation (mean)", f"{avg_rel:.2f}" if avg_rel is not None else "—")
    if avg_rel is not None:
        st.caption(f"Network mean relative deviation: **{avg_rel:.2f}** (0 = exact schedule match).")
else:
    st.warning(
        "No headway indicators in the selected hour range. "
        "Try widening the hour slider (e.g. 0–23)."
    )

net_diag = build_network_diagnostics(hw_df)
render_diagnostics_panel(net_diag)
if selected_route:
    route_dq = compute_data_quality(selected_route)
    if route_dq:
        rd = build_route_diagnostics(selected_route, route_dq)
        render_confidence_flags(assess_confidence(rd, pd.DataFrame(), pd.DataFrame()))
render_limitations_section()
render_metric_glossary(expanded=False)

st.markdown("---")

# ── Heatmap ───────────────────────────────────────────────────────────────────
st.subheader("Headway comparison heatmap")
value_col = _METRIC_COL_MAP[metric_choice]
st.caption(
    "Shows where observed and scheduled headway diverge across routes and hours. "
    "Check diagnostics for low-sample cells."
)
fig_heat = headway_heatmap(hw_df, value_col=value_col)
st.plotly_chart(fig_heat, use_container_width=True, key="reliability_heatmap")

# ── Per-route detail ──────────────────────────────────────────────────────────
if selected_route:
    st.markdown("---")
    st.subheader(f"Route {selected_route} — headway comparison")
    st.caption(
        "**Dashed** = scheduled mean headway (GTFS). **Solid** = observed mean from pass events. "
        "Large separation suggests uneven spacing vs timetable for that hour."
    )
    fig_line = headway_deviation_line(hw_df, selected_route)
    st.plotly_chart(fig_line, use_container_width=True, key="reliability_headway_line")

    route_df = hw_df[hw_df["route_id"] == selected_route]
    if not route_df.empty:
        r_abs = route_df["abs_headway_deviation_sec"].mean() if "abs_headway_deviation_sec" in route_df.columns else None
        r_rel = route_df["relative_deviation"].mean() if "relative_deviation" in route_df.columns else None
        r_sched = route_df["scheduled_headway_sec"].mean()
        r_actual = route_df["actual_headway_sec"].mean()

        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("Observed headway", f"{r_actual/60:.1f} min")
        cc2.metric("Scheduled headway", f"{r_sched/60:.1f} min")
        cc3.metric("Absolute deviation", f"{r_abs:.0f}s" if r_abs is not None else "—")
        cc4.metric("Relative deviation", f"{r_rel:.2f}" if r_rel is not None else "—")
        if r_rel is not None:
            st.caption(f"Mean relative deviation: **{r_rel:.2f}**")

st.markdown("---")
cfg = _agency_routes.get(selected_route, {}) if selected_route else {}
ref_lbl = cfg.get("ref_point", {}).get("label", "configured reference point")
render_methodology_expander(ref_lbl, dq=compute_data_quality(selected_route) if selected_route else None)
