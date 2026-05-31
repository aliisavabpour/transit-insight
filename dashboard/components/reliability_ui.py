"""
Research-oriented UI helpers: diagnostics, rule-based insights, metric glossary,
methodology text, limitations, and confidence flags for reliability pages.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.parquet_date import get_selected_date, get_shared_analysis_bounds
from utils.diagnostics_display import (
    format_analysis_day_label,
    format_gps_coverage_range,
    fmt_count,
    fmt_pct,
    NA,
)
from utils.real_data import get_parquet_snapshot_info, snapshot_match_note
from utils.reliability import (
    ADHERENCE_BAND_GOOD,
    ADHERENCE_BAND_MODERATE,
    BUNCHING_THRESHOLD_MIN,
    CAP_HEADWAY_MIN,
    GAP_THRESHOLD_MIN,
    MAX_REL_DEV_FOR_SCORE,
    REF_RADIUS_METERS,
    get_ref_radius_deg,
    get_ref_radius_meters,
)

MIN_ROUTE_OBS = 15
MIN_HOURLY_OBS = 3
LOW_MATCH_PCT = 80.0
HIGH_COV = 0.45
PEAK_HOURS = (15, 16, 17, 18)
EVENING_HOURS = (17, 18, 19, 20, 21)


def _hour_label(h: int) -> str:
    if h == 0:
        return "12 AM"
    if h < 12:
        return f"{h} AM"
    if h == 12:
        return "12 PM"
    return f"{h - 12} PM"


def _hour_range_label(hours: list[int]) -> str:
    if not hours:
        return "selected hours"
    hours = sorted(set(int(h) for h in hours))
    if len(hours) == 1:
        return _hour_label(hours[0])
    return f"{_hour_label(hours[0])}–{_hour_label(hours[-1])}"


def build_route_diagnostics(
    route_id: str,
    dq: dict,
    n_obs_headways: int = 0,
    n_hourly_cells: int = 0,
) -> dict:
    """Assemble diagnostics dict for the Data Quality panel."""
    base = get_parquet_snapshot_info()
    gtfs_min, gtfs_max = get_shared_analysis_bounds()
    selected = get_selected_date()
    gps_min = dq.get("t_start") or base.get("t_min")
    gps_max = dq.get("t_end") or base.get("t_max")
    trips_computed = bool(dq)
    return {
        "route_id": route_id,
        "snapshot_date": selected.isoformat(),
        "analysis_day_label": format_analysis_day_label(selected),
        "gps_coverage_label": format_gps_coverage_range(gps_min, gps_max),
        "gtfs_feed_start": gtfs_min.isoformat(),
        "gtfs_feed_end": gtfs_max.isoformat(),
        "gps_t_min": gps_min,
        "gps_t_max": gps_max,
        "match_pct": dq.get("match_pct") if dq else None,
        "null_trip_pct": dq.get("null_trip_pct") if dq else None,
        "total_pings": dq.get("total_pings") if dq else None,
        "total_trips": dq.get("total_parquet_trips") if dq else None,
        "matched_trips": dq.get("matched_trips") if dq else None,
        "unmatched_trips": dq.get("unmatched_trips") if dq else None,
        "trips_match_computed": trips_computed,
        "n_obs_headways": n_obs_headways,
        "n_hourly_cells": n_hourly_cells,
        "ref_radius_m": get_ref_radius_meters(),
    }


def build_network_diagnostics(hw_df: pd.DataFrame) -> dict:
    """Diagnostics for the network reliability page (all routes)."""
    base = get_parquet_snapshot_info()
    gtfs_min, gtfs_max = get_shared_analysis_bounds()
    selected = get_selected_date()
    n_cells = len(hw_df) if hw_df is not None and not hw_df.empty else 0
    n_routes = hw_df["route_id"].nunique() if n_cells else 0
    trips_computed = base.get("total_trips") is not None
    return {
        "snapshot_date": selected.isoformat(),
        "analysis_day_label": format_analysis_day_label(selected),
        "gps_coverage_label": format_gps_coverage_range(base.get("t_min"), base.get("t_max")),
        "gtfs_feed_start": gtfs_min.isoformat(),
        "gtfs_feed_end": gtfs_max.isoformat(),
        "gps_t_min": base.get("t_min"),
        "gps_t_max": base.get("t_max"),
        "match_pct": base.get("match_pct"),
        "null_trip_pct": base.get("null_trip_pct"),
        "total_trips": base.get("total_trips"),
        "matched_trips": base.get("matched_trips"),
        "unmatched_trips": base.get("unmatched_trips"),
        "trips_match_computed": trips_computed,
        "n_network_cells": n_cells,
        "n_routes": n_routes,
        "ref_radius_m": get_ref_radius_meters(),
    }


def assess_confidence(
    diagnostics: dict,
    obs_hw: pd.DataFrame,
    rel_df: pd.DataFrame,
) -> list[dict]:
    """Return confidence flags: level in info/warning/error/success."""
    flags: list[dict] = []

    match_pct = diagnostics.get("match_pct")
    if match_pct is not None and match_pct < LOW_MATCH_PCT:
        flags.append({
            "level": "warning",
            "title": "Low GTFS trip match",
            "detail": (
                f"Only {match_pct:.0f}% of trip IDs matched the static schedule. "
                "Schedule indicators use the matched subset only."
            ),
        })

    null_pct = diagnostics.get("null_trip_pct")
    if null_pct is not None and null_pct > 25:
        flags.append({
            "level": "info",
            "title": "Many GPS rows lack trip_id",
            "detail": (
                f"{null_pct:.0f}% of position records have no trip_id and cannot "
                "be linked to the GTFS schedule."
            ),
        })

    n_obs = len(obs_hw) if obs_hw is not None and not obs_hw.empty else 0
    if n_obs > 0 and n_obs < MIN_ROUTE_OBS:
        flags.append({
            "level": "warning",
            "title": "Low sample size",
            "detail": (
                f"Only {n_obs} pass-event headways at the reference point. "
                f"Treat summaries with caution (suggested minimum: {MIN_ROUTE_OBS})."
            ),
        })

    if rel_df is not None and not rel_df.empty and "n_observations" in rel_df.columns:
        thin = rel_df[rel_df["n_observations"] < MIN_HOURLY_OBS]
        if not thin.empty:
            parts = [
                f"{row['direction_label']} @ {_hour_label(int(row['hour']))}"
                for _, row in thin.head(4).iterrows()
            ]
            flags.append({
                "level": "info",
                "title": "Thin hourly samples",
                "detail": (
                    f"Some direction/hour cells have fewer than {MIN_HOURLY_OBS} pass events: "
                    f"{', '.join(parts)}"
                    + (" …" if len(thin) > 4 else "")
                ),
            })

        if "direction_id" in rel_df.columns:
            for did, grp in rel_df.groupby("direction_id"):
                if grp["n_observations"].sum() < MIN_ROUTE_OBS:
                    lbl = (
                        grp["direction_label"].iloc[0]
                        if "direction_label" in grp.columns
                        else f"Dir {did}"
                    )
                    flags.append({
                        "level": "warning",
                        "title": f"Limited observations — {lbl}",
                        "detail": (
                            f"Only {int(grp['n_observations'].sum())} pass events for this direction. "
                            "Hourly charts may be unstable."
                        ),
                    })

    if (
        not any(f["level"] == "warning" for f in flags)
        and n_obs >= MIN_ROUTE_OBS
        and (match_pct is None or match_pct >= LOW_MATCH_PCT)
    ):
        flags.append({
            "level": "success",
            "title": "Sample adequate for analysis",
            "detail": (
                f"{n_obs} pass-event headways with {match_pct:.0f}% GTFS match on this route/day."
                if match_pct is not None
                else f"{n_obs} pass-event headways on this route/day."
            ),
        })

    return flags


def build_route_insights(
    route_id: str,
    route_name: str,
    obs_hw: pd.DataFrame,
    rel_df: pd.DataFrame,
    diagnostics: dict,
) -> list[str]:
    """Deterministic, rule-based exploratory insight bullets."""
    if obs_hw.empty or rel_df.empty:
        return ["Insufficient pass-event data to summarize patterns for this route."]

    insights: list[str] = []
    hw = obs_hw["headway_min_capped"]
    mean_hw = float(hw.mean())
    median_hw = float(hw.median())
    n_bunch = int(obs_hw["is_bunched"].sum())
    n_gap = int(obs_hw["is_gap"].sum())

    peak = rel_df[rel_df["hour"].isin(PEAK_HOURS)].copy()
    if (
        not peak.empty
        and peak["median_headway"].notna().any()
        and peak["scheduled_headway_min"].notna().any()
    ):
        obs_peak = float(peak["median_headway"].mean())
        sched_peak = float(peak["scheduled_headway_min"].mean())
        if sched_peak > 0 and obs_peak > sched_peak * 1.25:
            insights.append(
                f"Afternoon peak ({_hour_range_label(list(PEAK_HOURS))}) suggests **wider observed spacing** "
                f"than scheduled: median ~{obs_peak:.1f} min vs ~{sched_peak:.1f} min (approximate comparison)."
            )
        elif sched_peak > 0 and obs_peak < sched_peak * 0.85:
            insights.append(
                f"Afternoon peak ({_hour_range_label(list(PEAK_HOURS))}) suggests **tighter observed spacing** "
                f"than scheduled (~{obs_peak:.1f} min vs ~{sched_peak:.1f} min)."
            )

    if "bunching_events" in rel_df.columns and rel_df["bunching_events"].sum() > 0:
        by_hour = rel_df.groupby("hour")["bunching_events"].sum()
        top_hours = by_hour[by_hour > 0].sort_values(ascending=False).head(3)
        if len(top_hours) >= 1 and top_hours.iloc[0] >= 2:
            hrs = list(top_hours.index.astype(int))
            insights.append(
                f"Route {route_id} ({route_name}) shows **elevated potential bunching** "
                f"between {_hour_range_label(hrs)} "
                f"({int(top_hours.sum())} threshold-based events in those hours)."
            )

    eve = rel_df[rel_df["hour"].isin(EVENING_HOURS)]
    if not eve.empty and eve["cov_headway"].notna().any():
        eve_cov = float(eve["cov_headway"].mean())
        day_cov = (
            float(rel_df["cov_headway"].mean())
            if rel_df["cov_headway"].notna().any()
            else eve_cov
        )
        if eve_cov >= HIGH_COV and eve_cov > day_cov * 1.1:
            insights.append(
                f"Evening hours ({_hour_range_label(list(EVENING_HOURS))}) show **higher headway variability** "
                f"(CoV ~{eve_cov:.2f} vs ~{day_cov:.2f} earlier in the day) — less even spacing."
            )

    sched_all = rel_df["scheduled_headway_min"].dropna()
    if not sched_all.empty:
        sched_med = float(sched_all.median())
        if sched_med > 0 and mean_hw > sched_med * 1.2:
            insights.append(
                f"Day-level mean spacing at the reference point (~{mean_hw:.1f} min) "
                f"exceeds the median scheduled interval (~{sched_med:.1f} min) on this snapshot."
            )

    if n_bunch > n_gap and n_bunch >= 3:
        insights.append(
            f"Potential bunching flags exceed gap flags ({n_bunch} vs {n_gap}) "
            f"at thresholds <{BUNCHING_THRESHOLD_MIN:.0f} min / >{GAP_THRESHOLD_MIN:.0f} min."
        )
    elif n_gap > n_bunch and n_gap >= 2:
        insights.append(
            f"Potential **service gap** flags ({n_gap} over {GAP_THRESHOLD_MIN:.0f} min) "
            f"outnumber bunching flags ({n_bunch}) on this day."
        )

    match_pct = diagnostics.get("match_pct")
    if match_pct is not None and match_pct >= 90:
        insights.append(
            f"GTFS trip match is ~{match_pct:.0f}% for this route — schedule comparisons "
            "are more defensible when match rates are high."
        )

    if not insights:
        insights.append(
            f"Route {route_id} shows relatively stable pass-event spacing (median {median_hw:.1f} min) "
            "on the selected day — exploratory summary only."
        )

    return insights[:6]


def build_network_insights(hw_df: pd.DataFrame) -> list[str]:
    """Exploratory insights for the network page."""
    if hw_df.empty:
        return ["No network headway indicators in the selected hour range."]

    insights: list[str] = []
    score_col = "adherence_score" if "adherence_score" in hw_df.columns else "on_time_pct"
    by_route = hw_df.groupby("route_id")[score_col].mean()
    if len(by_route) >= 2:
        worst = by_route.idxmin()
        best = by_route.idxmax()
        insights.append(
            f"Lowest mean exploratory adherence score: **Route {worst}** ({by_route[worst]:.1f}). "
            f"Highest: **Route {best}** ({by_route[best]:.1f}). "
            "(Proxy metric — not an official agency KPI.)"
        )

    if "headway_deviation_sec" in hw_df.columns:
        peak = hw_df[hw_df["hour"].isin(PEAK_HOURS)]
        off_peak = hw_df[~hw_df["hour"].isin(PEAK_HOURS)]
        if not peak.empty and not off_peak.empty:
            peak_dev = float(peak["headway_deviation_sec"].mean()) / 60
            op_dev = float(off_peak["headway_deviation_sec"].mean()) / 60
            if peak_dev > op_dev + 2:
                insights.append(
                    f"Afternoon peak ({_hour_range_label(list(PEAK_HOURS))}) shows larger "
                    "mean signed deviation from scheduled headway than off-peak hours."
                )

    return insights[:4]


def render_limitations_section() -> None:
    """Visible research limitations (not hidden in methodology only)."""
    with st.expander("Current limitations", expanded=False):
        st.markdown(
            f"""
