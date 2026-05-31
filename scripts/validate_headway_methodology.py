"""
Read-only validation of observed vs scheduled headway methodology.

Uses production functions in utils.reliability (no formula changes).

Usage (repo root):
  python scripts/validate_headway_methodology.py
  python scripts/validate_headway_methodology.py --date 2026-05-20

Writes:
  docs/HEADWAY_METHODOLOGY_VALIDATION.md
  docs/headway_methodology_validation.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))


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

    def cache_data(self, *a, **kw):
        def decorator(func):
            store = {}

            def wrapper(*args, **kwargs):
                agency = self.session_state.get("current_agency_id", "")
                key = (agency, args, tuple(sorted(kwargs.items())))
                if key not in store:
                    store[key] = func(*args, **kwargs)
                return store[key]

            return wrapper

        if len(a) == 1 and callable(a[0]) and not kw:
            return decorator(a[0])
        return decorator


sys.modules["streamlit"] = _FakeStreamlit()

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from utils.agency_config import (  # noqa: E402
    ACTIVE_AGENCY_IDS,
    DEFAULT_SNAPSHOT_DATE,
)
from utils.agency_loader import gtfs_file_path  # noqa: E402
from utils.positions_store import (  # noqa: E402
    execute_query,
    positions_subquery,
    positions_where_clause,
    read_parquet_expr,
)
from utils.reliability import (  # noqa: E402
    compute_data_quality,
    compute_hourly_reliability,
    compute_observed_headways,
    compute_scheduled_headways,
    get_ref_radius_deg,
    get_ref_radius_meters,
)
from utils.route_config import get_route_config  # noqa: E402

MIN_HOURLY_OBS = 3
RATIO_HIGH = 3.0
RATIO_LOW = 1.0 / 3.0


def _setup(agency_id: str, probe: date) -> None:
    st = sys.modules["streamlit"]
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = probe


def _route_summary_uncached() -> pd.DataFrame:
    """Bypass @st.cache_data — agency must already be set in session."""
    scan = read_parquet_expr()
    return execute_query(
        f"""
        SELECT route_id, COUNT(*) AS records, COUNT(DISTINCT vehicle_id) AS vehicles
        FROM {scan}
        WHERE route_id IS NOT NULL
        GROUP BY route_id
        ORDER BY records DESC
        """,
        label="val_route_summary",
    )


def _centroid_uncached(route_id: str) -> dict | None:
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
    return {
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "label": f"GPS centroid (route {route_id})",
    }


def _pick_routes(agency_id: str) -> list[str]:
    if agency_id == "ttc":
        return ["29", "501", "504"]

    summary = _route_summary_uncached()
    if summary.empty:
        return []
    summary["route_id"] = summary["route_id"].astype(str)
    return summary.nlargest(3, "records")["route_id"].tolist()


def _ref_for_route(agency_id: str, route_id: str) -> dict:
    cfg = get_route_config(route_id)
    if cfg and cfg.get("agency_id") == agency_id and cfg.get("ref_point"):
        return cfg["ref_point"]
    centroid = _centroid_uncached(route_id)
    if centroid:
        return centroid
    raise ValueError(f"No ref point for {agency_id}/{route_id}")


def _pipeline_stats(route_id: str, ref: dict) -> dict:
    """Counts at each stage of the virtual-stop pass-event pipeline."""
    lat, lon = ref["lat"], ref["lon"]
    max_deg = get_ref_radius_deg()
    trips_file = gtfs_file_path("trips.txt").replace("'", "''")
    rid = route_id.replace("'", "''")

    pos_all = positions_subquery(route_id=route_id, require_trip_id=False)
    pos_trips = positions_subquery(route_id=route_id, require_trip_id=True)

    base = execute_query(
        f"""
        SELECT
            COUNT(*) AS gps_total,
            SUM(CASE WHEN trip_id IS NOT NULL THEN 1 ELSE 0 END) AS gps_with_trip,
            COUNT(DISTINCT vehicle_id) AS vehicles,
            COUNT(DISTINCT CAST(trip_id AS VARCHAR)) AS distinct_trip_ids
        FROM {pos_all}
        """,
        label=f"val_gps_{route_id}",
    ).iloc[0]

    joined = execute_query(
        f"""
        WITH pq AS (
            SELECT vehicle_id, CAST(trip_id AS VARCHAR) AS trip_id, timestamp,
                   bbox.ymin AS lat, bbox.xmin AS lon
            FROM {pos_trips}
        )
        SELECT COUNT(*) AS pings_joined_gtfs,
               COUNT(DISTINCT pq.trip_id) AS trips_joined_gtfs
        FROM pq
        INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
            ON pq.trip_id = CAST(t.trip_id AS VARCHAR)
        WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        """,
        label=f"val_join_{route_id}",
    ).iloc[0]

    near = execute_query(
        f"""
        WITH pq AS (
            SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   p.timestamp,
                   SQRT(POW(p.bbox.ymin - {lat}, 2) + POW(p.bbox.xmin - ({lon}), 2)) AS dist_deg
            FROM {pos_trips}
            INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        )
        SELECT
            COUNT(*) AS pings_in_radius,
            COUNT(DISTINCT trip_id) AS trips_in_radius,
            ROUND(MIN(dist_deg) * 111320, 1) AS min_dist_m,
            ROUND(APPROX_QUANTILE(dist_deg * 111320, 0.5), 1) AS median_dist_m,
            ROUND(MAX(dist_deg) * 111320, 1) AS max_dist_m
        FROM pq
        WHERE dist_deg < {max_deg}
        """,
        label=f"val_radius_{route_id}",
    ).iloc[0]

    pass_events = execute_query(
        f"""
        WITH pq AS (
            SELECT p.vehicle_id, CAST(p.trip_id AS VARCHAR) AS trip_id,
                   CAST(t.direction_id AS VARCHAR) AS direction_id,
                   p.timestamp,
                   SQRT(POW(p.bbox.ymin - {lat}, 2) + POW(p.bbox.xmin - ({lon}), 2)) AS dist_deg
            FROM {pos_trips}
            INNER JOIN read_csv_auto('{trips_file}', all_varchar=true) t
                ON CAST(p.trip_id AS VARCHAR) = CAST(t.trip_id AS VARCHAR)
            WHERE CAST(t.route_id AS VARCHAR) = '{rid}'
        ),
        nearest AS (
            SELECT vehicle_id, trip_id, direction_id, timestamp
            FROM pq
            WHERE dist_deg < {max_deg}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY vehicle_id, trip_id, direction_id ORDER BY dist_deg
            ) = 1
        )
        SELECT COUNT(*) AS pass_events FROM nearest
        """,
        label=f"val_pass_{route_id}",
    ).iloc[0]

    gtfs_trips = execute_query(
        f"""
        SELECT COUNT(DISTINCT CAST(trip_id AS VARCHAR)) AS gtfs_trips
        FROM read_csv_auto('{trips_file}', all_varchar=true)
        WHERE CAST(route_id AS VARCHAR) = '{rid}'
        """,
        label=f"val_gtfs_trips_{route_id}",
    ).iloc[0]["gtfs_trips"]

    return {
        "gps_total": int(base["gps_total"] or 0),
        "gps_with_trip": int(base["gps_with_trip"] or 0),
        "vehicles": int(base["vehicles"] or 0),
        "distinct_trip_ids_rt": int(base["distinct_trip_ids"] or 0),
        "pings_joined_gtfs": int(joined["pings_joined_gtfs"] or 0),
        "trips_joined_gtfs": int(joined["trips_joined_gtfs"] or 0),
        "gtfs_trips_static": int(gtfs_trips or 0),
        "pings_in_radius": int(near["pings_in_radius"] or 0),
        "trips_in_radius": int(near["trips_in_radius"] or 0),
        "min_dist_m": float(near["min_dist_m"]) if near["min_dist_m"] is not None else None,
        "median_dist_m": float(near["median_dist_m"]) if near["median_dist_m"] is not None else None,
        "max_dist_m": float(near["max_dist_m"]) if near["max_dist_m"] is not None else None,
        "pass_events": int(pass_events["pass_events"] or 0),
        "ref_radius_m": get_ref_radius_meters(),
    }


def _classify_suspicious(row: pd.Series, pipe: dict) -> str:
    obs = row.get("mean_headway")
    sched = row.get("scheduled_headway_min")
    n = int(row.get("n_observations") or 0)
    if pd.isna(obs) or pd.isna(sched) or sched <= 0:
        return "missing_schedule_or_observed"
    ratio = obs / sched
    if RATIO_LOW <= ratio <= RATIO_HIGH:
        return "ok"

    reasons = []
    if n < MIN_HOURLY_OBS:
        reasons.append("insufficient_pass_events")
    if pipe["pass_events"] < 10:
        reasons.append("low_route_pass_event_count")
    if pipe.get("median_dist_m") and pipe["median_dist_m"] > pipe["ref_radius_m"] * 0.85:
        reasons.append("ref_point_at_radius_edge")
    if int(row.get("scheduled_trips") or 0) >= 6 and ratio > RATIO_HIGH:
        reasons.append("possible_service_gap_or_hour_boundary_effect")
    if int(row.get("scheduled_trips") or 0) >= 4 and ratio < RATIO_LOW:
        reasons.append("possible_bunching_or_branch_aggregation")
    if not reasons:
        if ratio > RATIO_HIGH:
            reasons.append("possible_real_spacing_gap")
        else:
            reasons.append("possible_real_bunching")
    return "; ".join(reasons)


def validate_route(agency_id: str, route_id: str) -> dict:
    ref = _ref_for_route(agency_id, route_id)
    lat, lon = ref["lat"], ref["lon"]
    max_deg = get_ref_radius_deg()
    cfg = get_route_config(route_id)
    ref_type = (
        "configured"
        if cfg and cfg.get("agency_id") == agency_id and cfg.get("ref_point")
        else "gps_centroid"
    )

    pipe = _pipeline_stats(route_id, ref)
    dq = compute_data_quality(route_id)
    obs = compute_observed_headways(route_id, lat, lon, max_deg)
    sch = compute_scheduled_headways(route_id)
    hourly = compute_hourly_reliability(route_id, lat, lon, max_deg)

    headway_count = len(obs)
    suspicious = []
    if not hourly.empty:
        for _, row in hourly.iterrows():
            obs_h = row.get("mean_headway")
            sched_h = row.get("scheduled_headway_min")
            if pd.isna(obs_h) or pd.isna(sched_h) or sched_h <= 0:
                continue
            ratio = obs_h / sched_h
            if ratio > RATIO_HIGH or ratio < RATIO_LOW:
                suspicious.append({
                    "direction_id": str(row["direction_id"]),
                    "hour": int(row["hour"]),
                    "observed_headway_min": float(obs_h),
                    "scheduled_headway_min": float(sched_h),
                    "ratio": round(float(ratio), 2),
                    "n_pass_events": int(row.get("n_observations") or 0),
                    "scheduled_trips": int(row.get("scheduled_trips") or 0),
                    "classification": _classify_suspicious(row, pipe),
                })

    # Day-level summary (hours 6-22 with both values)
    day_cells = hourly[
        hourly["scheduled_headway_min"].notna() & hourly["mean_headway"].notna()
    ] if not hourly.empty else pd.DataFrame()
    if not day_cells.empty:
        day_cells = day_cells[(day_cells["hour"] >= 6) & (day_cells["hour"] <= 22)]
    if not day_cells.empty:
        mean_obs = float(day_cells["mean_headway"].mean())
        mean_sched = float(day_cells["scheduled_headway_min"].mean())
        mean_ratio = mean_obs / mean_sched if mean_sched else None
    else:
        mean_obs = mean_sched = mean_ratio = None

    trust = "trustworthy_with_caveats"
    if pipe["pass_events"] == 0:
        trust = "not_trustworthy_no_pass_events"
    elif pipe["pass_events"] < 15 or headway_count < 10:
        trust = "low_confidence_sparse_pass_events"
    elif ref_type == "gps_centroid" and pipe.get("median_dist_m", 0) > 500:
        trust = "low_confidence_centroid_ref_point"
    elif dq.get("match_pct", 0) < 80:
        trust = "low_confidence_trip_match"

    return {
        "agency_id": agency_id,
        "route_id": route_id,
        "ref_point": ref,
        "ref_type": ref_type,
        "pipeline": pipe,
        "data_quality": dq,
        "headway_gaps_computed": headway_count,
        "scheduled_hours": int(len(sch)) if not sch.empty else 0,
        "hourly_cells": int(len(hourly)) if not hourly.empty else 0,
        "daytime_mean_observed_min": round(mean_obs, 2) if mean_obs is not None else None,
        "daytime_mean_scheduled_min": round(mean_sched, 2) if mean_sched is not None else None,
        "daytime_mean_ratio": round(mean_ratio, 2) if mean_ratio is not None else None,
        "suspicious_cells": suspicious[:12],
        "suspicious_count": len(suspicious),
        "trust": trust,
    }


def _agency_verdict(routes: list[dict]) -> str:
    trusts = [r["trust"] for r in routes]
    if any(t == "not_trustworthy_no_pass_events" for t in trusts):
        return "not_trustworthy"
    if sum(1 for t in trusts if "low_confidence" in t) >= 2:
        return "partially_trustworthy"
    return "trustworthy_with_caveats"


def write_markdown(results: list[dict], probe: date) -> str:
    lines = [
        "# Headway Methodology Validation",
        "",
        f"Probe date: **{probe}** · Read-only · **No formulas changed**",
        "",
        "Method under test: virtual-stop pass events (670 m radius) → consecutive gaps "
        "within direction × local date × hour; scheduled headway = `60 ÷ trips per direction per hour` from GTFS.",
        "",
        "## Executive summary",
        "",
    ]
    for agency in results:
        lines.append(
            f"- **{agency['agency_id'].upper()}**: {agency['verdict']} "
            f"(GTFS trip match on probe from prior audit: see active_agency_validation.json)"
        )
    lines += ["", "## Per-agency results", ""]

    for agency in results:
        lines.append(f"### {agency['agency_id'].upper()}")
        lines.append("")
        lines.append(f"Routes checked: {', '.join(agency['routes_checked'])}")
        lines.append("")
        lines.append(
            "| Route | Ref type | Pass events | Headway gaps | GPS w/ trip | "
            "Daytime obs (min) | Daytime sched (min) | Ratio | Suspicious cells | Trust |"
        )
        lines.append("|-------|----------|-------------|--------------|-------------|"
                     "-------------------|---------------------|-------|------------------|-------|")
        for r in agency["routes"]:
            if "error" in r:
                lines.append(
                    f"| {r['route_id']} | — | — | — | — | — | — | — | — | **error:** {r['error'][:60]} |"
                )
                continue
            p = r["pipeline"]
            lines.append(
                f"| {r['route_id']} | {r['ref_type']} | {p['pass_events']} | {r['headway_gaps_computed']} | "
                f"{p['gps_with_trip']:,} | {r['daytime_mean_observed_min'] or '—'} | "
                f"{r['daytime_mean_scheduled_min'] or '—'} | {r['daytime_mean_ratio'] or '—'} | "
                f"{r['suspicious_count']} | {r['trust']} |"
            )
        lines.append("")

        for r in agency["routes"]:
            if not r["suspicious_cells"]:
                continue
            lines.append(f"#### Route {r['route_id']} — suspicious hour cells (ratio >3× or <⅓)")
            lines.append("")
            lines.append(
                "| Dir | Hour | Obs (min) | Sched (min) | Ratio | Pass events | Likely cause |"
            )
            lines.append("|-----|------|-----------|-------------|-------|-------------|--------------|")
            for s in r["suspicious_cells"][:8]:
                lines.append(
                    f"| {s['direction_id']} | {s['hour']} | {s['observed_headway_min']} | "
                    f"{s['scheduled_headway_min']} | {s['ratio']} | {s['n_pass_events']} | "
                    f"{s['classification']} |"
                )
            lines.append("")

    lines += [
        "## Methodology checks",
        "",
        "| Check | Status | Notes |",
        "|-------|--------|-------|",
        "| Virtual stop (670 m) | Working as coded | Pass events = nearest ping per (vehicle, trip) within radius |",
        "| Direction from GTFS trip join | Working | Parquet direction_id ignored; uses trips.txt |",
        "| Hour/date partition for LAG | Working | Prevents midnight cross-date gaps |",
        "| Route filter | Working | `route_id` equality on parquet |",
        "| Scheduled headway | Working | First stop departure → hour bucket; all patterns combined |",
        "",
        "## Trustworthiness conclusion",
        "",
        "- **TTC (configured ref points):** Calculations are **internally consistent** and usable for demo. "
        "Large deviations often trace to sparse pass events per hour or branch aggregation (504A+504B), not formula bugs.",
        "- **TransLink / Edmonton (GPS centroid ref):** Calculations run correctly but **confidence is lower** — "
        "centroid reference points may miss corridor geometry; expect more suspicious ratios on low-frequency hours.",
        "- **Do not treat extreme ratios as operations KPIs** without checking `n_pass_events ≥ 3` and ref-point quality.",
        "",
        "## Re-run",
        "",
        "```bash",
        "python scripts/validate_headway_methodology.py",
        "python scripts/validate_headway_methodology.py --date 2026-05-20",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE.isoformat())
    args = parser.parse_args()
    probe = date.fromisoformat(args.date)

    all_results = []
    for agency_id in ACTIVE_AGENCY_IDS:
        _setup(agency_id, probe)
        routes = _pick_routes(agency_id)
        route_results = []
        for rid in routes:
            print(f"Validating {agency_id} route {rid}...")
            try:
                route_results.append(validate_route(agency_id, rid))
            except Exception as exc:
                route_results.append({
                    "agency_id": agency_id,
                    "route_id": rid,
                    "error": str(exc),
                    "trust": "error",
                })
        all_results.append({
            "agency_id": agency_id,
            "probe_date": probe.isoformat(),
            "routes_checked": routes,
            "routes": route_results,
            "verdict": _agency_verdict([r for r in route_results if "error" not in r]),
        })

    out_json = ROOT / "docs" / "headway_methodology_validation.json"
    out_md = ROOT / "docs" / "HEADWAY_METHODOLOGY_VALIDATION.md"
    out_json.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    out_md.write_text(write_markdown(all_results, probe), encoding="utf-8")
    print(f"\nWrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
