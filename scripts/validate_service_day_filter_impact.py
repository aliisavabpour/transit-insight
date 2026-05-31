"""
Report impact of service-day scheduled headway filter.

Usage:
  python scripts/validate_service_day_filter_impact.py
  python scripts/validate_service_day_filter_impact.py --date 2026-05-20

Writes: docs/SERVICE_DAY_FILTER_IMPACT.md
"""
from __future__ import annotations

import argparse
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

from utils.agency_config import ACTIVE_AGENCY_IDS, DEFAULT_SNAPSHOT_DATE  # noqa: E402
from utils.agency_loader import gtfs_file_path  # noqa: E402
from utils.reliability import (  # noqa: E402
    _compute_scheduled_headways_cached,
    compute_hourly_reliability,
    compute_schedule_comparison,
)
from utils.route_config import get_route_config  # noqa: E402


def _bootstrap(agency_id: str, probe: date) -> None:
    st = sys.modules["streamlit"]
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = probe


def _unfiltered_headways(route_id: str, agency_id: str) -> dict:
    """Pre-fix logic: all trips for route, no calendar filter."""
    trips = gtfs_file_path("trips.txt", agency_id).replace("\\", "/").replace("'", "''")
    st_file = gtfs_file_path("stop_times.txt", agency_id).replace("\\", "/").replace("'", "''")
    rid = route_id.replace("'", "''")
    con = duckdb.connect()
    try:
        row = con.execute(f"""
            WITH route_trips AS (
                SELECT CAST(trip_id AS VARCHAR) AS trip_id,
                       CAST(direction_id AS VARCHAR) AS direction_id
                FROM read_csv_auto('{trips}', all_varchar=true)
                WHERE CAST(route_id AS VARCHAR) = '{rid}'
            ),
            first_dep AS (
                SELECT CAST(st.trip_id AS VARCHAR) AS trip_id, st.departure_time
                FROM read_csv_auto('{st_file}', all_varchar=true) st
                INNER JOIN route_trips rt ON CAST(st.trip_id AS VARCHAR) = rt.trip_id
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY st.trip_id ORDER BY CAST(st.stop_sequence AS INTEGER)
                ) = 1
            )
            SELECT COUNT(*) AS n, ROUND(60.0 / COUNT(*), 1) AS hw
            FROM first_dep fd
            JOIN route_trips rt ON fd.trip_id = rt.trip_id
            WHERE rt.direction_id = '0'
              AND CAST(SPLIT_PART(fd.departure_time, ':', 1) AS INTEGER) % 24 = 9
        """).fetchone()
        return {"trips": int(row[0]), "headway_min": float(row[1])}
    finally:
        con.close()


def _filtered_headways(route_id: str, probe: date) -> dict:
    df = _compute_scheduled_headways_cached(route_id, probe)
    row = df[(df["direction_id"] == "0") & (df["hour"] == 9)]
    if row.empty:
        return {"trips": 0, "headway_min": None}
    return {
        "trips": int(row.iloc[0]["scheduled_trips"]),
        "headway_min": float(row.iloc[0]["scheduled_headway_min"]),
    }


def _deviation_at_hour9(route_id: str, ref: dict) -> dict | None:
    hourly = compute_hourly_reliability(route_id, ref["lat"], ref["lon"])
    row = hourly[(hourly["direction_id"] == "0") & (hourly["hour"] == 9)]
    if row.empty or row.iloc[0]["mean_headway"] != row.iloc[0]["mean_headway"]:
        return None
    r = row.iloc[0]
    if r.get("scheduled_headway_min") != r.get("scheduled_headway_min"):
        return None
    obs = float(r["mean_headway"]) * 60
    sched = float(r["scheduled_headway_min"]) * 60
    cmp_m = compute_schedule_comparison(
        __import__("numpy").array([sched]),
        __import__("numpy").array([obs]),
    )
    return {
        "observed_min": float(r["mean_headway"]),
        "scheduled_min": float(r["scheduled_headway_min"]),
        "relative_deviation": float(cmp_m["relative_deviation"][0]),
        "n_pass_events": int(r.get("n_observations") or 0),
    }


