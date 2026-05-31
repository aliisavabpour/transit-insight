"""
Agency configuration for multi-agency GTFS-RT + GTFS static analysis.

Active agencies share a fixed May 2026 analysis window for cross-agency comparison.
TTC remains the default agency and deepest route-level demo (Route 29).
"""
from __future__ import annotations

import os
from datetime import date

_HERE = os.path.dirname(__file__)
_DATA = os.path.normpath(os.path.join(_HERE, "../data"))

S3_BUCKET = "gtfs-rt-etl-data"
S3_REGION = "us-west-2"

# Shared cross-agency analysis window (all active agencies must cover these dates)
SHARED_ANALYSIS_START = date(2026, 5, 15)
SHARED_ANALYSIS_END = date(2026, 5, 31)
SHARED_ANALYSIS_LABEL = "May 15–31, 2026"
DEFAULT_SNAPSHOT_DATE = date(2026, 5, 20)

S3_POSITIONS_GLOB = (
    "s3://{bucket}/{agency_id}/positions/"
    "year={year}/month={month}/day={day}/*.parquet"
)
S3_HTTPS_TEMPLATE = (
    "https://{bucket}.s3.{region}.amazonaws.com/{agency_id}/positions/"
    "year={year}/month={month}/day={day}/positions_0.parquet"
)


def _s3_glob(agency_id: str) -> str:
    return S3_POSITIONS_GLOB.format(
        bucket=S3_BUCKET, agency_id=agency_id, year="{year}", month="{month}", day="{day}"
    )


def _s3_https(agency_id: str) -> str:
    return S3_HTTPS_TEMPLATE.format(
        bucket=S3_BUCKET,
        region=S3_REGION,
        agency_id=agency_id,
        year="{year}",
        month="{month}",
        day="{day}",
    )


def _gtfs(path: str) -> str:
    return os.path.join(_DATA, path)


AGENCIES: dict[str, dict] = {
    "ttc": {
        "agency_id": "ttc",
        "name": "Toronto Transit Commission",
        "short_name": "TTC",
        "city": "Toronto, ON",
        "timezone": "America/Toronto",
        "status": "active",
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("ttc"),
        "s3_https_template": _s3_https("ttc"),
        "positions_cache_dir": os.path.join(_DATA, "positions_cache"),
        "gtfs_dir": _gtfs("gtfs"),
        "primary_bus_routes": ["29"],
        "data_note": "Primary demo agency · Route 29 deep-dive · shared May window",
        "data_coverage": f"Shared analysis window {SHARED_ANALYSIS_LABEL}",
    },
    "translink": {
        "agency_id": "translink",
        "name": "TransLink",
        "short_name": "TransLink",
        "city": "Metro Vancouver, BC",
        "timezone": "America/Vancouver",
        "status": "active",
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("translink"),
        "s3_https_template": _s3_https("translink"),
        "positions_cache_dir": os.path.join(_DATA, "translink", "positions_cache"),
        "gtfs_dir": _gtfs("translink"),
        "primary_bus_routes": [],
        "data_note": "Active · shared May window · network-level comparison",
        "data_coverage": f"Shared analysis window {SHARED_ANALYSIS_LABEL}",
    },
    "stm": {
        "agency_id": "stm",
        "name": "Société de transport de Montréal",
        "short_name": "STM",
        "city": "Montreal, QC",
        "timezone": "America/Montreal",
        "status": "pending",
        "block_reason": (
            "May 15-31 GTFS-RT trip_ids do not exist in local trips.txt (0% match on 2026-05-20); "
            "March RT matches same file at 99.8% — static feed version mismatch, not missing calendar"
        ),
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("stm"),
        "s3_https_template": _s3_https("stm"),
        "positions_cache_dir": os.path.join(_DATA, "stm", "positions_cache"),
        "gtfs_dir": _gtfs("stm"),
        "primary_bus_routes": [],
        "data_note": "Inactive — do not use reliability metrics until GTFS static matches May RT trip_ids",
        "data_coverage": "S3 positions OK; GTFS static trip_id mismatch for shared May window",
    },
    "edmonton": {
        "agency_id": "edmonton",
        "name": "Edmonton Transit Service",
        "short_name": "Edmonton",
        "city": "Edmonton, AB",
        "timezone": "America/Edmonton",
        "status": "active",
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("edmonton"),
        "s3_https_template": _s3_https("edmonton"),
        "positions_cache_dir": os.path.join(_DATA, "edmonton", "positions_cache"),
        "gtfs_dir": _gtfs("edmonton"),
        "primary_bus_routes": [],
        "data_note": "Active · shared May window · network-level comparison",
        "data_coverage": f"Shared analysis window {SHARED_ANALYSIS_LABEL}",
    },
    "octranspo": {
        "agency_id": "octranspo",
        "name": "OC Transpo",
        "short_name": "OC Transpo",
        "city": "Ottawa, ON",
        "timezone": "America/Toronto",
        "status": "pending",
        "block_reason": "GTFS starts 2026-05-22 — outside shared May 15–31 window for fair comparison",
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("octranspo"),
        "s3_https_template": _s3_https("octranspo"),
        "positions_cache_dir": os.path.join(_DATA, "octranspo", "positions_cache"),
        "gtfs_dir": _gtfs("octranspo"),
        "primary_bus_routes": [],
        "data_note": "Future work — activate only with a May 22+ analysis window",
        "data_coverage": "GTFS from 2026-05-22; not in shared May 15–31 cohort",
    },
    "calgary": {
        "agency_id": "calgary",
        "name": "Calgary Transit",
        "short_name": "Calgary",
        "city": "Calgary, AB",
        "timezone": "America/Edmonton",
        "status": "pending",
        "block_reason": "S3 parquet shows 1 distinct route_id vs 264 GTFS routes (ETL/schema)",
        "s3_bucket": S3_BUCKET,
        "s3_positions_glob": _s3_glob("calgary"),
        "s3_https_template": _s3_https("calgary"),
        "positions_cache_dir": os.path.join(_DATA, "calgary", "positions_cache"),
        "gtfs_dir": _gtfs("calgary"),
        "primary_bus_routes": [],
        "data_note": "Blocked until route_id cardinality in GTFS-RT parquet is fixed",
        "data_coverage": "Do not activate until audit route_id issue is resolved",
    },
}

