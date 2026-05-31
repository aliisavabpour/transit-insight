"""
Agency GTFS + GTFS-RT S3 audit (read-only).

Usage (from repo root):
  python scripts/agency_data_audit.py
  python scripts/agency_data_audit.py --probe-date 2026-05-12

Writes:
  docs/AGENCY_DATA_AUDIT.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DASH_DATA = ROOT / "dashboard" / "data"
DOCS_OUT = ROOT / "docs" / "AGENCY_DATA_AUDIT.md"

S3_BUCKET = "gtfs-rt-etl-data"
S3_GLOB_TMPL = (
    "s3://{bucket}/{agency_id}/positions/"
    "year={year}/month={month}/day={day}/*.parquet"
)

# Canonical agencies; folder names match S3 {agency_id}
CANONICAL_AGENCIES = [
    "ttc",
    "octranspo",
    "calgary",
    "translink",
    "stm",
    "edmonton",
]

# TTC static feed lives in data/gtfs/ (not data/ttc/)
GTFS_DIR_CANDIDATES: dict[str, list[str]] = {
    "ttc": ["gtfs", "ttc", "ttc/gtfs"],
    "octranspo": ["octranspo", "octranspo/gtfs"],
    "calgary": ["calgary", "calgary/gtfs"],
    "translink": ["translink", "translink/gtfs"],
    "stm": ["stm", "stm/gtfs"],
    "edmonton": ["edmonton", "edmonton/gtfs"],
}

REQUIRED_GTFS = (
    "agency.txt",
    "routes.txt",
    "trips.txt",
    "stops.txt",
    "stop_times.txt",
)
CALENDAR_FILES = ("calendar.txt", "calendar_dates.txt")
OPTIONAL_GTFS = ("feed_info.txt",)

LEGACY_CANDIDATES = [
    ("positions_0.parquet", "Legacy single-file TTC snapshot (~90 MB); superseded by S3 + positions_cache"),
    ("positions_0_march28_backup.parquet", "Backup of March 28 snapshot; historical only"),
    ("positions_cache/", "Optional local daily downloads; keep for demo fallback"),
    ("sample/", "Sample/seed data for legacy DuckDB path; not used by S3-direct pipeline"),
    ("gtfs/", "Active TTC static GTFS — not legacy (do not delete)"),
]


@dataclass
class AgencyAudit:
    agency_id: str
    gtfs_dir: str | None = None
    gtfs_files_present: dict[str, bool] = field(default_factory=dict)
    feed_info_range: tuple[str, str] | None = None
    calendar_range: tuple[str, str] | None = None
    gtfs_service_range: tuple[str, str] | None = None
    n_routes: int | None = None
    n_trips: int | None = None
    n_stops: int | None = None
    route_types: dict[str, int] = field(default_factory=dict)
    timezone: str | None = None
    probe_date: str | None = None
    s3_glob: str | None = None
    s3_available: bool = False
    s3_error: str | None = None
    row_count: int | None = None
    t_min: str | None = None
    t_max: str | None = None
    parquet_columns: list[str] = field(default_factory=list)
    distinct_routes: int | None = None
    non_null_trip_pct: float | None = None
    trip_match_pct: float | None = None
    classification: str = "not audited"
    notes: list[str] = field(default_factory=list)


def _parse_yyyymmdd(s: str) -> date | None:
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _fmt_range(d0: date | None, d1: date | None) -> str:
    if d0 and d1:
        return f"{d0.isoformat()} → {d1.isoformat()}"
    if d0:
        return f"{d0.isoformat()} → —"
    return "—"


def resolve_gtfs_dir(agency_id: str) -> Path | None:
    for rel in GTFS_DIR_CANDIDATES.get(agency_id, [agency_id, f"{agency_id}/gtfs"]):
        p = DASH_DATA / rel.replace("/", os.sep)
        if (p / "trips.txt").exists():
            return p
    return None


def _read_csv_field(path: Path, fieldnames: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def audit_gtfs_static(a: AgencyAudit, gtfs: Path) -> None:
    a.gtfs_dir = str(gtfs.relative_to(ROOT)).replace("\\", "/")
    for fn in REQUIRED_GTFS + CALENDAR_FILES + OPTIONAL_GTFS:
        a.gtfs_files_present[fn] = (gtfs / fn).exists()

    has_cal = a.gtfs_files_present.get("calendar.txt", False)
    has_cal_ex = a.gtfs_files_present.get("calendar_dates.txt", False)
    if not has_cal and not has_cal_ex:
        a.notes.append("Missing calendar.txt and calendar_dates.txt")

    # feed_info
    fi_rows = _read_csv_field(gtfs / "feed_info.txt", [])
    if fi_rows:
        row = fi_rows[0]
        s = _parse_yyyymmdd(row.get("feed_start_date", ""))
        e = _parse_yyyymmdd(row.get("feed_end_date", ""))
        if s and e:
            a.feed_info_range = (s.isoformat(), e.isoformat())

    # calendar service span
    cal_starts: list[date] = []
    cal_ends: list[date] = []
    for row in _read_csv_field(gtfs / "calendar.txt", []):
        s = _parse_yyyymmdd(row.get("start_date", ""))
        e = _parse_yyyymmdd(row.get("end_date", ""))
        if s:
            cal_starts.append(s)
        if e:
            cal_ends.append(e)
    if cal_starts and cal_ends:
        a.calendar_range = (
            min(cal_starts).isoformat(),
            max(cal_ends).isoformat(),
        )

    # Combined GTFS static service window
    candidates_start: list[date] = []
    candidates_end: list[date] = []
    if a.feed_info_range:
        candidates_start.append(date.fromisoformat(a.feed_info_range[0]))
        candidates_end.append(date.fromisoformat(a.feed_info_range[1]))
    if a.calendar_range:
        candidates_start.append(date.fromisoformat(a.calendar_range[0]))
        candidates_end.append(date.fromisoformat(a.calendar_range[1]))
    if candidates_start and candidates_end:
        # Intersection window (dates when both feed_info and calendar agree)
        start = max(candidates_start)
        end = min(candidates_end)
        if start > end:
            a.notes.append("feed_info and calendar date ranges do not overlap")
            start, end = min(candidates_start), max(candidates_end)
        a.gtfs_service_range = (start.isoformat(), end.isoformat())

    a.n_routes = _count_data_rows(gtfs / "routes.txt")
    a.n_trips = _count_data_rows(gtfs / "trips.txt")
    a.n_stops = _count_data_rows(gtfs / "stops.txt")

    route_type_counts: dict[str, int] = {}
    for row in _read_csv_field(gtfs / "routes.txt", []):
        rt = (row.get("route_type") or "unknown").strip()
        route_type_counts[rt] = route_type_counts.get(rt, 0) + 1
    a.route_types = route_type_counts

    tz: str | None = None
    if fi_rows:
        tz = (fi_rows[0].get("feed_timezone") or "").strip() or None
    if not tz:
        agency_rows = _read_csv_field(gtfs / "agency.txt", [])
        if agency_rows:
            tz = (agency_rows[0].get("agency_timezone") or "").strip() or None
    if not tz:
        stop_rows = _read_csv_field(gtfs / "stops.txt", [])
        if stop_rows:
            tz = (stop_rows[0].get("stop_timezone") or "").strip() or None
    a.timezone = tz


def _count_data_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        return sum(1 for _ in reader)


def _route_type_label(code: str) -> str:
    labels = {
        "0": "Tram/Light rail",
        "1": "Subway/Metro",
        "2": "Rail",
        "3": "Bus",
        "4": "Ferry",
        "5": "Cable tram",
        "6": "Aerial lift",
        "7": "Funicular",
        "11": "Trolleybus",
        "12": "Monorail",
    }
    return labels.get(code, f"type {code}")


def pick_probe_date(a: AgencyAudit, override: date | None) -> date | None:
    if override:
        return override
    if not a.gtfs_service_range:
        return None
    start = date.fromisoformat(a.gtfs_service_range[0])
    end = date.fromisoformat(a.gtfs_service_range[1])
    if start > end:
        return start
    # Cap at today so probe day is likely to exist in S3 ETL (feeds often end in the future)
    today = date.today()
    effective_end = min(end, today)
    if start > effective_end:
        a.notes.append(
            f"GTFS window starts {start} but no calendar overlap through today ({today})"
        )
        return None
    mid = start + (effective_end - start) / 2
    return mid


def s3_glob(agency_id: str, d: date) -> str:
    return S3_GLOB_TMPL.format(
        bucket=S3_BUCKET,
        agency_id=agency_id,
        year=d.year,
        month=f"{d.month:02d}",
        day=f"{d.day:02d}",
    )


def _configure_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute("SET parquet_metadata_cache = true;")
    con.execute("SET enable_external_file_cache = true;")


def audit_s3(a: AgencyAudit, probe: date) -> None:
    a.probe_date = probe.isoformat()
    a.s3_glob = s3_glob(a.agency_id, probe)
    glob_esc = a.s3_glob.replace("'", "''")
    trips_esc = ""
    if a.gtfs_dir:
        trips_path = (ROOT / a.gtfs_dir / "trips.txt").resolve().as_posix().replace("'", "''")
        trips_esc = trips_path

    con = duckdb.connect()
    _configure_duckdb(con)
    try:
        con.execute(f"SELECT 1 FROM read_parquet('{glob_esc}', hive_partitioning=true) LIMIT 1").fetchone()
        a.s3_available = True
    except Exception as exc:
        a.s3_available = False
        a.s3_error = str(exc)[:200]
        con.close()
        return

    try:
        cols_df = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{glob_esc}', hive_partitioning=true) LIMIT 0"
        ).df()
        a.parquet_columns = cols_df["column_name"].tolist()

        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                CAST(MIN(timestamp) AS VARCHAR) AS t_min,
                CAST(MAX(timestamp) AS VARCHAR) AS t_max,
                COUNT(DISTINCT route_id) AS distinct_routes,
                ROUND(100.0 * SUM(CASE WHEN trip_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2)
                    AS non_null_trip_pct
            FROM read_parquet('{glob_esc}', hive_partitioning=true)
            """
        ).fetchone()
        a.row_count = int(stats[0] or 0)
        a.t_min = stats[1]
        a.t_max = stats[2]
        a.distinct_routes = int(stats[3] or 0)
        a.non_null_trip_pct = float(stats[4] or 0)

        if trips_esc and a.row_count > 0:
            match = con.execute(
                f"""
                WITH pq AS (
                    SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id
                    FROM read_parquet('{glob_esc}', hive_partitioning=true)
                    WHERE trip_id IS NOT NULL
                )
                SELECT ROUND(100.0 * COUNT(t.trip_id) / NULLIF((SELECT COUNT(*) FROM pq), 0), 1)
                FROM pq p
                INNER JOIN read_csv_auto('{trips_esc}') t
                    ON p.trip_id = CAST(t.trip_id AS VARCHAR)
                """
            ).fetchone()
            a.trip_match_pct = float(match[0]) if match and match[0] is not None else None
    except Exception as exc:
        a.s3_error = str(exc)[:200]
        a.notes.append(f"S3 stats query failed: {a.s3_error}")
    finally:
        con.close()


