"""
Corridor-based reference points for multi-agency reliability.

Uses GTFS shapes.txt to place virtual-stop reference points on the transit
corridor instead of geographic GPS centroids. Optionally refines the candidate
shape vertex using realtime ping density when parquet is available.
"""
from __future__ import annotations

import os

import duckdb
import streamlit as st

from utils.agency_loader import get_current_agency_id, gtfs_file_path
from utils.reliability import REF_RADIUS_METERS, get_ref_radius_deg

_MAX_SHAPE_SAMPLES = 40


def _esc(path: str) -> str:
    return path.replace("\\", "/").replace("'", "''")


def _esc_route_id(route_id: str) -> str:
    rid = str(route_id).replace("'", "''")
    if not rid.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid route_id: {route_id!r}")
    return rid


def shapes_available(agency_id: str | None = None) -> bool:
    aid = agency_id or get_current_agency_id()
    return os.path.exists(gtfs_file_path("shapes.txt", aid))


@st.cache_data(ttl=3600, show_spinner=False)
def load_route_corridor_ref(
    route_id: str,
    agency_id: str | None = None,
) -> dict | None:
    """
    Reference point on the route corridor from GTFS shapes.

    1. Pick dominant shape_id for the route (by trip count in trips.txt).
    2. Sample vertices along the shape polyline.
    3. When parquet is available, pick the vertex with the most GPS pings
       within the pass-event radius; otherwise use the median-sequence vertex.

    Falls back to the busiest stop on the route when shapes are unavailable.
    """
    aid = agency_id or get_current_agency_id()
    rid = _esc_route_id(route_id)
    trips_file = _esc(gtfs_file_path("trips.txt", aid))
    shapes_file = gtfs_file_path("shapes.txt", aid)

    if not os.path.exists(shapes_file):
        return _busiest_stop_ref(route_id, aid)

    con = duckdb.connect()
    try:
        shape_row = con.execute(f"""
            SELECT CAST(shape_id AS VARCHAR) AS shape_id, COUNT(*) AS trip_count
            FROM read_csv_auto('{trips_file}', all_varchar=true)
            WHERE CAST(route_id AS VARCHAR) = '{rid}'
              AND shape_id IS NOT NULL
              AND TRIM(CAST(shape_id AS VARCHAR)) != ''
            GROUP BY 1
            ORDER BY trip_count DESC
            LIMIT 1
        """).fetchone()
        if not shape_row or not shape_row[0]:
            return _busiest_stop_ref(route_id, aid)

        shape_id = str(shape_row[0]).replace("'", "''")
        shapes_esc = _esc(shapes_file)

        median_pt = con.execute(f"""
            WITH pts AS (
                SELECT
                    TRY_CAST(shape_pt_lat AS DOUBLE) AS lat,
                    TRY_CAST(shape_pt_lon AS DOUBLE) AS lon,
                    TRY_CAST(shape_pt_sequence AS INTEGER) AS seq
                FROM read_csv_auto('{shapes_esc}', all_varchar=true)
                WHERE CAST(shape_id AS VARCHAR) = '{shape_id}'
                  AND shape_pt_lat IS NOT NULL
                  AND shape_pt_lon IS NOT NULL
            ),
            med AS (
                SELECT APPROX_QUANTILE(seq, 0.5) AS mid_seq FROM pts
            )
            SELECT p.lat, p.lon, p.seq
            FROM pts p
            CROSS JOIN med m
            ORDER BY ABS(p.seq - m.mid_seq), p.seq
            LIMIT 1
        """).fetchone()
        if not median_pt or median_pt[0] is None:
            return _busiest_stop_ref(route_id, aid)

        lat, lon = float(median_pt[0]), float(median_pt[1])
        source = "shape_median"
        label = f"Shape corridor (route {route_id}, shape {shape_row[0]})"

        refined = _refine_with_gps(route_id, shape_id, shapes_esc, aid)
        if refined is not None:
            lat, lon, ping_score = refined
            source = "shape_gps_refined"
            label = (
                f"Shape corridor + GPS (route {route_id}, shape {shape_row[0]}, "
                f"{ping_score:,} pings)"
            )

        return {
            "lat": lat,
            "lon": lon,
            "label": label,
            "source": source,
            "shape_id": str(shape_row[0]),
        }
    finally:
        con.close()


