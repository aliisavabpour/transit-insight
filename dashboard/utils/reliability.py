"""
Transit reliability metrics — generalised for any supported TTC route.

METHODOLOGY — Observed headway (virtual-stop approach)
-------------------------------------------------------
A fixed GPS reference point is chosen for each route (e.g. King St & Bay St
for route 504). For every vehicle trip with a GPS ping within REF_RADIUS_METERS
of that point, we record the timestamp of the ping closest to it (one approximate
"pass event" per trip — not a true stop arrival).
Within each (direction, local_date, local_hour) bucket, sorting consecutive
pass events and measuring the gap gives the observed inter-vehicle headway.

Date+hour partitioning fix
---------------------------
The 24-hour parquet window often spans two local calendar dates (late evening
on day one through late evening on day two). The partition key is
(direction_id, local_date, local_hour) — NOT just hour — to prevent LAG from
bridging midnight within an "hour 23" bucket.

METHODOLOGY — Scheduled headway
---------------------------------
Derived from GTFS stop_times.txt for trips active on the selected analysis date:
  • Filter trips by service_id using calendar.txt + calendar_dates.txt
  • First-stop departure time per trip → extract hour
  • Count trips per direction per hour → scheduled headway = 60 ÷ trip_count
Route 504 runs as 504A + 504B (both counted when active that day), giving total
scheduled corridor frequency. The same approach applies to any route.

GTFS alignment
----------------
The active realtime parquet should cover the same period as the static GTFS
feed (currently May–June 2026). Trip ID match rates are ~96% when aligned.
Rows with NULL trip_id cannot match trips.txt and are excluded from
direction-resolved headway analysis.

Reliability thresholds
-----------------------
  Bunching : headway <  3 min  (vehicles within ~2.5 scheduled intervals)
  Gap      : headway > 15 min  (wait more than ~10× scheduled frequency)
  Cap      : headway > 30 min  (treated as gap event, not a headway estimate)
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

_HERE = os.path.dirname(__file__)

# Frozen primary metrics (report / demo focus)
PRIMARY_METRICS = (
    "observed_headway",
    "scheduled_headway",
    "absolute_deviation",
    "relative_deviation",
)


def _trips_file() -> str:
    from utils.agency_loader import gtfs_file_path

    return gtfs_file_path("trips.txt")


def _stop_times_file() -> str:
    from utils.agency_loader import gtfs_file_path

    return gtfs_file_path("stop_times.txt")


def _positions_from(route_id: str | None = None, require_trip_id: bool = False) -> str:
    from utils.positions_store import positions_subquery

    return positions_subquery(route_id=route_id, require_trip_id=require_trip_id, alias="p")


def _positions_available() -> bool:
    from utils.positions_store import positions_available

    return positions_available()

# Default reference point — King St & Bay St (route 504).
# Always pass route-specific values explicitly for other routes.
REF_LAT      = 43.6476
REF_LON      = -79.3814

# Virtual-stop pass detection — single source of truth (see get_ref_radius_deg).
# Pass-event corridor radius (single tuning point).
# Target for stop-scale detection is ~150–250 m, but on the May 12 snapshot the nearest
# GPS pings to the Route 29 reference are ~606 m away; 670 m retains pass events while
# reducing the prior ~900 m window. See methodology / limitations in the UI.
REF_RADIUS_METERS = 670
REF_RADIUS_DEG    = REF_RADIUS_METERS / 111_320.0
MAX_DIST_DEG      = REF_RADIUS_DEG  # backward-compatible alias for callers

# Exploratory schedule-comparison bands (relative deviation |actual−scheduled| / scheduled)
ADHERENCE_BAND_GOOD     = 0.25
ADHERENCE_BAND_MODERATE = 0.50
MAX_REL_DEV_FOR_SCORE   = 1.0  # cap relative deviation at 100% for adherence score

# Reliability thresholds (minutes) — operational-style cutoffs for exploratory flags
BUNCHING_THRESHOLD_MIN = 3.0
GAP_THRESHOLD_MIN      = 15.0
CAP_HEADWAY_MIN        = 30.0


def get_ref_radius_deg() -> float:
    """Pass-event detection radius in degrees (configure REF_RADIUS_METERS above)."""
    return REF_RADIUS_DEG


def get_ref_radius_meters() -> int:
    return REF_RADIUS_METERS


def compute_schedule_comparison(
    scheduled_sec: pd.Series | np.ndarray,
    actual_sec: pd.Series | np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Deviation-based exploratory metrics (not official TTC KPIs).

    Returns abs_deviation_sec, relative_deviation, adherence_score (0–100),
    adherence_band (Good / Moderate / Poor).
    """
    sched = np.asarray(scheduled_sec, dtype=float)
    actual = np.asarray(actual_sec, dtype=float)
    abs_dev = np.abs(actual - sched)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_dev = np.where(sched > 0, abs_dev / sched, np.nan)
    rel_capped = np.minimum(np.nan_to_num(rel_dev, nan=MAX_REL_DEV_FOR_SCORE), MAX_REL_DEV_FOR_SCORE)
    score = np.where(
        np.isfinite(rel_dev),
        np.maximum(0.0, 100.0 * (1.0 - rel_capped)),
        np.nan,
    )
    band = np.where(
        rel_dev < ADHERENCE_BAND_GOOD,
        "Good",
        np.where(
            rel_dev <= ADHERENCE_BAND_MODERATE,
            "Moderate",
            np.where(rel_dev > ADHERENCE_BAND_MODERATE, "Poor", ""),
        ),
    )
    return {
        "abs_deviation_sec": abs_dev,
        "relative_deviation": rel_dev,
        "adherence_score": score,
        "adherence_band": band,
    }