- **Single-day snapshot** — one 24-hour parquet window; not representative of typical service.
- **Simplified headway estimation** — consecutive pass events at one reference point, not full-route travel times.
- **Virtual-stop approximation** — GPS pings within **{REF_RADIUS_METERS} m** of a fixed intersection (**not** true stop arrivals). A strict 150–250 m window captured no events at the Route 29 reference on the current snapshot; radius reflects nearest-ping distance (~600 m) while staying below the prior ~900 m setting.
- **Limited route set** — configured routes for the selected agency; some agencies use a top-route subset for speed.
- **Branch / pattern simplification** — scheduled headway aggregates all GTFS trips per direction/hour (e.g. 504A + 504B).
- **Hourly aggregation** — cells with few pass events ({MIN_HOURLY_OBS}+ recommended) produce unstable means and CoV.
- **Research-oriented indicators** — not validated against agency operations data or passenger wait times.
- **GTFS alignment required** — realtime day must fall inside the static feed calendar; mismatch sharply reduces trip match.
            """
        )


def render_methodology_expander(
    ref_label: str,
    dq: dict | None = None,
    expanded: bool = False,
) -> None:
    """Rigorous methodology text with transparent formulas."""
    match_note = f"~{dq['match_pct']:.0f}%" if dq and dq.get("match_pct") is not None else "see diagnostics"
    with st.expander("Methodology and assumptions", expanded=expanded):
        st.markdown(
            f"""