def _refine_with_gps(
    route_id: str,
    shape_id: str,
    shapes_esc: str,
    agency_id: str,
) -> tuple[float, float, int] | None:
    """Pick shape vertex with highest GPS ping count within ref radius."""
    from utils.positions_store import execute_query, positions_available, positions_subquery

    if not positions_available():
        return None

    rid = _esc_route_id(route_id)
    max_deg = get_ref_radius_deg()
    pos = positions_subquery(route_id=route_id, require_trip_id=False)

    row = execute_query(
        f"""
        WITH pts AS (
            SELECT
                TRY_CAST(shape_pt_lat AS DOUBLE) AS lat,
                TRY_CAST(shape_pt_lon AS DOUBLE) AS lon,
                TRY_CAST(shape_pt_sequence AS INTEGER) AS seq
            FROM read_csv_auto('{shapes_esc}', all_varchar=true)
            WHERE CAST(shape_id AS VARCHAR) = '{shape_id.replace("'", "''")}'
              AND shape_pt_lat IS NOT NULL
              AND shape_pt_lon IS NOT NULL
        ),
        numbered AS (
            SELECT
                lat, lon, seq,
                ROW_NUMBER() OVER (ORDER BY seq) AS rn,
                COUNT(*) OVER () AS total
            FROM pts
        ),
        sampled AS (
            SELECT lat, lon
            FROM numbered
            WHERE rn = 1
               OR rn = total
               OR rn % GREATEST(1, total / {_MAX_SHAPE_SAMPLES}) = 0
        ),
        gps AS (
            SELECT p.bbox.ymin AS lat, p.bbox.xmin AS lon
            FROM {pos}
        ),
        scored AS (
            SELECT
                s.lat,
                s.lon,
                COUNT(*) AS ping_score
            FROM sampled s
            INNER JOIN gps g
                ON SQRT(POW(g.lat - s.lat, 2) + POW(g.lon - s.lon, 2)) < {max_deg}
            GROUP BY s.lat, s.lon
        )
        SELECT lat, lon, ping_score
        FROM scored
        ORDER BY ping_score DESC
        LIMIT 1
        """,
        label=f"corridor_ref_gps_{agency_id}_{route_id}",
    )
    if row.empty or row.iloc[0]["ping_score"] is None or int(row.iloc[0]["ping_score"]) == 0:
        return None
    r = row.iloc[0]
    return float(r["lat"]), float(r["lon"]), int(r["ping_score"])


def _busiest_stop_ref(route_id: str, agency_id: str) -> dict | None:
    """Fallback: stop with the most scheduled visits for the route."""
    rid = _esc_route_id(route_id)
    trips_file = _esc(gtfs_file_path("trips.txt", agency_id))
    stops_file = _esc(gtfs_file_path("stops.txt", agency_id))
    stop_times_file = _esc(gtfs_file_path("stop_times.txt", agency_id))

    if not all(os.path.exists(p) for p in [trips_file, stops_file, stop_times_file]):
        return None

    con = duckdb.connect()
    try:
        row = con.execute(f"""
            WITH route_trips AS (
                SELECT CAST(trip_id AS VARCHAR) AS trip_id
                FROM read_csv_auto('{trips_file}', all_varchar=true)
                WHERE CAST(route_id AS VARCHAR) = '{rid}'
            ),
            stop_hits AS (
                SELECT CAST(st.stop_id AS VARCHAR) AS stop_id, COUNT(*) AS hits
                FROM read_csv_auto('{stop_times_file}', all_varchar=true) st
                INNER JOIN route_trips rt
                    ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
                GROUP BY 1
            )
            SELECT
                TRY_CAST(s.stop_lat AS DOUBLE) AS lat,
                TRY_CAST(s.stop_lon AS DOUBLE) AS lon,
                s.stop_name,
                h.hits
            FROM stop_hits h
            INNER JOIN read_csv_auto('{stops_file}', all_varchar=true) s
                ON CAST(s.stop_id AS VARCHAR) = h.stop_id
            WHERE s.stop_lat IS NOT NULL AND s.stop_lon IS NOT NULL
            ORDER BY h.hits DESC
            LIMIT 1
        """).fetchone()
    finally:
        con.close()

    if not row or row[0] is None:
        return None
    name = str(row[2] or "stop")
    return {
        "lat": float(row[0]),
        "lon": float(row[1]),
        "label": f"Busiest stop (route {route_id}: {name})",
        "source": "busiest_stop",
        "shape_id": None,
    }


def min_gps_distance_m(route_id: str, ref_lat: float, ref_lon: float) -> float | None:
    """Minimum distance (m) from any GPS ping on the route to a reference point."""
    from utils.positions_store import execute_query, positions_available, positions_subquery

    if not positions_available():
        return None

    pos = positions_subquery(route_id=route_id, require_trip_id=False)
    row = execute_query(
        f"""
        SELECT ROUND(
            MIN(SQRT(POW(bbox.ymin - {ref_lat}, 2) + POW(bbox.xmin - ({ref_lon}), 2))) * 111320,
            1
        ) AS min_dist_m
        FROM {pos}
        """,
        label=f"min_gps_dist_{route_id}",
    )
    if row.empty or row.iloc[0]["min_dist_m"] is None:
        return None
    return float(row.iloc[0]["min_dist_m"])


def count_pass_events(route_id: str, ref_lat: float, ref_lon: float) -> int:
    """Pass-event count for a reference point (production virtual-stop logic)."""
    from utils.agency_loader import gtfs_file_path
    from utils.positions_store import execute_query, positions_available, positions_subquery

    if not positions_available():
        return 0

    max_deg = get_ref_radius_deg()
    trips_file = _esc(gtfs_file_path("trips.txt"))
    rid = _esc_route_id(route_id)
    pos = positions_subquery(route_id=route_id, require_trip_id=True)

    row = execute_query(
        f"""
        WITH pq AS (
            SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   SQRT(POW(p.bbox.ymin - {ref_lat}, 2) + POW(p.bbox.xmin - ({ref_lon}), 2)) AS dist_deg
            FROM {pos}
            INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        )
        SELECT COUNT(*) AS pass_events
        FROM (
            SELECT 1
            FROM pq
            WHERE dist_deg < {max_deg}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY vehicle_id, trip_id, direction_id ORDER BY dist_deg
            ) = 1
        )
        """,
        label=f"pass_events_{route_id}",
    )
    return int(row.iloc[0]["pass_events"] or 0)