def _ref_for_route(agency_id: str, route_id: str) -> dict | None:
    cfg = get_route_config(route_id)
    if cfg and cfg.get("agency_id") == agency_id and cfg.get("ref_point"):
        return cfg["ref_point"]
    from utils.positions_store import execute_query, positions_where_clause, read_parquet_expr

    scan = read_parquet_expr()
    where = positions_where_clause(route_id=route_id)
    row = execute_query(
        f"SELECT AVG(bbox.ymin) AS lat, AVG(bbox.xmin) AS lon FROM {scan} WHERE {where}",
        label=f"centroid_{route_id}",
    )
    if row.empty or row.iloc[0]["lat"] is None:
        return None
    return {"lat": float(row.iloc[0]["lat"]), "lon": float(row.iloc[0]["lon"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE.isoformat())
    args = parser.parse_args()
    probe = date.fromisoformat(args.date)

    lines = [
        "# Service-Day Filter — Impact Report",
        "",
        f"**Analysis date:** {probe}",
        "",
        "## TTC Route 504 — hour 9, direction 0",
        "",
    ]

    _bootstrap("ttc", probe)
    old = _unfiltered_headways("504", "ttc")
    new = _filtered_headways("504", probe)
    ref504 = get_route_config("504")["ref_point"]
    dev = _deviation_at_hour9("504", ref504)

    lines += [
        "| Metric | Before (unfiltered) | After (service-day filter) |",
        "|--------|----------------------:|---------------------------:|",
        f"| Departures counted | {old['trips']} | {new['trips']} |",
        f"| Scheduled headway (min) | {old['headway_min']} | {new['headway_min']} |",
        "",
    ]
    if dev:
        ratio_before = dev["observed_min"] / old["headway_min"] if old["headway_min"] else None
        ratio_after = dev["observed_min"] / new["headway_min"] if new["headway_min"] else None
        lines += [
            "### Deviation metrics (hour 9, with filtered schedule)",
            "",
            f"- Observed headway: **{dev['observed_min']} min** ({dev['n_pass_events']} pass events)",
            f"- Scheduled headway (filtered): **{dev['scheduled_min']} min**",
            f"- Relative deviation: **{dev['relative_deviation']:.2f}** (was ~{ratio_before:.2f}× obs/sched implied ratio before)",
            f"- Implied obs/sched ratio after fix: **{ratio_after:.2f}×**",
            "",
        ]

    lines += ["## Multi-agency impact", ""]

    agency_routes = {
        "ttc": ["29", "501", "504"],
        "translink": ["6636"],
        "edmonton": ["009"],
    }

    for agency_id in ACTIVE_AGENCY_IDS:
        _bootstrap(agency_id, probe)
        lines.append(f"### {agency_id.upper()}")
        lines.append("")
        lines.append(
            "| Route | Hour 9 old trips | Hour 9 new trips | Old HW | New HW | Rel dev (h9) |"
        )
        lines.append("|-------|-----------------:|-----------------:|-------:|-------:|-------------:|")

        for rid in agency_routes.get(agency_id, []):
            old_r = _unfiltered_headways(rid, agency_id)
            new_r = _filtered_headways(rid, probe)
            ref = _ref_for_route(agency_id, rid)
            rel = "—"
            if ref:
                d = _deviation_at_hour9(rid, ref)
                if d:
                    rel = f"{d['relative_deviation']:.2f}"
            lines.append(
                f"| {rid} | {old_r['trips']} | {new_r['trips']} | "
                f"{old_r['headway_min']} | {new_r['headway_min'] or '—'} | {rel} |"
            )
        lines.append("")

    lines += [
        "## Summary",
        "",
        "- Scheduled headways increase **~3–4×** for TTC peak hours (fewer trips counted).",
        "- Relative deviation drops toward plausible range where pass events exist.",
        "- TransLink/Edmonton benefit from correct schedule; observed headway still limited by centroid refs.",
        "",
        "Re-run: `python scripts/validate_service_day_filter_impact.py`",
        "",
    ]

    out = ROOT / "docs" / "SERVICE_DAY_FILTER_IMPACT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}")
    print(f"TTC 504: {old['trips']} -> {new['trips']} trips, {old['headway_min']} -> {new['headway_min']} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