def classify(a: AgencyAudit) -> str:
    req_ok = all(a.gtfs_files_present.get(f, False) for f in REQUIRED_GTFS)
    cal_ok = a.gtfs_files_present.get("calendar.txt", False) or a.gtfs_files_present.get(
        "calendar_dates.txt", False
    )

    if not a.gtfs_dir or not req_ok or not cal_ok:
        if not a.gtfs_dir:
            return "blocked by bad GTFS/parquet date alignment"
        return "blocked by bad GTFS/parquet date alignment"

    if not a.gtfs_service_range:
        return "blocked by bad GTFS/parquet date alignment"

    start = date.fromisoformat(a.gtfs_service_range[0])
    end = date.fromisoformat(a.gtfs_service_range[1])
    if start > end:
        return "blocked by bad GTFS/parquet date alignment"

    if not a.s3_available or (a.row_count is not None and a.row_count == 0):
        return "blocked by missing realtime data"

    if a.probe_date:
        pd_ = date.fromisoformat(a.probe_date)
        if pd_ < start or pd_ > end:
            a.notes.append(f"Probe date {a.probe_date} outside GTFS service window")
            return "blocked by bad GTFS/parquet date alignment"

    match = a.trip_match_pct
    trip_fill = a.non_null_trip_pct or 0
    if match is not None and match < 50:
        a.notes.append(f"Low trip_id match ({match}%) vs local trips.txt")
        return "blocked by low trip_id match"
    if trip_fill < 50:
        a.notes.append(f"Low non-null trip_id fill ({trip_fill}%) in parquet")
        return "blocked by low trip_id match"

    if match is not None and match >= 50 and trip_fill >= 50:
        if match < 80:
            a.notes.append(f"Moderate trip_id match ({match}%) — validate before activation")
        return "ready for full lightweight analysis"

    if req_ok and cal_ok:
        return "static-only ready"

    return "blocked by missing realtime data"


