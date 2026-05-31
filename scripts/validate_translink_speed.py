"""
Validate TransLink source speed issue and derived-speed fix.

Usage:
  python scripts/validate_translink_speed.py --date 2026-05-20

Writes: docs/TRANSLINK_SPEED_VALIDATION.md
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

from utils.agency_config import DEFAULT_SNAPSHOT_DATE  # noqa: E402
from utils.positions_store import execute_query, read_parquet_expr  # noqa: E402
from utils.real_data import agency_needs_derived_speed  # noqa: E402
from utils.speed_utils import apply_effective_speed_kmh, compute_derived_speed_kmh  # noqa: E402

AGENCIES = ("translink", "ttc", "edmonton")
SAMPLE_LIMIT = 500_000


def _bootstrap(agency_id: str, probe: date) -> None:
    st = sys.modules["streamlit"]
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = probe


def _source_stats(agency_id: str) -> dict:
    scan = read_parquet_expr()
    row = execute_query(
        f"""
        SELECT
            COUNT(*) AS rows,
            ROUND(MIN(speed * 3.6), 2) AS min_kmh,
            ROUND(AVG(speed * 3.6), 2) AS mean_kmh,
            ROUND(MAX(speed * 3.6), 2) AS max_kmh,
            ROUND(100.0 * SUM(CASE WHEN speed = 0 OR speed IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_zero,
            SUM(CASE WHEN bbox.ymin IS NOT NULL AND bbox.xmin IS NOT NULL THEN 1 ELSE 0 END) AS bbox_ok,
            COUNT(DISTINCT vehicle_id) AS vehicles
        FROM {scan}
        """,
        label=f"speed_source_{agency_id}",
    ).iloc[0]
    return {k: row[k] for k in row.index}


def _derived_stats(agency_id: str) -> dict:
    scan = read_parquet_expr()
    df = execute_query(
        f"""
        SELECT vehicle_id, timestamp, bbox.ymin AS latitude, bbox.xmin AS longitude,
               ROUND(speed * 3.6, 2) AS speed_kmh
        FROM {scan}
        WHERE bbox.ymin IS NOT NULL AND bbox.xmin IS NOT NULL
        ORDER BY vehicle_id, timestamp
        LIMIT {SAMPLE_LIMIT}
        """,
        label=f"speed_derived_sample_{agency_id}",
    )
    if df.empty:
        return {"sample_rows": 0}
    enriched = apply_effective_speed_kmh(df, use_derived=True)
    derived = enriched["derived_speed_kmh"].dropna()
    src = enriched["speed_kmh"].dropna()
    return {
        "sample_rows": int(len(df)),
        "vehicles_in_sample": int(df["vehicle_id"].nunique()),
        "source_mean": round(float(src.mean()), 2) if not src.empty else None,
        "source_median": round(float(src.median()), 2) if not src.empty else None,
        "source_max": round(float(src.max()), 2) if not src.empty else None,
        "derived_mean": round(float(derived.mean()), 2) if not derived.empty else None,
        "derived_median": round(float(derived.median()), 2) if not derived.empty else None,
        "derived_max": round(float(derived.max()), 2) if not derived.empty else None,
        "valid_derived_pct": round(100 * len(derived) / max(len(df) - df["vehicle_id"].nunique(), 1), 2),
    }


def write_md(results: dict, probe: date) -> str:
    tl = results["translink"]
    lines = [
        "# TransLink Speed Validation",
        "",
        f"**Probe date:** {probe}",
        "",
        "## 1. Realtime data path (before fix)",
        "",
        "| Component | File | Function | Speed field |",
        "|-----------|------|----------|-------------|",
        "| Fleet Avg Speed KPI | `pages/01_Realtime.py` | `load_realtime_positions` → mean | `effective_speed_kmh` |",
        "| Speed Distribution | `pages/01_Realtime.py` | histogram of positions | `effective_speed_kmh` |",
        "| Route Summary avg/max | `pages/01_Realtime.py` | `load_realtime_route_summary` | `effective_avg/max_speed_kmh` |",
        "| Map hover | `pages/01_Realtime.py` | scatter_mapbox | `effective_speed_kmh` |",
        "| Source SQL (legacy) | `utils/real_data.py` | `load_route_summary`, `load_route_positions` | `speed * 3.6` (unchanged elsewhere) |",
        "",
        "## 2. Source issue — TransLink May 20, 2026",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Rows | {tl['source']['rows']:,} |",
        f"| Min speed (km/h) | {tl['source']['min_kmh']} |",
        f"| Mean speed (km/h) | {tl['source']['mean_kmh']} |",
        f"| Max speed (km/h) | {tl['source']['max_kmh']} |",
        f"| % speed == 0 or null | {tl['source']['pct_zero']}% |",
        f"| Rows with usable bbox lat/lon | {tl['source']['bbox_ok']:,} |",
        f"| Distinct vehicles | {tl['source']['vehicles']:,} |",
        f"| `agency_needs_derived_speed()` | **{tl['needs_derived']}** |",
        "",
        "**Root cause:** TransLink parquet `speed` and `bearing` are always 0; coordinates in `bbox` are valid and change over time.",
        "",
        "## 3. Fix — derived speed from consecutive GPS",
        "",
        "Module: `utils/speed_utils.py` → `compute_derived_speed_kmh`",
        "",
        "- Haversine distance between consecutive pings per `vehicle_id`",
        "- `speed_kmh = distance_m / elapsed_s × 3.6`",
        "- Filters: elapsed 5–600 s, distance > 0, speed ≤ 120 km/h",
        "- TransLink Realtime only: `effective_speed_kmh` = derived when source unusable",
        "- TTC / Edmonton: source speed unchanged",
        "",
        "## 4. Validation by agency",
        "",
        "| Agency | Source mean | Source max | Derived mean* | Derived max* | Valid derived % | Vehicles (sample) |",
        "|--------|------------:|-----------:|--------------:|-------------:|----------------:|------------------:|",
    ]
    for aid in AGENCIES:
        r = results[aid]
        d = r["derived"]
        lines.append(
            f"| {aid.upper()} | {d.get('source_mean', '—')} | {d.get('source_max', '—')} | "
            f"{d.get('derived_mean', '—')} | {d.get('derived_max', '—')} | "
            f"{d.get('valid_derived_pct', '—')} | {d.get('vehicles_in_sample', '—')} |"
        )
    lines += [
        "",
        "*For TTC/Edmonton, derived columns are computed for comparison only; Realtime UI still uses source speed.",
        "",
        "## 5. Expected Realtime outcome",
        "",
        "- **TransLink:** Avg Speed and Route Summary show plausible derived speeds (typically 15–35 km/h urban bus).",
        "- **TTC / Edmonton:** Unchanged (source speed).",
        "- **Reliability / Route Analysis / Network Indicators:** Not modified.",
        "",
        "Re-run: `python scripts/validate_translink_speed.py --date 2026-05-20`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE.isoformat())
    args = parser.parse_args()
    probe = date.fromisoformat(args.date)

    results = {}
    for agency_id in AGENCIES:
        print(f"Validating {agency_id}...")
        _bootstrap(agency_id, probe)
        results[agency_id] = {
            "source": _source_stats(agency_id),
            "derived": _derived_stats(agency_id),
            "needs_derived": agency_needs_derived_speed((agency_id, probe.isoformat(), "s3")),
        }

    out = ROOT / "docs" / "TRANSLINK_SPEED_VALIDATION.md"
    out.write_text(write_md(results, probe), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}")
    tl = results["translink"]
    print(f"TransLink pct zero speed: {tl['source']['pct_zero']}%")
    print(f"TransLink derived mean (sample): {tl['derived'].get('derived_mean')} km/h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
