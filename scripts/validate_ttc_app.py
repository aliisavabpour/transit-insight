"""Final TTC validation checks (no Streamlit UI)."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
sys.path.insert(0, str(DASH))

import duckdb

from utils.positions_store import duckdb_connect, probe_positions_available
from utils.agency_loader import s3_glob_for_date, cache_path_for_date

DAY = date(2026, 5, 12)
S3_GLOB = s3_glob_for_date(DAY, "ttc")
LOCAL = cache_path_for_date(DAY, "ttc")
LEGACY = DASH / "data" / "positions_cache" / "positions_20260512.parquet"


def main() -> int:
    issues: list[str] = []

    pages = list((DASH / "pages").glob("*.py"))
    if len(pages) != 3:
        issues.append(f"Expected 3 page files, found {len(pages)}: {[p.name for p in pages]}")
    archive = list((DASH / "pages").glob("*archive*"))
    if archive:
        issues.append(f"Archive page files still present: {archive}")

    if not probe_positions_available("s3", DAY.isoformat()):
        issues.append("S3 probe failed")
    else:
        print("PASS S3 probe")

    local_path = Path(LOCAL) if Path(LOCAL).exists() else (LEGACY if LEGACY.exists() else None)
    if not local_path:
        issues.append("No local parquet cache file for May 12")
    else:
        con = duckdb.connect()
        n = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(local_path).replace(chr(92), '/')}') "
            f"WHERE route_id='29'"
        ).fetchone()[0]
        con.close()
        print(f"PASS local cache rows route 29: {n}")

    con, close = duckdb_connect(ephemeral=True)
    try:
        con.execute(f"SELECT 1 FROM read_parquet('{S3_GLOB.replace(chr(39), chr(39)+chr(39))}', hive_partitioning=true) LIMIT 1").fetchone()
        print("PASS S3 direct query")
    except Exception as exc:
        issues.append(f"S3 direct query failed: {exc}")
    finally:
        if close:
            con.close()

    if issues:
        print("ISSUES:")
        for i in issues:
            print(" -", i)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