#### Virtual-stop pass events
A fixed reference point at **{ref_label}** defines a search window of **{REF_RADIUS_METERS} m**
(`{get_ref_radius_deg():.5f}`° Euclidean distance on lat/lon). For each matched `trip_id`,
the GPS ping **closest** to that point within the window is treated as one **pass event**.
This is **not** stop-level arrival detection; vehicles may pass near the intersection without serving it.

#### Direction recovery
Parquet `direction_id` often stores the route number. True direction comes from joining
`trip_id` → **`trips.txt`**. Rows with NULL or unmatched `trip_id` are excluded from direction-resolved metrics.

#### Scheduled headway
From **`stop_times.txt`**: first departure time per trip → hour bucket → trip count per direction/hour.
Scheduled headway (min) = `60 ÷ trip_count`. All service patterns for the route are combined.

#### Observed headway
Minutes between consecutive pass events in the same direction, local date, and hour
(midnight split prevents cross-date gaps in the 24 h UTC window).

#### Supporting flags
| Indicator | Rule |
|-----------|------|
| Potential bunching | Observed gap < **{BUNCHING_THRESHOLD_MIN:.0f} min** |
| Potential service gap | Observed gap > **{GAP_THRESHOLD_MIN:.0f} min** |
| CoV (variability) | `std(headway) ÷ mean(headway)` on capped gaps (≤ **{CAP_HEADWAY_MIN:.0f} min**) |