# ── Data quality diagnostics ───────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def compute_data_quality(route_id: str) -> dict:
    """
    Return a dict of data quality stats:
      total_parquet_trips, matched_trips, match_pct,
      total_pings, t_start, t_end
    """
    trips_file = _trips_file()
    if not _positions_available() or not os.path.exists(trips_file):
        return {}

    from utils.positions_store import execute_query

    src_all = _positions_from(route_id=route_id, require_trip_id=False)
    pq = execute_query(
        f"""
        SELECT COUNT(DISTINCT CAST(trip_id AS VARCHAR)) AS total_trips,
               COUNT(*) AS total_pings,
               SUM(CASE WHEN trip_id IS NULL THEN 1 ELSE 0 END) AS null_rows,
               CAST(MIN(timestamp) AS VARCHAR) AS t_start,
               CAST(MAX(timestamp) AS VARCHAR) AS t_end
        FROM {src_all}
        """,
        label=f"data_quality_{route_id}",
    ).iloc[0]

    src_trips = _positions_from(route_id=route_id, require_trip_id=True)
    matched = execute_query(
        f"""
        WITH pq_trips AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id FROM {src_trips}
        )
        SELECT COUNT(*) AS matched
        FROM pq_trips p
        JOIN read_csv_auto('{trips_file}', all_varchar=true) t
            ON p.trip_id = CAST(t.trip_id AS VARCHAR)
        """,
        label=f"data_quality_match_{route_id}",
    ).iloc[0]["matched"]

    total = int(pq["total_trips"] or 1)
    pings = int(pq["total_pings"] or 0)
    null_rows = int(pq["null_rows"] or 0)
    matched_n = int(matched or 0)
    return {
        "total_parquet_trips": int(total),
        "matched_trips":       matched_n,
        "unmatched_trips":     int(total) - matched_n,
        "match_pct":           round(100 * matched_n / total, 1),
        "total_pings":         pings,
        "null_trip_pct":       round(100 * null_rows / pings, 1) if pings else None,
        "t_start":             str(pq["t_start"]),
        "t_end":               str(pq["t_end"]),
    }


