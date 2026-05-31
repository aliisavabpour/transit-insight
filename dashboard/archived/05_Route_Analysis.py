"""
Archived Route Analysis page — not registered in Streamlit navigation.
Run manually for development: streamlit run archived/05_Route_Analysis.py

Bus Reliability Analysis — TTC + OC Transpo cross-agency prototype.
Select a route from the sidebar to see GPS data and observed-headway reliability metrics.
Methodology: virtual-stop headway, direction recovery via GTFS trip join, DuckDB in-memory.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from utils.real_data import (
    parquet_available,
    load_route_positions,
    load_hourly_activity,
    load_speed_percentiles,
    get_parquet_snapshot_info,
    snapshot_source_caption,
    snapshot_match_note,
)
from utils.agency_config import AGENCIES, SHARED_ANALYSIS_LABEL
from utils.agency_loader import get_current_agency_id
from utils.route_config import (
    SUPPORTED_ROUTES,
    get_route_config,
    get_routes_for_agency,
)
from utils.gtfs_loader import load_feed_date_range
from utils.reliability import (
    compute_data_quality,
    compute_observed_headways,
    compute_scheduled_headways,
    compute_hourly_reliability,
    BUNCHING_THRESHOLD_MIN,
    GAP_THRESHOLD_MIN,
    CAP_HEADWAY_MIN,
)

from utils.parquet_date import render_agency_sidebar
from components.page_guard import require_active_agency, run_data_load
from components.reliability_ui import render_route_reliability_extras, render_methodology_expander

st.set_page_config(page_title="Route Analysis | Transit Insight", layout="wide")
render_agency_sidebar()
require_active_agency()

_agency_id = get_current_agency_id()
_agency_routes = get_routes_for_agency(_agency_id)
if not _agency_routes:
    st.title("Route Analysis")
    st.info(
        f"Deep route-level analysis is configured for **TTC** (e.g. Route 29). "
        f"**{AGENCIES[_agency_id]['short_name']}** is active for fleet overview and "
        f"network indicators over the shared May window ({SHARED_ANALYSIS_LABEL}). "
        f"Switch to **TTC** in the sidebar for the primary route demo."
    )
    st.stop()

MAPBOX_STYLE = "carto-darkmatter"
CHART_BG     = "#161B22"
CHART_FONT   = "#E6EDF3"
CHART_GRID   = "#2a2a2a"

_snap = get_parquet_snapshot_info()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Route Analysis")
    st.caption("Primary demo · Route 29 default")
    st.markdown("---")

    route_ids    = sorted(_agency_routes.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
    route_labels = []
    for rid in route_ids:
        cfg = _agency_routes[rid]
        vtype = cfg.get("vehicle_type", "")
        tag   = " (Bus)" if vtype == "bus" else " (Streetcar)" if vtype == "streetcar" else ""
        route_labels.append(f"{rid} — {cfg['name']}{tag}")

    # Default to Route 29 Dufferin (bus — primary demo example)
    default_idx   = route_ids.index("29") if "29" in route_ids else 0
    selected_lbl  = st.selectbox("Select route", route_labels, index=default_idx)
    ROUTE_ID      = route_ids[route_labels.index(selected_lbl)]
    cfg           = get_route_config(ROUTE_ID)

    vtype = cfg.get("vehicle_type", "route")
    st.caption(f"Type: {vtype.title()} · Agency: {cfg.get('agency_id','ttc').upper()}")
    st.caption(f"Ref: {cfg['ref_point']['label']}")
    st.markdown("---")

    dir_options      = ["Both directions"] + list(cfg["directions"].values())
    selected_dir_lbl = st.radio("Reliability direction filter", dir_options, index=0)
    dir_filter_id    = None
    if selected_dir_lbl != "Both directions":
        dir_filter_id = next(
            k for k, v in cfg["directions"].items() if v == selected_dir_lbl
        )

    show_traces = st.checkbox("Show vehicle traces", value=False)
    n_trace     = st.slider("Vehicles to trace", 1, 10, 3) if show_traces else 3

    st.markdown("---")
    from utils.diagnostics_display import format_analysis_day_label
    from utils.parquet_date import get_selected_date

    st.caption(
        f"Analysis day: {format_analysis_day_label(get_selected_date())} · "
        f"{SHARED_ANALYSIS_LABEL}"
    )


REF   = cfg["ref_point"]
DIRS  = cfg["directions"]
COLOR = cfg["color"]
VTYPE = cfg.get("vehicle_type", "route")


# ── Load GPS / speed data ──────────────────────────────────────────────────────
with st.spinner(f"Loading route {ROUTE_ID} GPS data…"):
    pos_df    = load_route_positions(ROUTE_ID, latest_only=True)
    hourly_df = load_hourly_activity(ROUTE_ID)
    pct_df    = load_speed_percentiles(ROUTE_ID)


# ── Page header ───────────────────────────────────────────────────────────────
agency_label = cfg.get("agency_id", "ttc").upper()
st.title(f"Route {ROUTE_ID} — {cfg['name']} ({VTYPE.title()})")
st.markdown(cfg["description"])
st.caption(f"Agency: {agency_label} · {snapshot_source_caption()}")


# ── KPIs ──────────────────────────────────────────────────────────────────────
n_vehicles = len(pos_df)
avg_speed  = pos_df["speed_kmh"].mean()   if not pos_df.empty else 0
pct_moving = (pos_df["speed_kmh"] > 1).mean() * 100 if not pos_df.empty else 0

c1, c2, c3 = st.columns(3)
c1.metric("Active Vehicles", f"{n_vehicles}")
c2.metric("Average Speed",   f"{avg_speed:.1f} km/h")
c3.metric("Moving (%)",      f"{pct_moving:.0f}%")

st.markdown("---")


# ── Vehicle map ───────────────────────────────────────────────────────────────
st.subheader("Vehicle Positions — Latest Ping per Vehicle")
st.caption(
    f"All route {ROUTE_ID} vehicles shown in route colour. "
    "Direction is not available on the map — it is recovered in the "
    "reliability section below via GTFS trip matching."
)

if not pos_df.empty:
    fig_map = px.scatter_mapbox(
        pos_df,
        lat="latitude", lon="longitude",
        color_discrete_sequence=[COLOR],
        hover_name="vehicle_id",
        hover_data={
            "speed_kmh": True, "bearing": True, "timestamp": True,
            "latitude": False, "longitude": False,
        },
        zoom=cfg["map_zoom"],
        center=cfg["map_center"],
        mapbox_style=MAPBOX_STYLE,
    )
    fig_map.update_traces(marker=dict(size=10, opacity=0.9))
    fig_map.update_layout(
        showlegend=False, height=480,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="#0D1117", font_color=CHART_FONT,
    )
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.warning("No position data found for this route.")

if show_traces and not pos_df.empty:
    from utils.real_data import load_vehicle_traces
    trace_ids = pos_df["vehicle_id"].head(n_trace).tolist()
    with st.spinner("Loading vehicle traces…"):
        trace_df = load_vehicle_traces(ROUTE_ID, trace_ids)
    if not trace_df.empty:
        fig_tr = px.line_mapbox(
            trace_df, lat="latitude", lon="longitude", color="vehicle_id",
            zoom=cfg["map_zoom"], center=cfg["map_center"],
            mapbox_style=MAPBOX_STYLE,
            hover_data=["speed_kmh", "timestamp"],
        )
        fig_tr.update_layout(
            height=440, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="#0D1117", font_color=CHART_FONT,
        )
        st.plotly_chart(fig_tr, use_container_width=True)

with st.expander(f"Vehicle snapshot — {n_vehicles} vehicles · latest ping", expanded=False):
    st.caption("All timestamps in Toronto local time (EDT = UTC−4).")
    if not pos_df.empty:
        st.dataframe(
            pos_df[["vehicle_id", "speed_kmh", "bearing", "latitude", "longitude", "timestamp"]]
            .sort_values("vehicle_id")
            .rename(columns={
                "vehicle_id": "Vehicle", "speed_kmh": "Speed (km/h)",
                "bearing": "Bearing (°)", "latitude": "Lat",
                "longitude": "Lon", "timestamp": "Last Seen",
            }),
            use_container_width=True, hide_index=True,
        )

st.markdown("---")


# ── Hourly activity & speed ───────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.subheader("Active Vehicles by Hour")
    st.caption("Count of distinct vehicles transmitting GPS pings per hour.")
    if not hourly_df.empty:
        fig_hr = go.Figure(go.Bar(
            x=hourly_df["hour"], y=hourly_df["active_vehicles"],
            marker_color=COLOR,
            hovertemplate="Hour %{x}:00 — %{y} vehicles<extra></extra>",
        ))
        fig_hr.update_layout(
            xaxis=dict(title="Hour of Day (Toronto time)", dtick=2, gridcolor=CHART_GRID),
            yaxis=dict(title="Active vehicles", gridcolor=CHART_GRID),
            plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG,
            font_color=CHART_FONT, showlegend=False,
            height=300, margin=dict(l=40, r=20, t=10, b=40),
        )
        st.plotly_chart(fig_hr, use_container_width=True)
    else:
        st.info("No hourly data.")

with col_r:
    st.subheader("Average Speed by Hour")
    st.caption("Mean GPS-reported speed across all vehicle pings per hour.")
    if not hourly_df.empty:
        fig_sp = go.Figure(go.Scatter(
            x=hourly_df["hour"], y=hourly_df["avg_speed_kmh"],
            mode="lines+markers",
            line=dict(color=COLOR, width=2), marker=dict(size=6),
            hovertemplate="Hour %{x}:00 — %{y} km/h<extra></extra>",
        ))
        fig_sp.update_layout(
            xaxis=dict(title="Hour of Day (Toronto time)", dtick=2, gridcolor=CHART_GRID),
            yaxis=dict(title="Speed (km/h)", gridcolor=CHART_GRID),
            plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG,
            font_color=CHART_FONT, showlegend=False,
            height=300, margin=dict(l=40, r=20, t=10, b=40),
        )
        st.plotly_chart(fig_sp, use_container_width=True)
    else:
        st.info("No speed data.")

st.markdown("---")


# ── Speed percentile band ─────────────────────────────────────────────────────
st.subheader("Speed Distribution by Hour — Percentile Bands")
st.caption(
    "Shaded bands show P10–P90 (outer) and P25–P75 (inner) speed range. "
    "Solid line = median (P50). Narrower bands = more consistent speed."
)

if not pct_df.empty:
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Scatter(
        x=list(pct_df["hour"]) + list(pct_df["hour"])[::-1],
        y=list(pct_df["p90_kmh"]) + list(pct_df["p10_kmh"])[::-1],
        fill="toself", fillcolor="rgba(66,165,245,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="P10–P90", showlegend=True, hoverinfo="skip",
    ))
    fig_pct.add_trace(go.Scatter(
        x=list(pct_df["hour"]) + list(pct_df["hour"])[::-1],
        y=list(pct_df["p75_kmh"]) + list(pct_df["p25_kmh"])[::-1],
        fill="toself", fillcolor="rgba(66,165,245,0.28)",
        line=dict(color="rgba(0,0,0,0)"),
        name="P25–P75", showlegend=True, hoverinfo="skip",
    ))
    fig_pct.add_trace(go.Scatter(
        x=pct_df["hour"], y=pct_df["p50_kmh"],
        mode="lines+markers",
        line=dict(color=COLOR, width=2.5), marker=dict(size=5),
        name="Median (P50)",
        hovertemplate="Hour %{x}:00 · median %{y} km/h<extra></extra>",
    ))
    fig_pct.update_layout(
        xaxis=dict(title="Hour of Day (Toronto time)", dtick=2, gridcolor=CHART_GRID),
        yaxis=dict(title="Speed (km/h)", gridcolor=CHART_GRID),
        plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG,
        font_color=CHART_FONT, legend=dict(bgcolor=CHART_BG),
        height=360, margin=dict(l=40, r=20, t=10, b=40),
    )
    st.plotly_chart(fig_pct, use_container_width=True)
else:
    st.info("No percentile data.")

st.markdown("---")


# ── Lightweight headway demo ──────────────────────────────────────────────────
st.subheader("Headway comparison (lightweight demo)")
st.markdown(
    f"Approximate pass-event headways at **{REF['label']}** (virtual-stop method, "
    f"not true stop arrivals). One pass event per matched trip per direction, aggregated by hour. "
    + (f"Direction filter: **{selected_dir_lbl}**." if dir_filter_id
       else "Both directions shown.")
)

# ── Load reliability data ─────────────────────────────────────────────────────
def _load_reliability():
    dq = compute_data_quality(ROUTE_ID)
    obs = compute_observed_headways(ROUTE_ID, REF["lat"], REF["lon"])
    sched = compute_scheduled_headways(ROUTE_ID)
    rel = compute_hourly_reliability(ROUTE_ID, REF["lat"], REF["lon"])
    return dq, obs, sched, rel

dq, obs_hw, sched_hw, rel_df = run_data_load(
    "Computing headway metrics… (first run may scan stop_times.txt ~60s, then cached)",
    _load_reliability,
)

# Remap generic "Dir 0"/"Dir 1" to route-specific direction labels
def _remap_dirs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["direction_label"] = df["direction_id"].map(DIRS).fillna("Unknown")
    return df

obs_hw = _remap_dirs(obs_hw)
rel_df = _remap_dirs(rel_df)

# Apply direction filter (reliability only; map always shows all vehicles)
if dir_filter_id and not obs_hw.empty:
    obs_hw = obs_hw[obs_hw["direction_id"] == dir_filter_id]
if dir_filter_id and not rel_df.empty:
    rel_df = rel_df[rel_df["direction_id"] == dir_filter_id]


render_route_reliability_extras(ROUTE_ID, cfg["name"], dq, obs_hw, rel_df)
render_methodology_expander(REF["label"], dq=dq)

st.markdown("---")

if obs_hw.empty:
    st.warning(
        "No observed headway data. "
        "Check that `trips.txt` is present and that this route exists in the parquet."
    )
else:
    # ── Primary KPIs (frozen metrics) ───────────────────────────────────────
    n_obs = len(obs_hw)
    mean_obs = rel_df["mean_headway"].mean() if not rel_df.empty and "mean_headway" in rel_df.columns else obs_hw["headway_min_capped"].mean()
    mean_sched = rel_df["scheduled_headway_min"].mean() if not rel_df.empty and rel_df["scheduled_headway_min"].notna().any() else float("nan")
    mean_abs = rel_df["abs_headway_deviation_min"].mean() if not rel_df.empty and rel_df["abs_headway_deviation_min"].notna().any() else float("nan")
    mean_rel = rel_df["relative_deviation"].mean() if not rel_df.empty and rel_df["relative_deviation"].notna().any() else float("nan")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Observed headway (mean)", f"{mean_obs:.1f} min", help="Mean pass-event gap across hourly cells")
    p2.metric("Scheduled headway (mean)", f"{mean_sched:.1f} min" if pd.notna(mean_sched) else "—", help="From GTFS departures per hour")
    p3.metric("Absolute deviation (mean)", f"{mean_abs:.1f} min" if pd.notna(mean_abs) else "—", help="|observed − scheduled|")
    p4.metric("Relative deviation (mean)", f"{mean_rel:.2f}" if pd.notna(mean_rel) else "—", help="Absolute deviation ÷ scheduled")
    st.caption(
        f"Primary metrics · **{n_obs}** pass-event headways at {REF['label']} · "
        f"hourly table has {len(rel_df)} direction/hour cells."
    )

    with st.expander("Exploratory spacing flags (CoV, bunching, gaps)", expanded=False):
        hw_cap = obs_hw["headway_min_capped"]
        cov_hw = hw_cap.std() / hw_cap.mean() if hw_cap.mean() > 0 else 0
        e1, e2, e3 = st.columns(3)
        e1.metric("CoV (exploratory)", f"{cov_hw:.2f}")
        e2.metric("Potential bunching", int(obs_hw["is_bunched"].sum()))
        e3.metric("Potential gaps", int(obs_hw["is_gap"].sum()))
    st.markdown("---")

    # ── Chart 1: Observed vs scheduled headway by hour ──────────────────────
    st.markdown("#### Approximate observed vs scheduled headway by hour")
    st.caption(
        "**Solid** = median observed pass-event gap. **Dashed** = GTFS scheduled interval (all patterns). "
        "**Look for:** sustained separation between lines — suggests spacing differs from timetable. "
        "**Caution:** low hourly sample sizes (see table) make medians unstable."
    )

    if not rel_df.empty:
        chart_rows = []
        for _, row in rel_df.iterrows():
            lbl = row["direction_label"]
            if pd.notna(row["median_headway"]):
                chart_rows.append({"Hour": int(row["hour"]),
                                   "Series": f"{lbl} — Observed",
                                   "Minutes": row["median_headway"]})
            if pd.notna(row.get("scheduled_headway_min")):
                chart_rows.append({"Hour": int(row["hour"]),
                                   "Series": f"{lbl} — Scheduled",
                                   "Minutes": row["scheduled_headway_min"]})
        if chart_rows:
            cmap = {}
            for dk, dv in DIRS.items():
                c = "#42A5F5" if dk == "0" else "#FF7043"
                cmap[f"{dv} — Observed"]  = c
                cmap[f"{dv} — Scheduled"] = c

            chart_df = pd.DataFrame(chart_rows)
            fig_hw = px.line(
                chart_df, x="Hour", y="Minutes", color="Series", markers=True,
                color_discrete_map=cmap,
                line_dash="Series",
                line_dash_map={k: ("solid" if "Observed" in k else "dot")
                               for k in chart_df["Series"].unique()},
                labels={"Minutes": "Minutes between buses"},
            )
            fig_hw.update_layout(
                plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG, font_color=CHART_FONT,
                xaxis=dict(title="Hour of Day (Toronto time)", dtick=1,
                           gridcolor=CHART_GRID, range=[-0.5, 23.5]),
                yaxis=dict(title="Minutes between buses",
                           gridcolor=CHART_GRID, rangemode="tozero"),
                legend=dict(bgcolor=CHART_BG, title=""),
                margin=dict(l=0, r=0, t=20, b=0), height=350,
            )
            st.plotly_chart(fig_hw, use_container_width=True, key=f"route_{ROUTE_ID}_hw_compare")

    with st.expander("Exploratory charts: CoV, bunching, and gap flags by hour", expanded=False):
        st.markdown("#### Headway variability (CoV) by hour")
        if not rel_df.empty and rel_df["cov_headway"].notna().any():
            cov_df = rel_df[rel_df["cov_headway"].notna()].copy()
            dcolor = {v: ("#42A5F5" if k == "0" else "#FF7043") for k, v in DIRS.items()}
            fig_cov = px.bar(
                cov_df, x="hour", y="cov_headway", color="direction_label", barmode="group",
                color_discrete_map=dcolor,
            )
            fig_cov.update_layout(
                plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG, font_color=CHART_FONT, height=300,
            )
            st.plotly_chart(fig_cov, use_container_width=True, key=f"route_{ROUTE_ID}_cov")
        st.markdown("#### Potential bunching and gap flags by hour")
        if not rel_df.empty:
            ev_rows = []
            for _, row in rel_df.iterrows():
                lbl = row["direction_label"]
                if row["bunching_events"] > 0:
                    ev_rows.append({"Hour": int(row["hour"]), "Direction": lbl,
                                    "Event": "Bunching", "Count": int(row["bunching_events"])})
                if row["gap_events"] > 0:
                    ev_rows.append({"Hour": int(row["hour"]), "Direction": lbl,
                                    "Event": "Gap", "Count": int(row["gap_events"])})
            if ev_rows:
                fig_ev = px.bar(pd.DataFrame(ev_rows), x="Hour", y="Count", color="Event",
                                facet_col="Direction", barmode="stack")
                fig_ev.update_layout(
                    plot_bgcolor=CHART_BG, paper_bgcolor=CHART_BG, font_color=CHART_FONT, height=300,
                )
                st.plotly_chart(fig_ev, use_container_width=True, key=f"route_{ROUTE_ID}_bunch_gap")
            else:
                st.info("No bunching or gap flags at current thresholds.")

    with st.expander("Full hourly detail table", expanded=False):
        if not rel_df.empty:
            col_map = {
                "direction_label":       "Direction",
                "hour":                  "Hour",
                "scheduled_headway_min": "Scheduled (min)",
                "mean_headway":          "Mean observed (min)",
                "median_headway":        "Median observed (min)",
                "std_headway":           "Std dev (min)",
                "cov_headway":           "Variability (CoV)",
                "n_observations":        "Sample size",
                "bunching_events":       "Potential bunching",
                "gap_events":            "Potential gaps",
                "relative_deviation":    "Relative deviation",
                "adherence_score":       "Adherence score",
                "adherence_band":        "Band",
            }
            avail = [c for c in col_map if c in rel_df.columns]
            st.dataframe(
                rel_df[avail].rename(columns={c: col_map[c] for c in avail})
                .sort_values(["Direction", "Hour"]).reset_index(drop=True),
                use_container_width=True, hide_index=True,
            )

st.markdown("---")
_gtfs_s, _gtfs_e = load_feed_date_range()
st.caption(
    f"Route {ROUTE_ID} · {snapshot_source_caption()} · "
    f"Ref: {REF['label']} · "
    f"GTFS feed valid {_gtfs_s[:4]}-{_gtfs_s[4:6]}-{_gtfs_s[6:8]} – {_gtfs_e[:4]}-{_gtfs_e[4:6]}-{_gtfs_e[6:8]} · "
    "Cross-agency bus reliability prototype — OC Transpo routes pending data ingestion"
)