#### Schedule comparison methodology
For each hour/direction with both scheduled and mean observed headway:

- **Absolute deviation (min):** `|mean_observed − scheduled|`
- **Relative deviation:** `|mean_observed − scheduled| ÷ scheduled`
- **Adherence score (0–100):** `max(0, 100 × (1 − min(relative_deviation, {MAX_REL_DEV_FOR_SCORE})))`
- **Bands:** Good if relative deviation < **{ADHERENCE_BAND_GOOD}**;
  Moderate if **{ADHERENCE_BAND_GOOD}–{ADHERENCE_BAND_MODERATE}**; Poor if > **{ADHERENCE_BAND_MODERATE}**

Signed deviation (observed − scheduled) is also shown in seconds for direction of bias.

Results depend on the **selected route, day, GTFS match rate ({match_note})**, and sample size.
{snapshot_match_note()}.
            """
        )


def render_metric_glossary(expanded: bool = False) -> None:
    with st.expander("What do these metrics mean?", expanded=expanded):
        st.markdown(
            f"""
#### Primary metrics (report focus)
| Metric | Explanation |
|--------|-------------|
| **Observed headway** | Minutes between consecutive pass events at the route reference point (GPS-based). |
| **Scheduled headway** | From GTFS: `60 ÷ trips per direction per hour`. |
| **Absolute deviation** | `|observed − scheduled|` in minutes or seconds. |
| **Relative deviation** | Absolute deviation ÷ scheduled headway (unitless). |