# ── Observed headways ─────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def compute_observed_headways(
    route_id: str,
    ref_lat: float = REF_LAT,
    ref_lon: float = REF_LON,
    max_dist_deg: float = MAX_DIST_DEG,
) -> pd.DataFrame:
    """
    Estimate observed inter-vehicle headways at the given reference point.

    Returns columns:
      direction_id, local_date, hour, vehicle_id, trip_id,
      timestamp, headway_min, is_bunched, is_gap,
      headway_min_capped, direction_label
    Note: direction_label uses generic "Dir 0"/"Dir 1" labels.
    Callers should remap using route_config["directions"] for route-specific labels.
    """
    trips_file = _trips_file()
    if not _positions_available() or not os.path.exists(trips_file):
        return pd.DataFrame()

    from utils.agency_loader import agency_timezone
    from utils.positions_store import execute_query

    tz = agency_timezone().replace("'", "''")
    pos = _positions_from(route_id=route_id, require_trip_id=True)
    df = execute_query(
        f"""
            WITH parquet_with_dir AS (
                -- direction_id in parquet stores route_id, not 0/1.
                -- Correct direction recovered via trip_id → trips.txt join.
                SELECT
                    p.vehicle_id,
                    CAST(p.trip_id AS VARCHAR)      AS trip_id,
                    CAST(t.direction_id AS VARCHAR) AS direction_id,
                    p.timestamp,
                    SQRT(
                        POW(p.bbox.ymin - {ref_lat}, 2) +
                        POW(p.bbox.xmin - ({ref_lon}), 2)
                    )                               AS dist_deg
                FROM {pos}
                JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                    ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
            ),
            nearest_per_trip AS (
                -- One pass event per (vehicle, trip): ping closest to reference point
                SELECT vehicle_id, trip_id, direction_id, timestamp
                FROM parquet_with_dir
                WHERE dist_deg < {max_dist_deg}
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY vehicle_id, trip_id, direction_id
                    ORDER BY dist_deg
                ) = 1
            ),
            with_date_hour AS (
                SELECT
                    vehicle_id, trip_id, direction_id, timestamp,
                    DATE(timestamp AT TIME ZONE '{tz}')  AS local_date,
                    HOUR(timestamp AT TIME ZONE '{tz}')  AS hour
                FROM nearest_per_trip
            ),
            with_prev AS (
                -- Partition includes local_date to prevent LAG from spanning
                -- the two calendar dates present in this 24-h UTC window
                SELECT
                    direction_id, local_date, hour,
                    vehicle_id, trip_id, timestamp,
                    LAG(timestamp) OVER (
                        PARTITION BY direction_id, local_date, hour
                        ORDER BY timestamp
                    ) AS prev_ts
                FROM with_date_hour
            )
            SELECT
                direction_id, local_date, hour,
                vehicle_id, trip_id, timestamp,
                ROUND(DATEDIFF('second', prev_ts, timestamp) / 60.0, 2) AS headway_min
            FROM with_prev
            WHERE prev_ts IS NOT NULL
              AND DATEDIFF('second', prev_ts, timestamp) / 60.0 >= 0.5
            ORDER BY direction_id, local_date, hour, timestamp
        """,
        label=f"observed_headways_{route_id}",
    )

    if df.empty:
        return df

    # Flag events before capping
    df["is_gap"]     = df["headway_min"] > GAP_THRESHOLD_MIN
    df["is_bunched"] = (df["headway_min"] < BUNCHING_THRESHOLD_MIN) & ~df["is_gap"]
    df["headway_min_capped"] = df["headway_min"].clip(upper=CAP_HEADWAY_MIN)

    # Generic direction labels (callers should remap for route-specific N/S labels)
    df["direction_label"] = df["direction_id"].map(
        {"0": "Dir 0", "1": "Dir 1"}
    ).fillna("Unknown")
    return df


