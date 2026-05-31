"""
Route 29 / May 12 — compare S3 cold/warm/local using positions_store patterns.
  python scripts/benchmark_route29_headway.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

# Fake minimal streamlit session for cache_resource (reuse connection)
class _FakeSessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _FakeSessionState()

    def cache_resource(self, func):
        cached = {}

        def wrapper(*a, **kw):
            if "val" not in cached:
                cached["val"] = func(*a, **kw)
            return cached["val"]

        return wrapper


sys.modules["streamlit"] = _FakeStreamlit()

from utils.positions_store import (  # noqa: E402
    duckdb_connect,
    execute_query,
    positions_subquery,
)
from utils.route_config import get_route_config

ROUTE = "29"
D = date(2026, 5, 12)
cfg = get_route_config(ROUTE)
REF = cfg["ref_point"]
MAX_D = 670 / 111_320.0
TRIPS = str(ROOT / "dashboard" / "data" / "gtfs" / "trips.txt").replace("\\", "/")


def run_headway(label: str, subquery_fn) -> float:
    pos = subquery_fn()
    sql = f"""
        WITH parquet_with_dir AS (
            SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id, p.timestamp,
                   SQRT(POW(p.bbox.ymin - {REF['lat']}, 2) +
                        POW(p.bbox.xmin - ({REF['lon']}), 2)) AS dist_deg
            FROM {pos}
            JOIN read_csv_auto('{TRIPS}') t
                ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
        ),
        nearest AS (
            SELECT vehicle_id, trip_id, direction_id, timestamp
            FROM parquet_with_dir WHERE dist_deg < {MAX_D}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY vehicle_id, trip_id, direction_id ORDER BY dist_deg
            ) = 1
        ),
        wh AS (
            SELECT *, DATE(timestamp AT TIME ZONE 'America/Toronto') AS local_date,
                   HOUR(timestamp AT TIME ZONE 'America/Toronto') AS hour
            FROM nearest
        ),
        wp AS (
            SELECT *, LAG(timestamp) OVER (
                PARTITION BY direction_id, local_date, hour ORDER BY timestamp
            ) AS prev_ts FROM wh
        )
        SELECT COUNT(*) AS n FROM wp WHERE prev_ts IS NOT NULL
    """
    t0 = time.perf_counter()
    n = execute_query(sql, label=label).iloc[0, 0]
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.2f}s  headways={int(n)}")
    return elapsed


def main():
    import utils.positions_store as ps
    from utils import parquet_date as pd_mod

    s3 = (
        "s3://gtfs-rt-etl-data/ttc/positions/"
        "year=2026/month=05/day=12/*.parquet"
    )
    local = ROOT / "dashboard" / "data" / "positions_cache" / "positions_20260512.parquet"
    if not local.exists():
        local = ROOT / "dashboard" / "data" / "positions_cache" / "ttc_positions_20260512.parquet"

    print("DuckDB session reuse:", not duckdb_connect()[1])

    # --- S3 ---
    print("\n=== S3 direct (shared Streamlit-style connection) ===")
    pd_mod.st.session_state[pd_mod._SESSION_KEY] = D
    ps.set_data_source("s3")
    os.environ.pop("TRANSIT_INSIGHT_BENCH", None)

    def s3_sub():
        uri = s3.replace("'", "''")
        return f"""(
            SELECT trip_id, route_id, vehicle_id, timestamp, bbox
            FROM read_parquet('{uri}', hive_partitioning=true)
            WHERE route_id = '{ROUTE}' AND trip_id IS NOT NULL
        ) AS p"""

    t1 = run_headway("s3_run1", s3_sub)
    t2 = run_headway("s3_run2_warm", s3_sub)

    # New ephemeral connection (old app behavior)
    print("\n=== S3 with NEW ephemeral connection (legacy pattern) ===")
    con, _ = duckdb_connect(ephemeral=True)
    con.close()
    con2, close2 = duckdb_connect(ephemeral=True)

    def s3_sub2():
        return s3_sub()

    # patch execute to use ephemeral only for this run
    orig = ps.duckdb_connect
    ps.duckdb_connect = lambda ephemeral=True: orig(ephemeral=True)
    t3 = run_headway("s3_ephemeral_fresh", s3_sub)
    ps.duckdb_connect = orig
    if close2:
        con2.close()

    # --- Local ---
    if local.exists():
        print("\n=== Local parquet ===")
        ps.set_data_source("local")

        def loc_sub():
            uri = str(local).replace("'", "''").replace("\\", "/")
            return f"""(
                SELECT trip_id, route_id, vehicle_id, timestamp, bbox
                FROM read_parquet('{uri}', hive_partitioning=true)
                WHERE route_id = '{ROUTE}' AND trip_id IS NOT NULL
                  AND DATE(timestamp AT TIME ZONE 'America/Toronto') = DATE '2026-05-12'
            ) AS p"""

        t4 = run_headway("local_run1", loc_sub)
        t5 = run_headway("local_run2", loc_sub)
    else:
        t4 = t5 = None

    print("\n=== Summary ===")
    print(f"S3 shared-con: run1={t1:.1f}s run2={t2:.1f}s speedup={t1/t2:.1f}x")
    print(f"S3 ephemeral fresh: {t3:.1f}s")
    if t4:
        print(f"Local: run1={t4:.1f}s run2={t5:.1f}s")


if __name__ == "__main__":
    main()
