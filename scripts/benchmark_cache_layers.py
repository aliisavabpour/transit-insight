"""
Benchmark Route 29 observed-headway query — S3 cold/warm + local.
Run from repo root: python scripts/benchmark_cache_layers.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
sys.path.insert(0, str(DASHBOARD))

# Minimal env for non-Streamlit run
os.environ.setdefault("TRANSIT_INSIGHT_BENCH", "1")

import duckdb

BENCH_DATE = date(2026, 5, 12)
ROUTE_ID = "29"
S3_GLOB = (
    "s3://gtfs-rt-etl-data/ttc/positions/"
    "year=2026/month=05/day=12/*.parquet"
)
LOCAL_GLOB = str(DASHBOARD / "data" / "positions_cache" / "positions_20260512.parquet")
if not Path(LOCAL_GLOB).exists():
    alt = DASHBOARD / "data" / "positions_cache" / "ttc_positions_20260512.parquet"
    if alt.exists():
        LOCAL_GLOB = str(alt)

TRIPS = str(DASHBOARD / "data" / "gtfs" / "trips.txt")
REF_LAT, REF_LON = 43.6620, -79.4422  # Route 29 Dufferin & Bloor
MAX_DIST = 670 / 111_320.0


def configure(con: duckdb.DuckDBPyConnection, *, metadata: bool = True, external: bool = True) -> None:
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET parquet_metadata_cache = {str(metadata).lower()};")
    con.execute(f"SET enable_external_file_cache = {str(external).lower()};")
    con.execute("SET timezone = 'America/Toronto';")
    con.execute("SET threads TO 4;")


def headway_sql(parquet_expr: str, local_date_filter: str = "") -> str:
    where_extra = f" AND {local_date_filter}" if local_date_filter else ""
    return f"""
        WITH parquet_with_dir AS (
            SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id, p.timestamp,
                   SQRT(POW(p.bbox.ymin - {REF_LAT}, 2) + POW(p.bbox.xmin - ({REF_LON}), 2)) AS dist_deg
            FROM (
                SELECT trip_id, route_id, vehicle_id, timestamp, bbox
                FROM {parquet_expr}
                WHERE route_id = '{ROUTE_ID}' AND trip_id IS NOT NULL{where_extra}
            ) p
            JOIN read_csv_auto('{TRIPS.replace(chr(92), "/")}') t
                ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
        ),
        nearest_per_trip AS (
            SELECT vehicle_id, trip_id, direction_id, timestamp
            FROM parquet_with_dir WHERE dist_deg < {MAX_DIST}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY vehicle_id, trip_id, direction_id ORDER BY dist_deg
            ) = 1
        ),
        with_date_hour AS (
            SELECT vehicle_id, trip_id, direction_id, timestamp,
                   DATE(timestamp AT TIME ZONE 'America/Toronto') AS local_date,
                   HOUR(timestamp AT TIME ZONE 'America/Toronto') AS hour
            FROM nearest_per_trip
        ),
        with_prev AS (
            SELECT direction_id, local_date, hour, vehicle_id, trip_id, timestamp,
                   LAG(timestamp) OVER (
                       PARTITION BY direction_id, local_date, hour ORDER BY timestamp
                   ) AS prev_ts
            FROM with_date_hour
        )
        SELECT COUNT(*) AS n FROM with_prev WHERE prev_ts IS NOT NULL
    """


def run_once(con: duckdb.DuckDBPyConnection, label: str, sql: str) -> float:
    t0 = time.perf_counter()
    n = con.execute(sql).fetchone()[0]
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.2f}s (rows={n})")
    return elapsed


def bench_mode(name: str, parquet_expr: str, local_filter: str = "") -> dict:
    sql = headway_sql(parquet_expr, local_filter)
    print(f"\n=== {name} ===")

    # A: new connection each run (current app pattern)
    t_cold_new = None
    t_warm_new = None
    con1 = duckdb.connect()
    configure(con1)
    t_cold_new = run_once(con1, "run1 same connection", sql)
    t_warm_new = run_once(con1, "run2 same connection (warm)", sql)
    con1.close()

    con2 = duckdb.connect()
    configure(con2)
    t_fresh = run_once(con2, "run3 NEW connection (cache lost?)", sql)
    con2.close()

    return {
        "run1_same_con": t_cold_new,
        "run2_same_con": t_warm_new,
        "run3_new_con": t_fresh,
    }


def main() -> None:
    print("DuckDB", duckdb.__version__)
    print("Local file exists:", Path(LOCAL_GLOB).exists(), LOCAL_GLOB)

    s3_expr = f"read_parquet('{S3_GLOB}', hive_partitioning=true)"
    local_expr = f"read_parquet('{LOCAL_GLOB.replace(chr(92), '/')}', hive_partitioning=true)"
    local_filter = "DATE(timestamp AT TIME ZONE 'America/Toronto') = DATE '2026-05-12'"

    results = {}
    results["s3"] = bench_mode("S3 direct", s3_expr)
    if Path(LOCAL_GLOB).exists():
        results["local"] = bench_mode("Local parquet", local_expr, local_filter)
    else:
        print("\n=== Local parquet: SKIPPED (file missing) ===")

    print("\n=== Summary ===")
    for mode, r in results.items():
        if not r:
            continue
        speedup = r["run1_same_con"] / r["run2_same_con"] if r["run2_same_con"] else 0
        print(
            f"{mode}: same-con warm speedup {speedup:.2f}x; "
            f"new-con vs warm {r['run3_new_con']:.2f}s vs {r['run2_same_con']:.2f}s"
        )


if __name__ == "__main__":
    main()