ACTIVE_AGENCY_IDS = [aid for aid, cfg in AGENCIES.items() if cfg.get("status") == "active"]
PENDING_AGENCY_IDS = [aid for aid, cfg in AGENCIES.items() if cfg.get("status") == "pending"]

REQUIRED_AGENCY_FIELDS = (
    "agency_id",
    "name",
    "short_name",
    "city",
    "timezone",
    "status",
    "s3_positions_glob",
    "s3_https_template",
    "positions_cache_dir",
    "gtfs_dir",
    "data_note",
    "data_coverage",
)


def validate_agency_config() -> list[str]:
    errors: list[str] = []
    for aid, cfg in AGENCIES.items():
        missing = [k for k in REQUIRED_AGENCY_FIELDS if k not in cfg]
        if missing:
            errors.append(f"{aid}: missing fields {missing}")
        if cfg.get("status") not in {"active", "pending"}:
            errors.append(f"{aid}: invalid status {cfg.get('status')!r}")
    if AGENCIES.get("ttc", {}).get("status") != "active":
        errors.append("ttc: must remain status='active'")
    for aid in ("translink", "edmonton"):
        if AGENCIES.get(aid, {}).get("status") != "active":
            errors.append(f"{aid}: expected status='active' for shared May cohort")
    for aid in ("octranspo", "calgary", "stm"):
        if AGENCIES.get(aid, {}).get("status") != "pending":
            errors.append(f"{aid}: expected status='pending'")
    return errors


def get_agency_config(agency_id: str) -> dict | None:
    return AGENCIES.get(agency_id)


def get_supported_agency_ids() -> list[str]:
    return list(AGENCIES.keys())


def agency_gtfs_available(agency_id: str) -> bool:
    cfg = AGENCIES.get(agency_id)
    if not cfg:
        return False
    return os.path.exists(os.path.join(cfg["gtfs_dir"], "trips.txt"))


def agency_data_available(agency_id: str, probe_date: date | None = None) -> bool:
    """S3 partition reachable for agency on probe_date (default: mid shared window)."""
    cfg = AGENCIES.get(agency_id)
    if not cfg or cfg.get("status") != "active":
        return False
    if not agency_gtfs_available(agency_id):
        return False
    d = probe_date or DEFAULT_SNAPSHOT_DATE
    if d < SHARED_ANALYSIS_START or d > SHARED_ANALYSIS_END:
        return False
    from utils.positions_store import probe_agency_positions_available

    return probe_agency_positions_available(agency_id, "s3", d.isoformat())