# ── Scheduled headways from GTFS ──────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _compute_scheduled_headways_cached(route_id: str, service_date: date) -> pd.DataFrame:
    """
    Count scheduled trips per direction per hour for trips active on service_date.

    Scheduled headway = 60 ÷ trip_count. All branch variants that run on the
    service day and pass the route are combined per direction/hour.
    """
    from utils.gtfs_loader import build_active_service_ids_sql

    trips_file = _trips_file().replace("'", "''")
    stop_times_file = _stop_times_file().replace("'", "''")
    if not os.path.exists(_trips_file()) or not os.path.exists(_stop_times_file()):
        return pd.DataFrame()

    rid = str(route_id).replace("'", "''")
    active_service = build_active_service_ids_sql(service_date)

    con = duckdb.connect()
    try:
        df = con.execute(f"""
            WITH active_service AS ({active_service}),
            route_trips AS (
                SELECT
                    CAST(t.trip_id AS VARCHAR)      AS trip_id,
                    CAST(t.direction_id AS VARCHAR) AS direction_id,
                    CAST(t.service_id AS VARCHAR)   AS service_id
                FROM read_csv_auto('{trips_file}', all_varchar=true) t
                WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
            ),
            active_trips AS (
                SELECT rt.trip_id, rt.direction_id
                FROM route_trips rt
                INNER JOIN active_service act_svc
                    ON rt.service_id = act_svc.service_id
            ),
            first_dep AS (
                SELECT CAST(st.trip_id AS VARCHAR) AS trip_id,
                       st.departure_time
                FROM read_csv_auto('{stop_times_file}', all_varchar=true) st
                INNER JOIN active_trips rt
                    ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY st.trip_id
                    ORDER BY CAST(st.stop_sequence AS INTEGER)
                ) = 1
            )
            SELECT
                act_t.direction_id,
                CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24
                    AS hour,
                COUNT(*)                    AS scheduled_trips,
                ROUND(60.0 / COUNT(*), 1)  AS scheduled_headway_min
            FROM first_dep fd
            JOIN active_trips act_t ON fd.trip_id = act_t.trip_id
            GROUP BY act_t.direction_id, hour
            ORDER BY act_t.direction_id, hour
        """).df()
    finally:
        con.close()

    if df.empty:
        return df

    df["direction_id"] = df["direction_id"].astype(str)
    df["direction_label"] = df["direction_id"].map(
        {"0": "Dir 0", "1": "Dir 1"}
    ).fillna("Unknown")
    return df


def compute_scheduled_headways(route_id: str) -> pd.DataFrame:
    """
    Scheduled headways for the selected analysis date (Streamlit snapshot date).

    Filters trips to service_ids active on that date via calendar.txt and
    calendar_dates.txt. See _compute_scheduled_headways_cached for details.
    """
    from utils.parquet_date import get_selected_date

    return _compute_scheduled_headways_cached(route_id, get_selected_date())