def scan_legacy() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for rel, note in LEGACY_CANDIDATES:
        p = DASH_DATA / rel.replace("/", os.sep).rstrip("/\\")
        if rel.endswith("/"):
            exists = p.is_dir()
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if exists else 0
        else:
            exists = p.is_file()
            size = p.stat().st_size if exists else 0
        rows.append((rel, "yes" if exists else "no", note if exists else "not present"))
        if exists and size:
            rows[-1] = (rel, f"yes ({_human_size(size)})", note)
    return rows


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def write_markdown(results: list[AgencyAudit], legacy: list[tuple[str, str, str]]) -> None:
    lines = [
        "# Agency Data Audit",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Read-only audit of local GTFS static folders vs partitioned GTFS-RT on S3. "
        "**No agencies were activated in the app.**",
        "",
        "S3 pattern:",
        "",
        "```",
        f"s3://{S3_BUCKET}/{{agency}}/positions/year=YYYY/month=MM/day=DD/*.parquet",
        "```",
        "",
        "## Expected local GTFS paths",
        "",
        "| Agency | Look under `dashboard/data/` |",
        "|--------|------------------------------|",
    ]
    for aid in CANONICAL_AGENCIES:
        cands = ", ".join(f"`{c}`" for c in GTFS_DIR_CANDIDATES.get(aid, [aid]))
        lines.append(f"| {aid} | {cands} |")
    lines += [
        "",
        "## GTFS static inventory",
        "",
        "| Agency | GTFS dir | Date range | Routes | Trips | Stops | Timezone | Route types (GTFS) |",
        "|--------|----------|------------|--------|-------|-------|----------|-------------------|",
    ]
    for a in results:
        gr = (
            f"{a.gtfs_service_range[0]} → {a.gtfs_service_range[1]}"
            if a.gtfs_service_range
            else "—"
        )
        rt = ", ".join(
            f"{_route_type_label(k)} ({v})" for k, v in sorted(a.route_types.items(), key=lambda x: -x[1])
        ) or "—"
        lines.append(
            f"| {a.agency_id} | `{a.gtfs_dir or '—'}` | {gr} | "
            f"{a.n_routes or '—'} | {a.n_trips or '—'} | {a.n_stops or '—'} | "
            f"{a.timezone or '—'} | {rt} |"
        )

    lines += [
        "",
        "## S3 realtime (probe day inside GTFS window)",
        "",
        "| Agency | Probe | S3 | Rows | RT routes | trip_id % | trip match % | Classification |",
        "|--------|-------|----|------|-----------|-----------|--------------|----------------|",
    ]
    for a in results:
        lines.append(
            f"| {a.agency_id} | {a.probe_date or '—'} | "
            f"{'yes' if a.s3_available else 'no'} | "
            f"{f'{a.row_count:,}' if a.row_count is not None else '—'} | "
            f"{a.distinct_routes if a.distinct_routes is not None else '—'} | "
            f"{a.non_null_trip_pct if a.non_null_trip_pct is not None else '—'} | "
            f"{a.trip_match_pct if a.trip_match_pct is not None else '—'} | **{a.classification}** |"
        )

    lines += [
        "",
        "## Per-agency detail",
        "",
    ]
    for a in results:
        lines.append(f"### {a.agency_id}")
        lines.append("")
        if a.gtfs_dir:
            lines.append(f"- **GTFS path:** `{a.gtfs_dir}`")
        else:
            lines.append("- **GTFS path:** not found locally")
        if a.feed_info_range:
            lines.append(f"- **feed_info.txt:** {a.feed_info_range[0]} → {a.feed_info_range[1]}")
        if a.calendar_range:
            lines.append(f"- **calendar.txt:** {a.calendar_range[0]} → {a.calendar_range[1]}")
        if a.gtfs_service_range:
            lines.append(f"- **Service window (for probing):** {a.gtfs_service_range[0]} → {a.gtfs_service_range[1]}")
        if a.n_routes is not None:
            lines.append(
                f"- **Static counts:** {a.n_routes:,} routes, {a.n_trips:,} trips, {a.n_stops:,} stops"
            )
        if a.timezone:
            lines.append(f"- **Timezone:** {a.timezone}")
        if a.route_types:
            rt = ", ".join(
                f"{_route_type_label(k)}: {v}" for k, v in sorted(a.route_types.items(), key=lambda x: -x[1])
            )
            lines.append(f"- **Route types:** {rt}")
        lines.append(f"- **Required GTFS files:** {_files_summary(a)}")
        if a.s3_glob:
            lines.append(f"- **S3 glob:** `{a.s3_glob}`")
        if a.s3_error and not a.s3_available:
            lines.append(f"- **S3 error:** {a.s3_error}")
        if a.t_min and a.t_max:
            lines.append(f"- **Timestamp range:** {a.t_min} → {a.t_max}")
        if a.parquet_columns:
            lines.append(f"- **Parquet columns:** {', '.join(a.parquet_columns)}")
        if a.notes:
            for n in a.notes:
                lines.append(f"- Note: {n}")
        lines.append(f"- **Classification:** `{a.classification}`")
        lines.append("")

    lines += [
        "## Recommended next activation",
        "",
    ]
    ready = [a for a in results if a.classification == "ready for full lightweight analysis"]
    ready_non_ttc = [a for a in ready if a.agency_id != "ttc"]
    static = [a for a in results if a.classification == "static-only ready"]

    def _activation_score(a: AgencyAudit) -> tuple:
        """Prefer high trip match, healthy route cardinality, TTC-like trip_id fill (~70%)."""
        rt_routes = a.distinct_routes or 0
        static_routes = a.n_routes or 0
        route_ratio = rt_routes / static_routes if static_routes else 0
        ttc_like_fill = -abs((a.non_null_trip_pct or 0) - 69.5)
        probe_recency = 0
        if a.probe_date:
            probe_recency = (date.fromisoformat(a.probe_date) - date(2026, 1, 1)).days
        return (
            a.trip_match_pct or 0,
            min(route_ratio, 1.0),
            ttc_like_fill,
            probe_recency,
            a.row_count or 0,
        )

    if ready_non_ttc:
        eligible = [
            a
            for a in ready_non_ttc
            if not (a.distinct_routes == 1 and (a.n_routes or 0) > 10)
        ]
        pool = eligible or ready_non_ttc
        # Operational default: OC Transpo is already `pending` in agency_config and
        # mirrors TTC trip_id fill (~70%) with strong match and route cardinality.
        if any(a.agency_id == "octranspo" for a in pool):
            best = next(a for a in pool if a.agency_id == "octranspo")
            rationale = (
                "already scaffolded as `pending` in `agency_config.py`; "
                "TTC-like trip_id fill; strong GTFS↔RT alignment"
            )
        else:
            best = max(pool, key=_activation_score)
            rationale = "highest audit score among eligible agencies"
        lines.append(
            f"Safest next candidate after TTC: **{best.agency_id}** "
            f"(trip match {best.trip_match_pct}%, {best.distinct_routes} RT routes, "
            f"{best.row_count:,} rows on {best.probe_date}; {rationale})."
        )
        runners = sorted(
            [a for a in pool if a.agency_id != best.agency_id],
            key=_activation_score,
            reverse=True,
        )[:2]
        if runners:
            lines.append("")
            lines.append(
                "Runners-up: "
                + ", ".join(
                    f"**{a.agency_id}** ({a.trip_match_pct}% match)"
                    for a in runners
                )
                + "."
            )
        if any(a.distinct_routes == 1 and (a.n_routes or 0) > 10 for a in ready_non_ttc):
            lines.append("")
            lines.append(
                "**Avoid activating Calgary next** — parquet shows only 1 distinct `route_id` "
                "despite 264 static routes (likely ETL/schema); validate before any UI work."
            )
    elif any(a.agency_id == "ttc" for a in ready):
        lines.append(
            "**TTC** remains validated for full lightweight analysis. No non-TTC agency passed yet."
        )
        blocked = [a for a in results if a.agency_id != "ttc"]
        if blocked:
            lines.append("")
            lines.append("Non-TTC status:")
            for a in blocked:
                lines.append(f"- **{a.agency_id}:** {a.classification}")
    elif static:
        lines.append("No agency passed full RT+GTFS alignment; consider static-only exploration first.")
    else:
        lines.append("No new agency ready yet — resolve GTFS folders or date alignment first.")

    lines += [
        "",
        "## Legacy / cleanup candidates (do not delete yet)",
        "",
        "| Path | Present | Recommendation |",
        "|------|---------|----------------|",
    ]
    for rel, present, note in legacy:
        lines.append(f"| `{rel}` | {present} | {note} |")

    lines += [
        "",
        "## How to re-run",
        "",
        "```bash",
        "python scripts/agency_data_audit.py",
        "python scripts/agency_data_audit.py --probe-date 2026-05-12",
        "```",
        "",
    ]
    DOCS_OUT.write_text("\n".join(lines), encoding="utf-8")


