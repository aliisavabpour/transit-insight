"""
Real TTC data loader.
Queries GTFS-RT parquet via DuckDB (S3 httpfs by default, optional local cache).
Lat/lon from bbox: bbox.xmin = longitude, bbox.ymin = latitude.
"""
import os

import numpy as np
import pandas as pd
import streamlit as st

from utils.agency_loader import agency_timezone, get_current_agency_id, gtfs_file_path
from utils.gtfs_loader import get_routes_dict, gtfs_available
from utils.positions_store import (
    execute_query,
    positions_available,
    positions_subquery,
    positions_where_clause,
    read_parquet_expr,
    source_caption as _store_source_caption,
)
from utils.parquet_date import get_selected_date
from utils.speed_utils import apply_effective_speed_kmh, collapse_latest_per_vehicle

# Streamlit cache keys must include agency/day/source (session state is not hashed).
CacheScope = tuple[str, str, str]


def cache_scope() -> CacheScope:
    from utils.positions_store import get_data_source

    return (get_current_agency_id(), get_selected_date().isoformat(), get_data_source())

# Backward-compatible path helper (local cache path or S3 glob string).
def get_parquet_path() -> str:
    from utils.positions_store import positions_uri

    return positions_uri()


_ROUTES_FALLBACK = {
    "501": "Queen",        "504": "King",         "505": "Dundas",
    "506": "Carlton",      "510": "Spadina",       "511": "Bathurst",
    "512": "St. Clair",    "29":  "Dufferin",      "35":  "Jane",
    "36":  "Finch West",   "39":  "Finch East",    "52":  "Lawrence West",
    "54":  "Lawrence East","63":  "Ossington",     "72":  "Pape",
    "85":  "Sheppard East","86":  "Scarborough",   "95":  "York Mills",
    "96":  "Wilson",       "100": "Flemingdon Pk", "102": "Markham Rd",
    "165": "Weston Rd",    "169": "Huntingwood",   "927": "Highway 27",
    "939": "Finch Express",
}

TTC_ROUTES = _ROUTES_FALLBACK


@st.cache_data(ttl=3600, show_spinner=False)
def _get_routes_lookup() -> dict[str, str]:
    if gtfs_available():
        return get_routes_dict()
    if get_current_agency_id() == "ttc":
        return _ROUTES_FALLBACK
    return {}


def parquet_available() -> bool:
    return positions_available()


def _gtfs_trips_path() -> str:
    return gtfs_file_path("trips.txt")


def _format_date_label(start_d, end_d) -> str:
    if start_d == end_d:
        return f"{start_d.strftime('%B')} {start_d.day}, {start_d.year}"
    if start_d.month == end_d.month and start_d.year == end_d.year:
        return f"{start_d.strftime('%B')} {start_d.day}–{end_d.day}, {end_d.year}"
    return f"{start_d.strftime('%b %d %Y')} – {end_d.strftime('%b %d %Y')}"


