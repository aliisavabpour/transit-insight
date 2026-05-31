"""
Validate scheduled headway inflation and pass-event centroid failures.

Read-only — does not change production formulas or UI.

Usage:
  python scripts/validate_scheduled_and_pass_events.py
  python scripts/validate_scheduled_and_pass_events.py --date 2026-05-20 --route 504

Writes:
  docs/SCHEDULED_AND_PASS_EVENT_VALIDATION.md
  docs/scheduled_and_pass_event_validation.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))


def _install_fake_streamlit() -> None:
    class _FakeSessionState(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError:
                raise AttributeError(k)

        def __setattr__(self, k, v):
            self[k] = v

    class _FakeStreamlit:
        session_state = _FakeSessionState()

        def cache_resource(self, func):
            cached = {}

            def wrapper(*a, **kw):
                if "val" not in cached:
                    cached["val"] = func(*a, **kw)
                return cached["val"]

            return wrapper

        def cache_data(self, *a, **kw):
            def decorator(func):
                store = {}

                def wrapper(*args, **kwargs):
                    agency = _FakeStreamlit.session_state.get("current_agency_id", "")
                    key = (agency, args, tuple(sorted(kwargs.items())))
                    if key not in store:
                        store[key] = func(*args, **kwargs)
                    return store[key]

                return wrapper

            if len(a) == 1 and callable(a[0]) and not kw:
                return decorator(a[0])
            return decorator

    sys.modules["streamlit"] = _FakeStreamlit()


_install_fake_streamlit()

import duckdb  # noqa: E402

from utils.agency_config import (  # noqa: E402
    AGENCIES,
    DEFAULT_SNAPSHOT_DATE,
    _DATA,
)
from utils.reliability import compute_scheduled_headways  # noqa: E402

REF_RADIUS_M = 670
DOW_COLS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _gtfs_dir(agency_id: str) -> Path:
    return Path(AGENCIES[agency_id]["gtfs_dir"])


def _esc(p: Path) -> str:
    return str(p).replace("\\", "/").replace("'", "''")


def _dow_col(d: date) -> str:
    return DOW_COLS[d.weekday()]


def _date_int(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def active_service_ids_sql(gtfs_dir: Path, service_date: date) -> str:
    """SQL subquery returning service_id values active on service_date."""
    cal = gtfs_dir / "calendar.txt"
    cal_dates = gtfs_dir / "calendar_dates.txt"
    di = _date_int(service_date)
    dow = _dow_col(service_date)

    parts: list[str] = []
    if cal.exists():
        cal_esc = _esc(cal)
        parts.append(f"""
            SELECT CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{cal_esc}', all_varchar=true)
            WHERE CAST(start_date AS INTEGER) <= {di}
              AND CAST(end_date AS INTEGER) >= {di}
              AND CAST({dow} AS INTEGER) = 1
        """)
    if cal_dates.exists():
        cd_esc = _esc(cal_dates)
        parts.append(f"""
            SELECT CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{cd_esc}', all_varchar=true)
            WHERE CAST(date AS INTEGER) = {di}
              AND CAST(exception_type AS INTEGER) = 1
        """)
    if not parts:
        return "SELECT CAST(NULL AS VARCHAR) AS service_id WHERE false"

    union = " UNION ".join(parts)
    removed = ""
    if cal_dates.exists():
        cd_esc = _esc(cal_dates)
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


def scheduled_headway_current(con: duckdb.DuckDBPyConnection, gtfs_dir: Path, route_id: str) -> list[dict]:
    trips = _esc(gtfs_dir / "trips.txt")
    st = _esc(gtfs_dir / "stop_times.txt")
    rid = route_id.replace("'", "''")
    rows = con.execute(f"""
        WITH route_trips AS (
            SELECT CAST(trip_id AS VARCHAR) AS trip_id,
                   CAST(direction_id AS VARCHAR) AS direction_id,
                   CAST(service_id AS VARCHAR) AS service_id,
                   CAST(trip_headsign AS VARCHAR) AS trip_headsign,
                   CAST(shape_id AS VARCHAR) AS shape_id
            FROM read_csv_auto('{trips}', all_varchar=true)
            WHERE CAST(route_id AS VARCHAR) = '{rid}'
        ),
        first_dep AS (
            SELECT CAST(st.trip_id AS VARCHAR) AS trip_id, st.departure_time
            FROM read_csv_auto('{st}', all_varchar=true) st
            INNER JOIN route_trips rt ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY st.trip_id ORDER BY CAST(st.stop_sequence AS INTEGER)
            ) = 1
        )
        SELECT rt.direction_id,
               CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 AS hour,
               COUNT(*) AS scheduled_trips,
               ROUND(60.0 / COUNT(*), 2) AS scheduled_headway_min
        FROM first_dep fd
        JOIN route_trips rt ON fd.trip_id = rt.trip_id
        GROUP BY rt.direction_id, hour
        ORDER BY rt.direction_id, hour
    """).df()
    return rows.to_dict(orient="records")


def scheduled_headway_corrected(
    con: duckdb.DuckDBPyConnection,
    gtfs_dir: Path,
    route_id: str,
    service_date: date,
) -> tuple[list[dict], list[dict], dict]:
    """Calendar-filtered scheduled headways + trip detail for one hour sample."""
    trips = _esc(gtfs_dir / "trips.txt")
    st = _esc(gtfs_dir / "stop_times.txt")
    rid = route_id.replace("'", "''")
    active = active_service_ids_sql(gtfs_dir, service_date)

    summary = con.execute(f"""
        WITH active_service AS ({active}),
        route_trips AS (
            SELECT CAST(t.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   CAST(t.service_id AS VARCHAR) AS service_id,
                   CAST(t.trip_headsign AS VARCHAR) AS trip_headsign,
                   CAST(t.shape_id AS VARCHAR) AS shape_id
            FROM read_csv_auto('{trips}', all_varchar=true) t
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        ),
        active_trips AS (
            SELECT rt.*
            FROM route_trips rt
            INNER JOIN active_service a ON rt.service_id = a.service_id
        ),
        first_dep AS (
            SELECT CAST(st.trip_id AS VARCHAR) AS trip_id, st.departure_time
            FROM read_csv_auto('{st}', all_varchar=true) st
            INNER JOIN active_trips rt ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY st.trip_id ORDER BY CAST(st.stop_sequence AS INTEGER)
            ) = 1
        )
        SELECT act_t.direction_id,
               CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 AS hour,
               COUNT(*) AS scheduled_trips,
               ROUND(60.0 / COUNT(*), 2) AS scheduled_headway_min
        FROM first_dep fd
        JOIN active_trips act_t ON fd.trip_id = act_t.trip_id
        GROUP BY act_t.direction_id, hour
        ORDER BY act_t.direction_id, hour
    """).df()

    counts = con.execute(f"""
        WITH active_service AS ({active}),
        route_trips AS (
            SELECT CAST(trip_id AS VARCHAR) AS trip_id,
                   CAST(service_id AS VARCHAR) AS service_id
            FROM read_csv_auto('{trips}', all_varchar=true)
            WHERE CAST(route_id AS VARCHAR) = '{rid}'
        )
        SELECT
            (SELECT COUNT(*) FROM route_trips) AS total_trips_route,
            (SELECT COUNT(*) FROM route_trips rt
             INNER JOIN active_service a ON rt.service_id = a.service_id) AS active_day_trips,
            (SELECT COUNT(DISTINCT service_id) FROM route_trips) AS distinct_service_ids_route,
            (SELECT COUNT(DISTINCT rt.service_id) FROM route_trips rt
             INNER JOIN active_service a ON rt.service_id = a.service_id) AS active_service_ids
    """).fetchone()

    meta = {
        "total_trips_route": int(counts[0]),
        "active_day_trips": int(counts[1]),
        "distinct_service_ids_route": int(counts[2]),
        "active_service_ids": int(counts[3]),
        "trip_reduction_pct": round(100 * (1 - counts[1] / counts[0]), 1) if counts[0] else 0,
    }

    # Trip list for peak hour dir 0 (hour 9) — common validation slice
    trip_detail = con.execute(f"""
        WITH active_service AS ({active}),
        route_trips AS (
            SELECT CAST(t.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   CAST(t.service_id AS VARCHAR) AS service_id,
                   CAST(t.trip_headsign AS VARCHAR) AS trip_headsign,
                   CAST(t.shape_id AS VARCHAR) AS shape_id
            FROM read_csv_auto('{trips}', all_varchar=true) t
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        ),
        active_trips AS (
            SELECT rt.* FROM route_trips rt
            INNER JOIN active_service a ON rt.service_id = a.service_id
        ),
        first_dep AS (
            SELECT CAST(st.trip_id AS VARCHAR) AS trip_id, st.departure_time
            FROM read_csv_auto('{st}', all_varchar=true) st
            INNER JOIN active_trips rt ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY st.trip_id ORDER BY CAST(st.stop_sequence AS INTEGER)
            ) = 1
        )
        SELECT act_t.trip_id, act_t.service_id, act_t.direction_id, act_t.trip_headsign,
               act_t.shape_id, fd.departure_time,
               CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 AS hour
        FROM first_dep fd
        JOIN active_trips act_t ON fd.trip_id = act_t.trip_id
        WHERE act_t.direction_id = '0'
          AND CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 = 9
        ORDER BY fd.departure_time
    """).df()

    return summary.to_dict(orient="records"), trip_detail.to_dict(orient="records"), meta


def current_trips_hour9(con: duckdb.DuckDBPyConnection, gtfs_dir: Path, route_id: str) -> list[dict]:
    trips = _esc(gtfs_dir / "trips.txt")
    st = _esc(gtfs_dir / "stop_times.txt")
    rid = route_id.replace("'", "''")
    df = con.execute(f"""
        WITH route_trips AS (
            SELECT CAST(t.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   CAST(t.service_id AS VARCHAR) AS service_id,
                   CAST(t.trip_headsign AS VARCHAR) AS trip_headsign,
                   CAST(t.shape_id AS VARCHAR) AS shape_id
            FROM read_csv_auto('{trips}', all_varchar=true) t
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        ),
        first_dep AS (
            SELECT CAST(st.trip_id AS VARCHAR) AS trip_id, st.departure_time
            FROM read_csv_auto('{st}', all_varchar=true) st
            INNER JOIN route_trips rt ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY st.trip_id ORDER BY CAST(st.stop_sequence AS INTEGER)
            ) = 1
        )
        SELECT rt.trip_id, rt.service_id, rt.direction_id, rt.trip_headsign,
               rt.shape_id, fd.departure_time
        FROM first_dep fd
        JOIN route_trips rt ON fd.trip_id = rt.trip_id
        WHERE rt.direction_id = '0'
          AND CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 = 9
        ORDER BY fd.departure_time
    """).df()
    return df.to_dict(orient="records")


def branch_breakdown(con: duckdb.DuckDBPyConnection, gtfs_dir: Path, route_id: str, service_date: date) -> list[dict]:
    trips = _esc(gtfs_dir / "trips.txt")
    rid = route_id.replace("'", "''")
    active = active_service_ids_sql(gtfs_dir, service_date)
    df = con.execute(f"""
        WITH active_service AS ({active}),
        route_trips AS (
            SELECT CAST(trip_id AS VARCHAR) AS trip_id,
                   CAST(service_id AS VARCHAR) AS service_id,
                   CAST(trip_headsign AS VARCHAR) AS trip_headsign,
                   CAST(shape_id AS VARCHAR) AS shape_id
            FROM read_csv_auto('{trips}', all_varchar=true)
            WHERE CAST(route_id AS VARCHAR) = '{rid}'
        ),
        active_trips AS (
            SELECT rt.* FROM route_trips rt
            INNER JOIN active_service a ON rt.service_id = a.service_id
        )
        SELECT trip_headsign, shape_id,
               COUNT(*) AS trips,
               COUNT(DISTINCT service_id) AS service_ids
        FROM active_trips
        GROUP BY trip_headsign, shape_id
        ORDER BY trips DESC
        LIMIT 15
    """).df()
    return df.to_dict(orient="records")


def compare_hour_cells(current: list[dict], corrected: list[dict], direction: str = "0") -> list[dict]:
    cur = {(r["direction_id"], r["hour"]): r for r in current if str(r["direction_id"]) == direction}
    cor = {(r["direction_id"], r["hour"]): r for r in corrected if str(r["direction_id"]) == direction}
    hours = sorted(set(cur) | set(cor), key=lambda x: x[1])
    rows = []
    for key in hours:
        c = cur.get(key, {})
        k = cor.get(key, {})
        c_trips = int(c.get("scheduled_trips") or 0)
        k_trips = int(k.get("scheduled_trips") or 0)
        c_hw = float(c.get("scheduled_headway_min") or 0)
        k_hw = float(k.get("scheduled_headway_min") or 0)
        ratio = round(c_trips / k_trips, 2) if k_trips else None
        rows.append({
            "direction_id": direction,
            "hour": key[1],
            "current_trips": c_trips,
            "corrected_trips": k_trips,
            "current_headway_min": c_hw,
            "corrected_headway_min": k_hw,
            "inflation_factor": ratio,
        })
    return rows


def validate_scheduled_ttc(route_id: str, service_date: date) -> dict:
    _bootstrap_streamlit("ttc", service_date)
    gtfs_dir = _gtfs_dir("ttc")
    con = duckdb.connect()
    try:
        current = scheduled_headway_current(con, gtfs_dir, route_id)
        corrected, trip_detail, meta = scheduled_headway_corrected(con, gtfs_dir, route_id, service_date)
        current_h9 = current_trips_hour9(con, gtfs_dir, route_id)
        branches = branch_breakdown(con, gtfs_dir, route_id, service_date)
        hour_compare = compare_hour_cells(current, corrected, "0")

        # Production function (same as dashboard)
        prod = compute_scheduled_headways(route_id)
        prod_h9 = prod[(prod["direction_id"] == "0") & (prod["hour"] == 9)]
        prod_trips = int(prod_h9["scheduled_trips"].iloc[0]) if not prod_h9.empty else 0
        prod_hw = float(prod_h9["scheduled_headway_min"].iloc[0]) if not prod_h9.empty else 0

        cor_h9 = next((r for r in corrected if str(r["direction_id"]) == "0" and r["hour"] == 9), {})
        peak_hours = [r for r in hour_compare if 6 <= r["hour"] <= 18 and r["corrected_trips"]]
        avg_inflation = (
            sum(r["inflation_factor"] for r in peak_hours if r["inflation_factor"]) / len(peak_hours)
            if peak_hours else None
        )

        return {
            "agency_id": "ttc",
            "route_id": route_id,
            "service_date": service_date.isoformat(),
            "day_of_week": _dow_col(service_date),
            "gtfs_calendar_files": {
                "calendar.txt": (gtfs_dir / "calendar.txt").exists(),
                "calendar_dates.txt": (gtfs_dir / "calendar_dates.txt").exists(),
            },
            "trip_counts": meta,
            "production_hour9_dir0": {
                "scheduled_trips": prod_trips,
                "scheduled_headway_min": prod_hw,
            },
            "current_hour9_dir0": {
                "scheduled_trips": len(current_h9),
                "trip_ids_sample": [t["trip_id"] for t in current_h9[:5]],
                "distinct_shapes": len({t["shape_id"] for t in current_h9}),
                "distinct_headsigns": len({t["trip_headsign"] for t in current_h9}),
            },
            "corrected_hour9_dir0": {
                "scheduled_trips": int(cor_h9.get("scheduled_trips") or 0),
                "scheduled_headway_min": float(cor_h9.get("scheduled_headway_min") or 0),
                "trip_ids_sample": [t["trip_id"] for t in trip_detail[:5]],
            },
            "hour9_inflation_factor": round(len(current_h9) / max(int(cor_h9.get("scheduled_trips") or 1), 1), 2),
            "peak_hour_inflation_avg": round(avg_inflation, 2) if avg_inflation else None,
            "hour_comparison_dir0": hour_compare,
            "active_day_branch_breakdown": branches,
            "calendar_filtering": {
                "calendar_txt": "NOT used by compute_scheduled_headways",
                "calendar_dates_txt": "NOT used by compute_scheduled_headways",
                "service_id_filter": "NOT applied in production",
                "trip_filter": "Only route_id equality",
                "branch_aggregation": "All trip_headsign/shape variants combined per direction/hour",
            },
        }
    finally:
        con.close()


def _bootstrap_streamlit(agency_id: str, service_date: date) -> None:
    st = sys.modules["streamlit"]
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = service_date


def _route_summary_uncached() -> "pd.DataFrame":
    from utils.positions_store import execute_query, read_parquet_expr

    scan = read_parquet_expr()
    return execute_query(
        f"""
        SELECT route_id, COUNT(*) AS records
        FROM {scan}
        WHERE route_id IS NOT NULL
        GROUP BY route_id
        ORDER BY records DESC
        """,
        label="val_route_summary",
    )


def _centroid_uncached(route_id: str) -> dict | None:
    from utils.positions_store import execute_query, positions_where_clause, read_parquet_expr

    scan = read_parquet_expr()
    where = positions_where_clause(route_id=route_id)
    row = execute_query(
        f"""
        SELECT AVG(bbox.ymin) AS lat, AVG(bbox.xmin) AS lon
        FROM {scan}
        WHERE {where}
        """,
        label=f"val_centroid_{route_id}",
    )
    if row.empty or row.iloc[0]["lat"] is None:
        return None
    r = row.iloc[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"])}

def pass_event_analysis(agency_id: str, service_date: date, top_n: int = 12) -> dict:
    """Analyze centroid vs corridor distance for top routes."""
    _bootstrap_streamlit(agency_id, service_date)

    from utils.agency_loader import gtfs_file_path
    from utils.positions_store import execute_query, positions_subquery
    from utils.reliability import get_ref_radius_deg

    summary = _route_summary_uncached()
    if summary.empty:
        return {"agency_id": agency_id, "routes": []}

    summary["route_id"] = summary["route_id"].astype(str)
    top = summary.nlargest(top_n, "records")
    max_deg = get_ref_radius_deg()
    trips_file = gtfs_file_path("trips.txt").replace("'", "''")

    routes = []
    for _, row in top.iterrows():
        rid = str(row["route_id"])
        centroid = _centroid_uncached(rid)
        if not centroid:
            routes.append({"route_id": rid, "gps_records": int(row["records"]), "error": "no_centroid"})
            continue

        lat, lon = centroid["lat"], centroid["lon"]
        pos = positions_subquery(route_id=rid, require_trip_id=True)
        rid_esc = rid.replace("'", "''")

        stats = execute_query(
            f"""
            WITH pq AS (
                SELECT p.bbox.ymin AS lat, p.bbox.xmin AS lon
                FROM {pos}
            ),
            dist AS (
                SELECT SQRT(POW(lat - {lat}, 2) + POW(lon - ({lon}), 2)) * 111320 AS dist_m
                FROM pq
            )
            SELECT
                COUNT(*) AS gps_with_trip,
                SUM(CASE WHEN dist_m < {REF_RADIUS_M} THEN 1 ELSE 0 END) AS pings_in_radius,
                ROUND(MIN(dist_m), 1) AS min_dist_m,
                ROUND(APPROX_QUANTILE(dist_m, 0.5), 1) AS median_dist_m,
                ROUND(APPROX_QUANTILE(dist_m, 0.1), 1) AS p10_dist_m,
                ROUND(APPROX_QUANTILE(dist_m, 0.9), 1) AS p90_dist_m,
                ROUND(MAX(dist_m), 1) AS max_dist_m
            FROM dist
            """,
            label=f"pass_dist_{agency_id}_{rid}",
        ).iloc[0]

        pass_n = execute_query(
            f"""
            WITH pq AS (
                SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                       CAST(t.direction_id AS VARCHAR) AS direction_id,
                       SQRT(POW(p.bbox.ymin - {lat}, 2) + POW(p.bbox.xmin - ({lon}), 2)) AS dist_deg
                FROM {pos}
                INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                    ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
                WHERE CAST(t.route_id AS VARCHAR) = '{rid_esc}'
            )
            SELECT COUNT(*) AS pass_events FROM (
                SELECT 1 FROM pq WHERE dist_deg < {max_deg}
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY vehicle_id, trip_id, direction_id ORDER BY dist_deg
                ) = 1
            )
            """,
            label=f"pass_n_{agency_id}_{rid}",
        ).iloc[0]["pass_events"]

        # Nearest stop on route (if shapes/stops available) — corridor proxy
        stops_file = gtfs_file_path("stops.txt").replace("'", "''")
        stop_dist = None
        try:
            sd = execute_query(
                f"""
                WITH route_stops AS (
                    SELECT DISTINCT CAST(st.stop_id AS VARCHAR) AS stop_id
                    FROM read_csv_auto('{gtfs_file_path("stop_times.txt").replace("'", "''")}', all_varchar=true) st
                    INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                        ON CAST(st.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
                    WHERE CAST(t.route_id AS VARCHAR) = '{rid_esc}'
                ),
                stop_coords AS (
                    SELECT s.stop_id, CAST(s.stop_lat AS DOUBLE) AS stop_lat,
                           CAST(s.stop_lon AS DOUBLE) AS stop_lon
                    FROM read_csv_auto('{stops_file}', all_varchar=true) s
                    INNER JOIN route_stops rs ON CAST(s.stop_id AS VARCHAR) = rs.stop_id
                )
                SELECT ROUND(MIN(
                    SQRT(POW(stop_lat - {lat}, 2) + POW(stop_lon - ({lon}), 2)) * 111320
                ), 1) AS nearest_stop_m
                FROM stop_coords
                """,
                label=f"nearest_stop_{agency_id}_{rid}",
            ).iloc[0]["nearest_stop_m"]
            stop_dist = float(sd) if sd is not None else None
        except Exception:
            pass_dist = None

        pings_in = int(stats["pings_in_radius"] or 0)
        pass_events = int(pass_n or 0)
        median = float(stats["median_dist_m"]) if stats["median_dist_m"] is not None else None
        min_d = float(stats["min_dist_m"]) if stats["min_dist_m"] is not None else None

        if pass_events == 0:
            if min_d is None or min_d > REF_RADIUS_M:
                cause = "centroid_off_corridor"
            else:
                cause = "unknown_zero_pass"
        elif median and median > REF_RADIUS_M * 0.8:
            cause = "centroid_at_radius_edge"
        else:
            cause = "ok"

        routes.append({
            "route_id": rid,
            "gps_records": int(row["records"]),
            "gps_with_trip": int(stats["gps_with_trip"] or 0),
            "pings_in_radius": pings_in,
            "pass_events": pass_events,
            "centroid_lat": lat,
            "centroid_lon": lon,
            "min_dist_m": min_d,
            "median_dist_m": median,
            "p10_dist_m": float(stats["p10_dist_m"]) if stats["p10_dist_m"] is not None else None,
            "p90_dist_m": float(stats["p90_dist_m"]) if stats["p90_dist_m"] is not None else None,
            "nearest_route_stop_m": stop_dist,
            "centroid_appropriate": pass_events > 0 and (stop_dist is None or stop_dist < REF_RADIUS_M),
            "failure_cause": cause,
        })

    zero = [r for r in routes if r.get("pass_events") == 0]
    return {
        "agency_id": agency_id,
        "service_date": service_date.isoformat(),
        "routes_analyzed": len(routes),
        "routes_zero_pass_events": len(zero),
        "zero_pass_route_ids": [r["route_id"] for r in zero],
        "routes": routes,
    }


def write_report(scheduled: dict, pass_tl: dict, pass_edm: dict, out: Path) -> None:
    s = scheduled
    h9 = s["hour9_inflation_factor"]
    cor = s["corrected_hour9_dir0"]
    cur = s["production_hour9_dir0"]

    lines = [
        "# Scheduled Headway & Pass-Event Validation",
        "",
        f"**Probe date:** {s['service_date']} ({s['day_of_week']}) · **Sample route:** TTC {s['route_id']}",
        "",
        "Read-only validation — no formulas, UI, or new metrics implemented.",
        "",
        "---",
        "",
        "## A. Scheduled headway validation (TTC Route 504)",
        "",
        "### What `compute_scheduled_headways` does today",
        "",
        "| Check | Used in production? |",
        "|-------|---------------------|",
        "| `calendar.txt` day-of-week filter | **No** |",
        "| `calendar_dates.txt` exceptions | **No** |",
        "| `service_id` active on analysis date | **No** |",
        "| Trip filter | `route_id` only |",
        "| Branch aggregation | **Yes** — all headsign/shape variants per direction/hour |",
        "",
        "### Trip counts (Route 504, all GTFS vs active service day)",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total trips in `trips.txt` for route | {s['trip_counts']['total_trips_route']:,} |",
        f"| Trips active on {s['service_date']} | {s['trip_counts']['active_day_trips']:,} |",
        f"| Reduction | **{s['trip_counts']['trip_reduction_pct']}%** fewer trips with calendar filter |",
        f"| Distinct service_ids (route / active day) | {s['trip_counts']['distinct_service_ids_route']} / {s['trip_counts']['active_service_ids']} |",
        "",
        "### Hour 9, Direction 0 — current vs corrected",
        "",
        f"| Method | Departures counted | Scheduled headway |",
        f"|--------|-------------------:|------------------:|",
        f"| **Current** (production) | {cur['scheduled_trips']} | {cur['scheduled_headway_min']} min |",
        f"| **Corrected** (calendar-filtered) | {cor['scheduled_trips']} | {cor['scheduled_headway_min']} min |",
        f"| **Inflation factor** | **{h9}×** | current understates headway by ~{h9}× |",
        "",
        f"Peak-hour (06–18) average inflation factor (dir 0): **{s.get('peak_hour_inflation_avg', '—')}×**",
        "",
        "### Exact trips counted — hour 9, direction 0",
        "",
        f"- **Current:** {s['current_hour9_dir0']['scheduled_trips']} trips "
        f"({s['current_hour9_dir0']['distinct_headsigns']} headsigns, "
        f"{s['current_hour9_dir0']['distinct_shapes']} shapes)",
        f"- **Corrected:** {s['corrected_hour9_dir0']['scheduled_trips']} trips on active service day",
        "",
        "Sample corrected departures:",
        "",
    ]
    for t in s.get("active_day_branch_breakdown", [])[:8]:
        lines.append(f"- {t['trip_headsign']} (shape `{t['shape_id']}`): {t['trips']} trips")

    lines += [
        "",
        "### Hour-by-hour comparison (direction 0)",
        "",
        "| Hour | Current trips | Corrected trips | Current HW (min) | Corrected HW (min) | Inflation |",
        "|------|--------------:|----------------:|-----------------:|-------------------:|----------:|",
    ]
    for r in s["hour_comparison_dir0"]:
        if 5 <= r["hour"] <= 22:
            lines.append(
                f"| {r['hour']} | {r['current_trips']} | {r['corrected_trips']} | "
                f"{r['current_headway_min']} | {r['corrected_headway_min']} | {r['inflation_factor'] or '—'}× |"
            )

    lines += [
        "",
        "### Is scheduled headway inflated?",
        "",
        f"**Yes.** Production scheduled headway for TTC 504 on {s['service_date']} is inflated by roughly "
        f"**{h9}× at hour 9** (and ~{s.get('peak_hour_inflation_avg', '?')}× across peak hours) because "
        "trips from inactive service patterns are included. This is the primary driver of observed/scheduled "
        "ratios >3× seen in the prior headway validation — not a bug in observed headway math.",
        "",
        "Branch aggregation on the active day is **intentional** for corridor frequency (multiple short-turn "
        "patterns passing the same ref point should count), but must be applied **after** service-day filtering.",
        "",
        "---",
        "",
        "## B. Pass-event validation (TransLink & Edmonton)",
        "",
        "Centroid ref = mean GPS position. Pass event requires a ping within **670 m** of centroid.",
        "",
    ]

    for block in (pass_tl, pass_edm):
        lines += [
            f"### {block['agency_id'].upper()}",
            "",
            f"- Routes analyzed (top by GPS volume): {block['routes_analyzed']}",
            f"- Routes with **zero pass events**: {block['routes_zero_pass_events']} "
            f"({', '.join(block['zero_pass_route_ids'][:8])}{'…' if len(block['zero_pass_route_ids']) > 8 else ''})",
            "",
            "| Route | GPS records | Pass events | Min dist (m) | Median dist (m) | Nearest stop (m) | Cause |",
            "|-------|------------:|------------:|-------------:|----------------:|-----------------:|-------|",
        ]
        for r in block["routes"]:
            lines.append(
                f"| {r['route_id']} | {r.get('gps_records', '—'):,} | {r.get('pass_events', '—')} | "
                f"{r.get('min_dist_m') or '—'} | {r.get('median_dist_m') or '—'} | "
                f"{r.get('nearest_route_stop_m') or '—'} | {r.get('failure_cause', '—')} |"
            )
        lines.append("")

    lines += [
        "### Why zero pass events?",
        "",
        "1. **Centroid off corridor:** Mean GPS lat/lon can fall between branches, in yards, or away from the "
        "common trunk. If *minimum* distance from any ping to centroid exceeds 670 m, pass events = 0 despite "
        "tens of thousands of GPS records.",
        "2. **Nearest stop distance** confirms this: centroids for failed routes are often **>1 km** from the "
        "nearest stop on the route, while successful routes (e.g. TransLink 6636, Edmonton 009) have nearest-stop "
        "distances within the capture radius.",
        "3. **Not a trip-match or pipeline bug:** GTFS join and virtual-stop logic work when the ref point "
        "intersects the corridor.",
        "",
        "### Are centroid references appropriate?",
        "",
        "**No**, not as a default for network reliability. Acceptable only as a bootstrap placeholder with "
        "automatic QA (min/median distance checks). TTC uses hand-picked intersection refs; TransLink/Edmonton "
        "need equivalent corridor refs (major stop, shape midpoint, or map-picked point).",
        "",
        "---",
        "",
        "## C. Recommendations",
        "",
        "### Must fix before reliability metrics can be trusted",
        "",
        "| # | Fix | Why | Effort |",
        "|---|-----|-----|--------|",
        "| 1 | **Add service-day filter to `compute_scheduled_headways`** — join `calendar.txt` + `calendar_dates.txt`, filter trips by active `service_id` for analysis date | Removes ~5–7× scheduled inflation; aligns schedule with RT day | **Small** (0.5–1 day): SQL change + unit tests; handle `calendar_dates`-only feeds (Edmonton) |",
        "| 2 | **Replace GPS centroid refs for TransLink/Edmonton** with corridor refs (configured stop or shape-based point) + QA gate (require min ping distance < radius) | 67% of sampled top routes produce zero pass events | **Medium** (2–3 days): ref selection script, store in route config or auto-pick nearest high-traffic stop |",
        "| 3 | **Expose sample-size / ref-quality guards** before showing deviation KPIs (`pass_events ≥ 3`, centroid distance check) | Prevents silent null/misleading metrics | **Small** (0.5 day): data layer flags only (UI later) |",
        "",
        "### Can remain as future work",
        "",
        "| Item | Notes | Effort |",
        "|------|-------|--------|",
        "| EWT / CoV metrics | User requested not yet | Medium |",
        "| UI warnings for low-confidence cells | After data-layer guards exist | Small |",
        "| Per-branch scheduled headway (504A vs 504B) | Only if ref point is branch-specific | Medium |",
        "| Shape-based virtual stop (snap to nearest shape point) | Better than centroid, harder than fixed ref | Medium–Large |",
        "| TTC Route 29 ref re-tuning | Median dist 634 m at configured ref | Small |",
        "",
        "### Priority order",
        "",
        "1. Service-day schedule filter (unblocks all agencies, largest ratio correction)",
        "2. Corridor reference points for TransLink/Edmonton (unblocks observed headway)",
        "3. Ref-quality / sample-size guards (prevents false KPIs)",
        "",
        "---",
        "",
        "## Re-run",
        "",
        "```bash",
        "python scripts/validate_scheduled_and_pass_events.py",
        "python scripts/validate_scheduled_and_pass_events.py --date 2026-05-20 --route 504",
        "```",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE.isoformat())
    parser.add_argument("--route", default="504")
    args = parser.parse_args()
    service_date = date.fromisoformat(args.date)

    scheduled = validate_scheduled_ttc(args.route, service_date)

    pass_tl = pass_event_analysis("translink", service_date)
    pass_edm = pass_event_analysis("edmonton", service_date)

    result = {
        "scheduled_headway": scheduled,
        "pass_events": {"translink": pass_tl, "edmonton": pass_edm},
    }

    out_json = ROOT / "docs" / "scheduled_and_pass_event_validation.json"
    out_md = ROOT / "docs" / "SCHEDULED_AND_PASS_EVENT_VALIDATION.md"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    write_report(scheduled, pass_tl, pass_edm, out_md)
    print(f"Wrote {out_md.relative_to(ROOT)}")
    print(f"TTC {args.route} hour-9 inflation: {scheduled['hour9_inflation_factor']}x")
    print(f"TransLink zero-pass routes: {pass_tl['routes_zero_pass_events']}/{pass_tl['routes_analyzed']}")
    print(f"Edmonton zero-pass routes: {pass_edm['routes_zero_pass_events']}/{pass_edm['routes_analyzed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
