"""Investigate STM trip_id match between May parquet and local GTFS."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
GTFS = ROOT / "dashboard" / "data" / "stm"
PROBE = date(2026, 5, 20)
GLOB = (
    f"s3://gtfs-rt-etl-data/stm/positions/"
    f"year={PROBE.year}/month={PROBE.month:02d}/day={PROBE.day:02d}/*.parquet"
)


def calendar_overlap_may() -> None:
    print("=== GTFS calendar vs May 15–31, 2026 ===\n")
    fi = list(csv.DictReader((GTFS / "feed_info.txt").open(encoding="utf-8-sig")))[0]
    print(f"feed_info: {fi['feed_start_date']} to {fi['feed_end_date']} (version {fi.get('feed_version', '')})")

    may_start, may_end = date(2026, 5, 15), date(2026, 5, 31)
    services_may: set[str] = set()
    with (GTFS / "calendar.txt").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            s = row["start_date"]
            e = row["end_date"]
            if not (s.isdigit() and e.isdigit()):
                continue
            sd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            ed = date(int(e[:4]), int(e[4:6]), int(e[6:8]))
            if sd <= may_end and ed >= may_start:
                services_may.add(row["service_id"])

    trips_may = 0
    trip_ids_may: set[str] = set()
    with (GTFS / "trips.txt").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["service_id"] in services_may:
                trips_may += 1
                trip_ids_may.add(row["trip_id"])

    print(f"calendar service_ids overlapping May window: {len(services_may)}")
    print(f"trips.txt rows on those services: {trips_may:,}")
    print(f"distinct trip_ids on May services: {len(trip_ids_may):,}")

    # trips by service_id prefix in file
    prefixes: dict[str, int] = {}
    with (GTFS / "trips.txt").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = row["service_id"]
            pre = sid.split("-")[0] if "-" in sid else sid[:4]
            prefixes[pre] = prefixes.get(pre, 0) + 1
    print("\ntrips.txt by service_id prefix (schedule generation):")
    for k, v in sorted(prefixes.items()):
        print(f"  {k}: {v:,}")


def duckdb_analysis() -> None:
    trips_path = GTFS / "trips.txt"
    trips_esc = trips_path.as_posix().replace("'", "''")
    glob_esc = GLOB.replace("'", "''")

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET timezone = 'America/Montreal';")

    print(f"\n=== S3 parquet probe: {PROBE} ===\n")

    pq_sample = con.execute(f"""
        SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
        FROM read_parquet('{glob_esc}', hive_partitioning=true)
        WHERE trip_id IS NOT NULL
        ORDER BY trip_id
        LIMIT 15
    """).df()
    print("Parquet sample trip_ids:")
    for t in pq_sample["trip_id"]:
        print(f"  {t}")

    gt_sample = con.execute(f"""
        SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
        FROM read_csv_auto('{trips_esc}')
        ORDER BY trip_id
        LIMIT 15
    """).df()
    print("\nGTFS trips.txt sample trip_ids (file start):")
    for t in gt_sample["trip_id"]:
        print(f"  {t}")

    # Match all GTFS
    m_all = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        )
        SELECT COUNT(*) AS n_pq,
            (SELECT COUNT(*) FROM pq p
             INNER JOIN read_csv_auto('{trips_esc}') t
               ON p.trip_id = CAST(t.trip_id AS VARCHAR)) AS matched_all
        FROM pq
    """).fetchone()
    print(f"\nMatch vs entire trips.txt: {m_all[1]}/{m_all[0]} ({100*m_all[1]/m_all[0]:.2f}%)")

    # Match May-calendar trips only (load service ids)
    may_services = []
    with (GTFS / "calendar.txt").open(encoding="utf-8-sig") as f:
        may_start, may_end = date(2026, 5, 15), date(2026, 5, 31)
        for row in csv.DictReader(f):
            s, e = row["start_date"], row["end_date"]
            sd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            ed = date(int(e[:4]), int(e[4:6]), int(e[6:8]))
            if sd <= may_end and ed >= may_start:
                may_services.append(row["service_id"].replace("'", "''"))

    svc_list = ", ".join(f"'{s}'" for s in may_services[:500])
    m_may = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        ),
        gt_may AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_csv_auto('{trips_esc}')
            WHERE service_id IN ({svc_list})
        )
        SELECT
            (SELECT COUNT(*) FROM pq) AS n_pq,
            (SELECT COUNT(*) FROM pq p INNER JOIN gt_may g ON p.trip_id = g.trip_id) AS matched_may
    """).fetchone()
    print(f"Match vs May-calendar trips only: {m_may[1]}/{m_may[0]} ({100*m_may[1]/m_may[0]:.2f}%)")

    # Prefix / range analysis
    stats = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id,
                   TRY_CAST(trip_id AS BIGINT) AS tid
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        ),
        gt AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id,
                   TRY_CAST(trip_id AS BIGINT) AS tid,
                   service_id
            FROM read_csv_auto('{trips_esc}')
        )
        SELECT
            (SELECT MIN(tid) FROM pq) AS pq_min,
            (SELECT MAX(tid) FROM pq) AS pq_max,
            (SELECT MIN(tid) FROM gt) AS gt_min,
            (SELECT MAX(tid) FROM gt) AS gt_max,
            (SELECT COUNT(*) FROM pq WHERE trip_id LIKE '290%') AS pq_290,
            (SELECT COUNT(*) FROM pq) AS pq_total,
            (SELECT COUNT(*) FROM gt WHERE trip_id LIKE '290%') AS gt_290,
            (SELECT COUNT(*) FROM gt) AS gt_total
    """).fetchone()
    print(f"\nNumeric trip_id ranges:")
    print(f"  parquet: {stats[0]} – {stats[1]}")
    print(f"  GTFS:    {stats[2]} – {stats[3]}")
    print(f"  parquet IDs starting with 290: {stats[4]}/{stats[5]}")
    print(f"  GTFS IDs starting with 290:    {stats[6]}/{stats[7]}")

    # March probe for comparison
    glob_mar = "s3://gtfs-rt-etl-data/stm/positions/year=2026/month=03/day=17/*.parquet".replace("'", "''")
    m_mar = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_parquet('{glob_mar}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        )
        SELECT COUNT(*) AS n,
            (SELECT COUNT(*) FROM pq p INNER JOIN read_csv_auto('{trips_esc}') t
             ON p.trip_id = CAST(t.trip_id AS VARCHAR)) AS matched
        FROM pq
    """).fetchone()
    print(f"\nMarch 17 match (same GTFS file): {m_mar[1]}/{m_mar[0]} ({100*m_mar[1]/m_mar[0]:.2f}%)")

    # service_id prefix in GTFS for matched vs unmatched parquet ids
    unmatched = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        )
        SELECT p.trip_id
        FROM pq p
        LEFT JOIN read_csv_auto('{trips_esc}') t ON p.trip_id = CAST(t.trip_id AS VARCHAR)
        WHERE t.trip_id IS NULL
        LIMIT 10
    """).df()
    print("\nSample parquet trip_ids NOT in trips.txt:")
    for t in unmatched["trip_id"]:
        print(f"  {t}")

    matched = con.execute(f"""
        WITH pq AS (
            SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            WHERE trip_id IS NOT NULL
        )
        SELECT p.trip_id, t.service_id
        FROM pq p
        INNER JOIN read_csv_auto('{trips_esc}') t ON p.trip_id = CAST(t.trip_id AS VARCHAR)
        LIMIT 5
    """).df()
    if not matched.empty:
        print("\nSample matched (should be empty if 0%):")
        print(matched.to_string(index=False))

    con.close()


def main() -> None:
    calendar_overlap_may()
    duckdb_analysis()
    print("\n=== Conclusion ===")
    print("See scripts/investigate_stm_trip_match.py output and docs/STM_TRIP_MATCH_INVESTIGATION.md")


if __name__ == "__main__":
    main()