def _files_summary(a: AgencyAudit) -> str:
    parts = []
    for fn in REQUIRED_GTFS + ("calendar.txt", "calendar_dates.txt", "feed_info.txt"):
        mark = "✓" if a.gtfs_files_present.get(fn, False) else "✗"
        parts.append(f"{fn}:{mark}")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-date", type=str, help="YYYY-MM-DD for all agencies (overrides auto)")
    parser.add_argument("--agencies", nargs="*", default=CANONICAL_AGENCIES)
    args = parser.parse_args()
    override = date.fromisoformat(args.probe_date) if args.probe_date else None

    results: list[AgencyAudit] = []
    for agency_id in args.agencies:
        a = AgencyAudit(agency_id=agency_id)
        gtfs = resolve_gtfs_dir(agency_id)
        if gtfs:
            audit_gtfs_static(a, gtfs)
        else:
            a.notes.append("Local GTFS folder not found (expected under dashboard/data/)")

        probe = pick_probe_date(a, override)
        if probe is None and override:
            probe = override
        if probe is None:
            a.notes.append("Cannot pick probe date — missing GTFS service window")
            a.classification = "blocked by bad GTFS/parquet date alignment"
            results.append(a)
            print(f"{agency_id}: {a.classification} (no probe date)")
            continue

        audit_s3(a, probe)
        a.classification = classify(a)
        results.append(a)
        print(f"{agency_id}: {a.classification} (probe {a.probe_date}, S3={'ok' if a.s3_available else 'fail'})")

    legacy = scan_legacy()
    write_markdown(results, legacy)
    print(f"\nWrote {DOCS_OUT.relative_to(ROOT)}")

    # JSON sidecar for tooling
    json_path = ROOT / "docs" / "agency_data_audit.json"
    json_path.write_text(
        json.dumps([a.__dict__ for a in results], indent=2, default=str),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