#### Supporting indicators
| Metric | Explanation |
|--------|-------------|
| **Adherence score** | `max(0, 100×(1 − relative_deviation))` — supplementary chart metric derived from relative deviation. |
| **Adherence band** | Good / Moderate / Poor from relative deviation ({ADHERENCE_BAND_GOOD}, {ADHERENCE_BAND_MODERATE}). |
| **Potential bunching** | Pass-event gap < **{BUNCHING_THRESHOLD_MIN:.0f} min**. |
| **Potential service gap** | Pass-event gap > **{GAP_THRESHOLD_MIN:.0f} min**. |
| **CoV (variability)** | std ÷ mean of capped headways in an hour — spacing evenness indicator. |
| **Sample size** | Pass events in that hour/direction cell. |
            """
        )


def render_diagnostics_panel(diagnostics: dict, route_id: str | None = None) -> None:
    title = (
        f"Data Quality & Diagnostics — Route {route_id}"
        if route_id
        else "Data Quality & Diagnostics"
    )
    with st.expander(title, expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Analysis day",
            diagnostics.get("analysis_day_label", NA),
            help="Snapshot calendar day selected in the sidebar (service analysis date).",
        )
        c2.metric(
            "GTFS feed range",
            f"{diagnostics.get('gtfs_feed_start', NA)} → {diagnostics.get('gtfs_feed_end', NA)}",
            help="Static schedule validity window; realtime day should fall inside this range.",
        )
        c3.metric(
            "GTFS trip match",
            fmt_pct(diagnostics.get("match_pct")),
            help=(
                "Distinct parquet trip_ids found in trips.txt for this route."
                if route_id
                else "Fleet-wide share of distinct parquet trip_ids found in trips.txt."
            ),
        )
        c4.metric(
            "NULL trip_id",
            fmt_pct(diagnostics.get("null_trip_pct")),
            help="Share of GPS rows that cannot be joined to the schedule.",
        )

        trips_computed = diagnostics.get("trips_match_computed", False)
        c5, c6, c7, c8 = st.columns(4)
        c5.metric(
            "Matched trips",
            fmt_count(diagnostics.get("matched_trips"), computed=trips_computed),
            help="Parquet trips with a trips.txt match.",
        )
        c6.metric(
            "Unmatched trips",
            fmt_count(diagnostics.get("unmatched_trips"), computed=trips_computed),
            help="Parquet trips not found in the static feed for this route."
            if route_id
            else "Parquet trips not found in the static feed (fleet-wide).",
        )
        if route_id:
            c7.metric(
                "GPS pings (route)",
                fmt_count(diagnostics.get("total_pings"), computed=trips_computed),
                help="All position records for this route in the snapshot.",
            )
            c8.metric(
                "Pass-event headways",
                fmt_count(diagnostics.get("n_obs_headways"), computed=True),
                help=f"Observed gaps after virtual-stop detection ({diagnostics.get('ref_radius_m', REF_RADIUS_METERS)} m radius).",
            )
        else:
            c7.metric(
                "Network metric cells",
                fmt_count(diagnostics.get("n_network_cells"), computed=True),
                help="Route × hour cells in the filtered network table.",
            )
            c8.metric(
                "Routes analyzed",
                fmt_count(diagnostics.get("n_routes"), computed=True),
                help="Routes contributing metric cells in the selected hour range (may be a sampled top-route subset).",
            )

        st.caption(
            f"Pass-event radius: **{diagnostics.get('ref_radius_m', REF_RADIUS_METERS)} m** · "
            f"GPS coverage: **{diagnostics.get('gps_coverage_label', NA)}** · "
            f"File date: **{diagnostics.get('snapshot_date', NA)}**"
        )
        if diagnostics.get("n_hourly_cells"):
            st.caption(
                f"Hourly table: **{diagnostics['n_hourly_cells']}** direction×hour cells — "
                f"interpret cautiously when sample size < {MIN_HOURLY_OBS}."
            )


def render_confidence_flags(flags: list[dict]) -> None:
    if not flags:
        return
    for f in flags:
        level = f.get("level", "info")
        msg = f"**{f['title']}** — {f['detail']}"
        if level == "warning":
            st.warning(msg)
        elif level == "error":
            st.error(msg)
        elif level == "success":
            st.success(msg)
        else:
            st.info(msg)


def render_insights_box(insights: list[str], title: str = "Exploratory pattern summary") -> None:
    if not insights:
        return
    if title:
        st.markdown(f"#### {title}")
    st.caption(
        "Rule-based summaries from pass-event headways and hourly tables. "
        "Indicative only — not operational conclusions."
    )
    for line in insights:
        st.markdown(f"- {line}")


def render_route_reliability_extras(
    route_id: str,
    route_name: str,
    dq: dict,
    obs_hw: pd.DataFrame,
    rel_df: pd.DataFrame,
) -> None:
    """Diagnostics, confidence, insights, limitations, glossary for route pages."""
    n_obs = len(obs_hw) if obs_hw is not None and not obs_hw.empty else 0
    n_cells = len(rel_df) if rel_df is not None and not rel_df.empty else 0
    diag = build_route_diagnostics(route_id, dq or {}, n_obs, n_cells)

    render_diagnostics_panel(diag, route_id=route_id)
    render_confidence_flags(assess_confidence(diag, obs_hw, rel_df))
    if n_obs > 0:
        with st.expander("Exploratory pattern summary (rule-based)", expanded=False):
            render_insights_box(
                build_route_insights(route_id, route_name, obs_hw, rel_df, diag),
                title="",
            )
    render_limitations_section()
    render_metric_glossary(expanded=False)
