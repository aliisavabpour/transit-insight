"""Validate active agencies on DEFAULT_SNAPSHOT_DATE (S3 + GTFS alignment)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

from datetime import date

from utils.agency_config import (
    ACTIVE_AGENCY_IDS,
    DEFAULT_SNAPSHOT_DATE,
    SHARED_ANALYSIS_LABEL,
    agency_gtfs_available,
    get_agency_config,
)
from utils.positions_store import probe_agency_positions_available

# Reuse audit trip-match logic
sys.path.insert(0, str(ROOT / "scripts"))
from agency_data_audit import audit_s3, resolve_gtfs_dir, AgencyAudit  # noqa: E402


def main() -> int:
    probe = DEFAULT_SNAPSHOT_DATE
    print(f"Shared window: {SHARED_ANALYSIS_LABEL}")
    print(f"Probe date: {probe}\n")
    results = []
    for aid in ACTIVE_AGENCY_IDS:
        a = AgencyAudit(agency_id=aid)
        gtfs = resolve_gtfs_dir(aid)
        if gtfs:
            from agency_data_audit import audit_gtfs_static

            audit_gtfs_static(a, gtfs)
        audit_s3(a, probe)
        ok = probe_agency_positions_available(aid, "s3", probe.isoformat())
        row = {
            "agency": aid,
            "s3": ok,
            "rows": a.row_count,
            "rt_routes": a.distinct_routes,
            "trip_id_pct": a.non_null_trip_pct,
            "trip_match_pct": a.trip_match_pct,
            "gtfs": agency_gtfs_available(aid),
        }
        results.append(row)
        print(
            f"{aid}: S3={'ok' if ok else 'FAIL'} rows={a.row_count} "
            f"match={a.trip_match_pct}% routes={a.distinct_routes}"
        )
    out = ROOT / "docs" / "active_agency_validation.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out.relative_to(ROOT)}")
    return 0 if all(r["s3"] and r["gtfs"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
