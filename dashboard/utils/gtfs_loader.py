"""
GTFS static feed loader (multi-agency).

Reads routes.txt, trips.txt, stops.txt, stop_times.txt from the active agency's
gtfs_dir (see utils/agency_config.py).
"""
from __future__ import annotations

import os
from datetime import date

import duckdb
import pandas as pd
import streamlit as st

from utils.agency_loader import get_current_agency_id, gtfs_dir, gtfs_file_path

_DOW_COLS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _esc_sql_path(path: str) -> str:
    return path.replace("\\", "/").replace("'", "''")


def build_active_service_ids_sql(
    service_date: date,
    agency_id: str | None = None,
) -> str:
    """
    SQL subquery returning service_id values active on service_date.

    Combines calendar.txt day-of-week rules with calendar_dates.txt exceptions
    (type 1 = added, type 2 = removed). Supports calendar_dates-only feeds.
    """
    aid = agency_id or get_current_agency_id()
    calendar = gtfs_file_path("calendar.txt", aid)
    calendar_dates = gtfs_file_path("calendar_dates.txt", aid)
    di = int(service_date.strftime("%Y%m%d"))
    dow = _DOW_COLS[service_date.weekday()]

    parts: list[str] = []
    if os.path.exists(calendar):
        cal_esc = _esc_sql_path(calendar)
        parts.append(f"""
            SELECT CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{cal_esc}', all_varchar=true)
            WHERE CAST(start_date AS INTEGER) <= {di}
              AND CAST(end_date AS INTEGER) >= {di}
              AND CAST({dow} AS INTEGER) = 1
        """)
    if os.path.exists(calendar_dates):
        cd_esc = _esc_sql_path(calendar_dates)
        parts.append(f"""
            SELECT CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{cd_esc}', all_varchar=true)
            WHERE CAST(date AS INTEGER) = {di}
              AND CAST(exception_type AS INTEGER) = 1
        """)
    if not parts:
        return "SELECT CAST(NULL AS VARCHAR) AS service_id WHERE false"

    union = " UNION ".join(parts)
    if os.path.exists(calendar_dates):
        cd_esc = _esc_sql_path(calendar_dates)
        removed = f"""
            SELECT CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{cd_esc}', all_varchar=true)
            WHERE CAST(date AS INTEGER) = {di}
              AND CAST(exception_type AS INTEGER) = 2
        """
        return f"""
            SELECT service_id FROM ({union}) AS added
            WHERE service_id NOT IN ({removed})
        """
    return union


def _paths(agency_id: str | None = None) -> dict[str, str]:
    aid = agency_id or get_current_agency_id()
    return {
        "routes": gtfs_file_path("routes.txt", aid),
        "trips": gtfs_file_path("trips.txt", aid),
        "stops": gtfs_file_path("stops.txt", aid),
        "stop_times": gtfs_file_path("stop_times.txt", aid),
        "calendar": gtfs_file_path("calendar.txt", aid),
        "dir": gtfs_dir(aid),
    }


def gtfs_available(agency_id: str | None = None) -> bool:
    p = _paths(agency_id)
    return all(os.path.exists(f) for f in [p["routes"], p["trips"], p["stops"]])


@st.cache_data(ttl=3600, show_spinner=False)
def load_routes(agency_id: str | None = None) -> pd.DataFrame:
    routes_file = _paths(agency_id)["routes"]
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT
            CAST(route_id AS VARCHAR)           AS route_id,
            route_short_name,
            route_long_name,
            route_type,
            COALESCE(route_color, 'ED1C24')     AS route_color
        FROM read_csv_auto('{routes_file}', all_varchar=true)
        ORDER BY TRY_CAST(route_short_name AS INTEGER) NULLS LAST, route_short_name
    """).df()
    con.close()
    return df


def get_routes_dict(agency_id: str | None = None) -> dict[str, str]:
    p = _paths(agency_id)
    if not os.path.exists(p["routes"]):
        return {}
    df = load_routes(agency_id)
    return dict(zip(df["route_id"].astype(str), df["route_long_name"]))


@st.cache_data(ttl=3600, show_spinner=False)
def load_trips_for_route(route_id: str, agency_id: str | None = None) -> pd.DataFrame:
    trips_file = _paths(agency_id)["trips"]
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT
            CAST(trip_id AS VARCHAR)        AS trip_id,
            CAST(route_id AS VARCHAR)       AS route_id,
            CAST(service_id AS VARCHAR)     AS service_id,
            trip_headsign,
            CAST(direction_id AS VARCHAR)   AS direction_id,
            CAST(shape_id AS VARCHAR)       AS shape_id
        FROM read_csv_auto('{trips_file}', all_varchar=true)
        WHERE CAST(route_id AS VARCHAR) = '{route_id}'
    """).df()
    con.close()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_stop_sequence(trip_id: str, agency_id: str | None = None) -> pd.DataFrame:
    p = _paths(agency_id)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT
            st.stop_sequence,
            st.arrival_time,
            st.departure_time,
            CAST(st.stop_id AS VARCHAR)         AS stop_id,
            COALESCE(s.stop_name, 'Unknown')    AS stop_name,
            TRY_CAST(s.stop_lat AS DOUBLE)          AS stop_lat,
            TRY_CAST(s.stop_lon AS DOUBLE)          AS stop_lon
        FROM read_csv_auto('{p["stop_times"]}', all_varchar=true) st
        LEFT JOIN read_csv_auto('{p["stops"]}', all_varchar=true) s
            ON CAST(st.stop_id AS VARCHAR) = CAST(s.stop_id AS VARCHAR)
        WHERE CAST(st.trip_id AS VARCHAR) = '{trip_id}'
        ORDER BY st.stop_sequence
    """).df()
    con.close()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_trip_summary_for_route(route_id: str, agency_id: str | None = None) -> pd.DataFrame:
    trips = load_trips_for_route(route_id, agency_id)
    if trips.empty:
        return pd.DataFrame()

    summary = (
        trips.groupby("direction_id")
        .agg(
            trip_count=("trip_id", "count"),
            unique_headsigns=("trip_headsign", "nunique"),
            shapes=("shape_id", "nunique"),
            sample_headsign=("trip_headsign", "first"),
        )
        .reset_index()
    )
    return summary


@st.cache_data(ttl=3600, show_spinner=False)
def load_feed_date_range(agency_id: str | None = None) -> tuple[str, str]:
    calendar_file = _paths(agency_id)["calendar"]
    if not os.path.exists(calendar_file):
        return ("—", "—")
    con = duckdb.connect()
    row = con.execute(f"""
        SELECT
            MIN(CAST(start_date AS VARCHAR)) AS start_date,
            MAX(CAST(end_date   AS VARCHAR)) AS end_date
        FROM read_csv_auto('{calendar_file}', all_varchar=true)
    """).fetchone()
    con.close()
    return (str(row[0]), str(row[1]))