@st.cache_data(ttl=3600, show_spinner=False)
def get_parquet_snapshot_info() -> dict:
    if not parquet_available():
        return {
            "available": False,
            "date_label": "no parquet loaded",
            "start_date": None,
            "end_date": None,
            "t_min": None,
            "t_max": None,
            "match_pct": None,
            "null_trip_pct": None,
            "total_trips": None,
            "matched_trips": None,
            "unmatched_trips": None,
        }

    tz = agency_timezone().replace("'", "''")
    scan = read_parquet_expr()
    row = execute_query(
        f"""
        SELECT
            MIN(DATE(timestamp AT TIME ZONE '{tz}')) AS start_d,
            MAX(DATE(timestamp AT TIME ZONE '{tz}')) AS end_d,
            CAST(MIN(timestamp AT TIME ZONE '{tz}') AS VARCHAR) AS t_min,
            CAST(MAX(timestamp AT TIME ZONE '{tz}') AS VARCHAR) AS t_max
        FROM {scan}
        """,
        label="snapshot_info_range",
    ).iloc[0]

    start_d, end_d = row["start_d"], row["end_d"]
    match_pct = None
    total_trips = None
    matched_trips = None
    unmatched_trips = None
    trips_path = _gtfs_trips_path().replace("'", "''")
    if os.path.exists(_gtfs_trips_path()):
        pq = positions_subquery(require_trip_id=True, alias="pq")
        m = execute_query(
            f"""
            WITH pq AS (
                SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id FROM {pq}
            )
            SELECT
                (SELECT COUNT(*) FROM pq) AS total,
                (SELECT COUNT(*) FROM pq p
                 INNER JOIN read_csv_auto('{trips_path}', all_varchar=true) t
                   ON p.trip_id = CAST(t.trip_id AS VARCHAR)) AS matched
            """,
            label="snapshot_info_match",
        ).iloc[0]
        if m["total"]:
            total_trips = int(m["total"])
            matched_trips = int(m["matched"])
            unmatched_trips = total_trips - matched_trips
            match_pct = round(100 * matched_trips / total_trips, 1)
    null_trip_pct = None
    n = execute_query(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN trip_id IS NULL THEN 1 ELSE 0 END) AS null_rows
        FROM {scan}
        """,
        label="snapshot_info_nulls",
    ).iloc[0]
    if n["total_rows"]:
        null_trip_pct = round(100 * n["null_rows"] / n["total_rows"], 1)

    return {
        "available": True,
        "date_label": _format_date_label(start_d, end_d),
        "start_date": start_d,
        "end_date": end_d,
        "t_min": row["t_min"],
        "t_max": row["t_max"],
        "match_pct": match_pct,
        "null_trip_pct": null_trip_pct,
        "total_trips": total_trips,
        "matched_trips": matched_trips,
        "unmatched_trips": unmatched_trips,
    }


def snapshot_source_caption() -> str:
    if not parquet_available():
        return "GTFS-RT parquet not loaded for selected agency/day"
    from utils.diagnostics_display import format_analysis_day_label, format_gps_coverage_range
    from utils.parquet_date import get_selected_date

    info = get_parquet_snapshot_info()
    analysis = format_analysis_day_label(get_selected_date())
    gps = format_gps_coverage_range(info.get("t_min"), info.get("t_max"))
    return f"{_store_source_caption()} · Analysis day: {analysis} · GPS coverage: {gps}"


def snapshot_match_note() -> str:
    info = get_parquet_snapshot_info()
    if not info["available"] or info["match_pct"] is None:
        return (
            "Realtime parquet and GTFS static feed should cover the same service period."
        )
    return (
        f"Realtime parquet is aligned with the GTFS static feed (May–June 2026). "
        f"Trip ID match rate is ~{info['match_pct']:.0f}%."
    )


def _attach_effective_route_speeds(summary: pd.DataFrame, scope: CacheScope) -> pd.DataFrame:
    """Add effective_avg/max_speed_kmh (derived for TransLink, source otherwise)."""
    summary = summary.copy()
    if summary.empty:
        summary["effective_avg_speed_kmh"] = pd.Series(dtype=float)
        summary["effective_max_speed_kmh"] = pd.Series(dtype=float)
        return summary

    if not agency_needs_derived_speed(scope):
        summary["effective_avg_speed_kmh"] = summary["avg_speed_kmh"]
        summary["effective_max_speed_kmh"] = summary["max_speed_kmh"]
        return summary

    scan = read_parquet_expr()
    df = execute_query(
        f"""
        SELECT
            CAST(route_id AS VARCHAR) AS route_id,
            vehicle_id,
            timestamp,
            bbox.ymin AS latitude,
            bbox.xmin AS longitude,
            ROUND(speed * 3.6, 2) AS speed_kmh
        FROM {scan}
        WHERE route_id IS NOT NULL
        ORDER BY vehicle_id, timestamp
        """,
        label="derived_speed_by_route",
    )
    if df.empty:
        summary["effective_avg_speed_kmh"] = np.nan
        summary["effective_max_speed_kmh"] = np.nan
        return summary

    df = apply_effective_speed_kmh(df, use_derived=True)
    agg = df.groupby("route_id", as_index=False)["effective_speed_kmh"].agg(
        effective_avg_speed_kmh=lambda s: round(float(s.mean()), 1) if s.notna().any() else np.nan,
        effective_max_speed_kmh=lambda s: round(float(s.max()), 1) if s.notna().any() else np.nan,
    )
    summary["route_id"] = summary["route_id"].astype(str)
    agg["route_id"] = agg["route_id"].astype(str)
    summary = summary.drop(columns=["effective_avg_speed_kmh", "effective_max_speed_kmh"], errors="ignore")
    return summary.merge(agg, on="route_id", how="left")


@st.cache_data(ttl=300, show_spinner=False)
def load_route_summary(_scope: CacheScope) -> pd.DataFrame:
    scan = read_parquet_expr()
    df = execute_query(
        f"""
        SELECT
            route_id,
            COUNT(*)                              AS records,
            COUNT(DISTINCT vehicle_id)            AS vehicles,
            ROUND(AVG(speed) * 3.6, 1)            AS avg_speed_kmh,
            ROUND(MAX(speed) * 3.6, 1)            AS max_speed_kmh,
            MIN(timestamp)::TIMESTAMPTZ           AS first_seen,
            MAX(timestamp)::TIMESTAMPTZ           AS last_seen
        FROM {scan}
        WHERE route_id IS NOT NULL
        GROUP BY route_id
        ORDER BY vehicles DESC
        """,
        label="route_summary",
    )
    routes = _get_routes_lookup()
    df["route_name"] = df["route_id"].map(routes).fillna("Unknown")
    return _attach_effective_route_speeds(df, _scope)


@st.cache_data(ttl=300, show_spinner=False)
def agency_needs_derived_speed(_scope: CacheScope) -> bool:
    """
    True when the agency parquet has no usable source speed (TransLink only today).
    """
    aid = _scope[0]
    if aid != "translink":
        return False
    if not parquet_available():
        return False
    scan = read_parquet_expr()
    row = execute_query(
        f"""
        SELECT
            COUNT(*) AS n,
            SUM(CASE WHEN speed IS NOT NULL AND speed > 0 THEN 1 ELSE 0 END) AS positive
        FROM {scan}
        """,
        label="source_speed_probe",
    ).iloc[0]
    if int(row["n"] or 0) == 0:
        return False
    return int(row["positive"] or 0) == 0


@st.cache_data(ttl=60, show_spinner=False)
def load_realtime_positions(
    route_id: str,
    latest_only: bool,
    _scope: CacheScope,
) -> pd.DataFrame:
    """
    Positions for the Realtime page with effective_speed_kmh.

    TransLink: derives speed from consecutive GPS when source speed is all zero.
    TTC / Edmonton: effective_speed_kmh equals parquet speed (unchanged).
    """
    use_derived = agency_needs_derived_speed(_scope)
    if not use_derived:
        df = load_route_positions(route_id, latest_only, _scope)
        if df.empty:
            return df
        return apply_effective_speed_kmh(df, use_derived=False)

    df = load_route_positions(route_id, False, _scope)
    if df.empty:
        return df
    df = df.sort_values(["vehicle_id", "timestamp"])
    df = apply_effective_speed_kmh(df, use_derived=True)
    if latest_only:
        df = collapse_latest_per_vehicle(df)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_realtime_route_summary(_scope: CacheScope) -> pd.DataFrame:
    """Route summary with effective_avg/max_speed_kmh (alias of load_route_summary)."""
    return load_route_summary(_scope)


@st.cache_data(ttl=600, show_spinner=False)
def load_route_centroid(route_id: str, _scope: CacheScope) -> dict | None:
    """Mean GPS position for a route (fallback reference point for network metrics)."""
    scan = read_parquet_expr()
    where = positions_where_clause(route_id=route_id)
    row = execute_query(
        f"""
        SELECT
            AVG(bbox.ymin) AS lat,
            AVG(bbox.xmin) AS lon
        FROM {scan}
        WHERE {where}
        """,
        label=f"route_centroid_{route_id}",
    )
    if row.empty or row.iloc[0]["lat"] is None:
        return None
    r = row.iloc[0]
    return {
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "label": f"GPS centroid (route {route_id})",
    }


@st.cache_data(ttl=60, show_spinner=False)
def load_route_positions(route_id: str, latest_only: bool, _scope: CacheScope) -> pd.DataFrame:
    # QUALIFY must run on read_parquet directly (DuckDB fails on nested bbox struct).
    scan = read_parquet_expr()
    where = positions_where_clause(route_id=route_id)
    if latest_only:
        return execute_query(
            f"""
            SELECT
                route_id,
                direction_id,
                vehicle_id,
                ROUND(bearing, 1)           AS bearing,
                ROUND(speed * 3.6, 2)       AS speed_kmh,
                timestamp,
                bbox.xmin                   AS longitude,
                bbox.ymin                   AS latitude
            FROM {scan}
            WHERE {where}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY vehicle_id ORDER BY timestamp DESC
            ) = 1
            """,
            label=f"route_positions_{route_id}",
        )
    return execute_query(
        f"""
        SELECT
            route_id,
            direction_id,
            vehicle_id,
            ROUND(bearing, 1)           AS bearing,
            ROUND(speed * 3.6, 2)       AS speed_kmh,
            timestamp,
            bbox.xmin                   AS longitude,
            bbox.ymin                   AS latitude
        FROM {scan}
        WHERE {where}
        ORDER BY timestamp
        """,
        label=f"route_positions_all_{route_id}",
    )


@st.cache_data(ttl=120, show_spinner=False)
def load_hourly_activity(route_id: str) -> pd.DataFrame:
    tz = agency_timezone().replace("'", "''")
    src = positions_subquery(route_id=route_id, alias="p")
    return execute_query(
        f"""
        SELECT
            HOUR(timestamp AT TIME ZONE '{tz}')  AS hour,
            COUNT(DISTINCT vehicle_id)                      AS active_vehicles,
            ROUND(AVG(speed) * 3.6, 1)                     AS avg_speed_kmh,
            COUNT(*)                                        AS pings
        FROM {src}
        GROUP BY 1
        ORDER BY 1
        """,
        label=f"hourly_activity_{route_id}",
    )


@st.cache_data(ttl=120, show_spinner=False)
def load_vehicle_traces(route_id: str, vehicle_ids: list[str]) -> pd.DataFrame:
    if not vehicle_ids:
        return pd.DataFrame()
    ids = ", ".join(f"'{v}'" for v in vehicle_ids)
    scan = read_parquet_expr()
    where = positions_where_clause(route_id=route_id)
    return execute_query(
        f"""
        SELECT
            vehicle_id,
            direction_id,
            ROUND(speed * 3.6, 2)   AS speed_kmh,
            timestamp,
            bbox.xmin               AS longitude,
            bbox.ymin               AS latitude
        FROM {scan}
        WHERE {where} AND vehicle_id IN ({ids})
        ORDER BY vehicle_id, timestamp
        """,
        label=f"vehicle_traces_{route_id}",
    )


@st.cache_data(ttl=120, show_spinner=False)
def load_speed_percentiles(route_id: str) -> pd.DataFrame:
    tz = agency_timezone().replace("'", "''")
    src = positions_subquery(route_id=route_id, alias="p")
    return execute_query(
        f"""
        SELECT
            HOUR(timestamp AT TIME ZONE '{tz}')  AS hour,
            ROUND(QUANTILE_CONT(speed * 3.6, 0.10), 1)     AS p10_kmh,
            ROUND(QUANTILE_CONT(speed * 3.6, 0.25), 1)     AS p25_kmh,
            ROUND(QUANTILE_CONT(speed * 3.6, 0.50), 1)     AS p50_kmh,
            ROUND(QUANTILE_CONT(speed * 3.6, 0.75), 1)     AS p75_kmh,
            ROUND(QUANTILE_CONT(speed * 3.6, 0.90), 1)     AS p90_kmh
        FROM {src}
        GROUP BY 1
        ORDER BY 1
        """,
        label=f"speed_percentiles_{route_id}",
    )