# ── Hourly reliability summary ─────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def compute_hourly_reliability(
    route_id: str,
    ref_lat: float = REF_LAT,
    ref_lon: float = REF_LON,
    max_dist_deg: float = MAX_DIST_DEG,
) -> pd.DataFrame:
    """
    Merge observed headways and scheduled headways into a per-hour summary.

    Uses headway_min_capped (≤ 30 min) for mean/median/std.
    direction_label uses generic "Dir 0"/"Dir 1" — remap in the caller.

    Columns returned:
      direction_id, direction_label, hour,
      scheduled_headway_min, scheduled_trips,
      mean_headway, median_headway, std_headway, cov_headway,
      n_observations, bunching_events, gap_events
    """
    obs = compute_observed_headways(route_id, ref_lat, ref_lon, max_dist_deg)
    sch = compute_scheduled_headways(route_id)

    if obs.empty:
        return pd.DataFrame()

    def _agg(g: pd.DataFrame) -> pd.Series:
        hw = g["headway_min_capped"]
        return pd.Series({
            "mean_headway":    round(hw.mean(), 1),
            "median_headway":  round(hw.median(), 1),
            "std_headway":     round(hw.std(), 2),
            "n_observations":  int(len(hw)),
            "bunching_events": int(g["is_bunched"].sum()),
            "gap_events":      int(g["is_gap"].sum()),
        })

    agg = obs.groupby(["direction_id", "hour"]).apply(_agg).reset_index()
    agg["cov_headway"] = (
        agg["std_headway"] / agg["mean_headway"].replace(0, np.nan)
    ).round(3)
    agg["direction_label"] = agg["direction_id"].map(
        {"0": "Dir 0", "1": "Dir 1"}
    ).fillna("Unknown")

    if not sch.empty:
        agg = agg.merge(
            sch[["direction_id", "hour", "scheduled_headway_min", "scheduled_trips"]],
            on=["direction_id", "hour"],
            how="left",
        )
    else:
        agg["scheduled_headway_min"] = np.nan
        agg["scheduled_trips"]       = np.nan

    # Exploratory schedule comparison (hourly mean observed vs scheduled)
    agg["abs_deviation_sec"] = np.nan
    agg["relative_deviation"] = np.nan
    agg["adherence_score"] = np.nan
    agg["adherence_band"] = pd.Series(dtype=object)
    agg["abs_headway_deviation_min"] = np.nan

    mask = agg["scheduled_headway_min"].notna() & agg["mean_headway"].notna()
    if mask.any():
        sched_sec = agg.loc[mask, "scheduled_headway_min"] * 60
        actual_sec = agg.loc[mask, "mean_headway"] * 60
        cmp_metrics = compute_schedule_comparison(sched_sec, actual_sec)
        agg.loc[mask, "abs_deviation_sec"] = cmp_metrics["abs_deviation_sec"]
        agg.loc[mask, "relative_deviation"] = cmp_metrics["relative_deviation"]
        agg.loc[mask, "adherence_score"] = cmp_metrics["adherence_score"]
        agg.loc[mask, "adherence_band"] = list(cmp_metrics["adherence_band"])
        agg.loc[mask, "abs_headway_deviation_min"] = agg.loc[mask, "abs_deviation_sec"] / 60

    return agg


# ── Network-wide headway table (Reliability page) ─────────────────────────────

def _parquet_snapshot_date() -> date:
    """Primary local calendar date from the active parquet (end of 24 h window)."""
    from utils.real_data import get_parquet_snapshot_info

    info = get_parquet_snapshot_info()
    if info.get("end_date") is not None:
        return info["end_date"]
    return date.today()


def _hourly_to_headway_metrics(hourly: pd.DataFrame, route_id: str) -> pd.DataFrame:
    """Map compute_hourly_reliability output to headway_metrics schema."""
    if hourly.empty:
        return pd.DataFrame()

    df = hourly.copy()
    df["route_id"] = str(route_id)
    df["direction_id"] = pd.to_numeric(df["direction_id"], errors="coerce").astype("Int64")
    df["scheduled_headway_sec"] = df["scheduled_headway_min"] * 60
    df["actual_headway_sec"] = df["mean_headway"] * 60
    df["headway_deviation_sec"] = df["actual_headway_sec"] - df["scheduled_headway_sec"]

    sched = df["scheduled_headway_sec"].values
    actual = df["actual_headway_sec"].values
    cmp_metrics = compute_schedule_comparison(sched, actual)
    df["abs_headway_deviation_sec"] = cmp_metrics["abs_deviation_sec"]
    df["relative_deviation"] = cmp_metrics["relative_deviation"]
    df["adherence_score"] = cmp_metrics["adherence_score"]
    df["adherence_band"] = cmp_metrics["adherence_band"]
    # Legacy column name used by charts — same as adherence_score
    df["on_time_pct"] = df["adherence_score"]
    df["date"] = _parquet_snapshot_date()

    return df[
        [
            "route_id",
            "direction_id",
            "hour",
            "date",
            "scheduled_headway_sec",
            "actual_headway_sec",
            "headway_deviation_sec",
            "abs_headway_deviation_sec",
            "relative_deviation",
            "adherence_score",
            "adherence_band",
            "on_time_pct",
        ]
    ]


@st.cache_data(ttl=600, show_spinner="Computing reliability metrics…")
def load_network_headway_metrics(h_min: int, h_max: int) -> pd.DataFrame:
    """
    Headway metrics for the Reliability page.

    Uses real GTFS-RT parquet + GTFS schedule for configured routes
    when positions_0.parquet is present. Falls back to DuckDB sample data
    otherwise.
    """
    from utils.real_data import parquet_available
    from utils.route_config import get_routes_for_agency

    if parquet_available():
        frames: list[pd.DataFrame] = []
        from utils.agency_loader import get_current_agency_id
        from utils.route_config import get_network_routes_for_agency

        for route_id, cfg in get_network_routes_for_agency(get_current_agency_id()).items():
            ref = cfg["ref_point"]
            radius = get_ref_radius_deg()
            hourly = compute_hourly_reliability(
                route_id,
                ref["lat"],
                ref["lon"],
                radius,
            )
            if not hourly.empty:
                frames.append(_hourly_to_headway_metrics(hourly, route_id))

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        return df[(df["hour"] >= h_min) & (df["hour"] <= h_max)].copy()

    from utils.db import get_connection

    con = get_connection()
    df = con.execute(
        f"""
        SELECT *
        FROM headway_metrics
        WHERE hour BETWEEN {h_min} AND {h_max}
        """
    ).df()
    con.close()

    if df.empty:
        from utils.sample_data import seed_headway_metrics

        seed_headway_metrics()
        con = get_connection()
        df = con.execute(
            f"""
            SELECT *
            FROM headway_metrics
            WHERE hour BETWEEN {h_min} AND {h_max}
            """
        ).df()
        con.close()

    return df


# ── Per-route summary for multi-route comparison ───────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def compute_route_summary_stats(
    route_id: str,
    ref_lat: float = REF_LAT,
    ref_lon: float = REF_LON,
    max_dist_deg: float = MAX_DIST_DEG,
) -> dict:
    """
    Lightweight per-route summary dict for the multi-route comparison page.
    Does NOT scan stop_times.txt — fast even for 4+ routes.

    Keys: route_id, n_vehicles, avg_speed_kmh, total_pings, match_pct,
          matched_trips, total_trips, n_headway_obs, mean_headway,
          median_headway, cov_headway, bunching_events, gap_events
    """
    if not _positions_available():
        return {}

    from utils.positions_store import execute_query

    dq  = compute_data_quality(route_id)
    obs = compute_observed_headways(route_id, ref_lat, ref_lon, max_dist_deg)

    src = _positions_from(route_id=route_id)
    row = execute_query(
        f"""
        SELECT COUNT(DISTINCT vehicle_id) AS n_vehicles,
               ROUND(AVG(speed) * 3.6, 1) AS avg_speed_kmh,
               COUNT(*) AS total_pings
        FROM {src}
        """,
        label=f"route_summary_stats_{route_id}",
    ).iloc[0]

    hw       = obs["headway_min_capped"] if not obs.empty else pd.Series(dtype=float)
    mean_hw  = round(float(hw.mean()), 1)  if len(hw) > 0 else None
    med_hw   = round(float(hw.median()), 1) if len(hw) > 0 else None
    cov_hw   = (round(float(hw.std() / hw.mean()), 2)
                if len(hw) > 0 and hw.mean() > 0 else None)

    return {
        "route_id":        route_id,
        "n_vehicles":      int(row["n_vehicles"] or 0),
        "avg_speed_kmh":   float(row["avg_speed_kmh"] or 0),
        "total_pings":     int(row["total_pings"] or 0),
        "match_pct":       dq.get("match_pct", 0.0),
        "matched_trips":   dq.get("matched_trips", 0),
        "total_trips":     dq.get("total_parquet_trips", 0),
        "n_headway_obs":   len(obs),
        "mean_headway":    mean_hw,
        "median_headway":  med_hw,
        "cov_headway":     cov_hw,
        "bunching_events": int(obs["is_bunched"].sum()) if not obs.empty else 0,
        "gap_events":      int(obs["is_gap"].sum())     if not obs.empty else 0,
    }
