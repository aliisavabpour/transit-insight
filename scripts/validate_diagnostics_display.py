"""
Validate app-wide diagnostics display consistency (TTC, TransLink, Edmonton).

Usage:
  python scripts/validate_diagnostics_display.py --date 2026-05-20

Writes: docs/DIAGNOSTICS_DISPLAY_VALIDATION.md
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

import pandas as pd  # noqa: E402

from components.reliability_ui import build_network_diagnostics  # noqa: E402
from utils.agency_config import DEFAULT_SNAPSHOT_DATE  # noqa: E402
from utils.diagnostics_display import format_analysis_day_label  # noqa: E402
from utils.real_data import get_parquet_snapshot_info, snapshot_source_caption  # noqa: E402

AGENCIES = ("ttc", "translink", "edmonton")


def _bootstrap(agency_id: str, probe: date) -> None:
    st = sys.modules["streamlit"]
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = probe


def _check_trip_counts(info: dict) -> list[str]:
    issues: list[str] = []
    total = info.get("total_trips")
    matched = info.get("matched_trips")
    unmatched = info.get("unmatched_trips")
    match_pct = info.get("match_pct")

    if match_pct is not None:
        if total is None or matched is None or unmatched is None:
            issues.append("match_pct set but trip counts missing")
        elif matched + unmatched != total:
            issues.append(
                f"matched ({matched}) + unmatched ({unmatched}) != total ({total})"
            )
        else:
            expected = round(100 * matched / total, 1) if total else None
            if expected is not None and abs(expected - match_pct) > 0.05:
                issues.append(
                    f"match_pct {match_pct} != recomputed {expected}"
                )
    elif total is not None:
        issues.append("total_trips set but match_pct is None")

    return issues


def _check_network_diag(net: dict) -> list[str]:
    issues: list[str] = []
    computed = net.get("trips_match_computed", False)
    match_pct = net.get("match_pct")
    matched = net.get("matched_trips")
    unmatched = net.get("unmatched_trips")

    if match_pct is not None and not computed:
        issues.append("match_pct shown but trips_match_computed is False")
    if computed:
        if matched is None or unmatched is None:
            issues.append("trips_match_computed but counts are None")
    else:
        if matched not in (None, 0) or unmatched not in (None, 0):
            issues.append("trips not computed but counts are present")

    label = net.get("analysis_day_label", "")
    if "–" in label and "," in label:
        issues.append(f"analysis_day_label looks like a date span: {label}")

    gps = net.get("gps_coverage_label", "")
    if net.get("gps_t_min") and "→" not in gps:
        issues.append(f"GPS coverage label missing arrow: {gps}")

    return issues


def validate_agency(agency_id: str, probe: date) -> dict:
    _bootstrap(agency_id, probe)
    info = get_parquet_snapshot_info()
    caption = snapshot_source_caption() if info.get("available") else ""
    net = build_network_diagnostics(pd.DataFrame())

    issues = []
    if info.get("available"):
        issues.extend(_check_trip_counts(info))
        issues.extend(_check_network_diag(net))
        if "May 19–20" in caption or "May 19–20" in net.get("analysis_day_label", ""):
            issues.append("Confusing May 19–20 span in user-facing label")
        if "Analysis day:" not in caption:
            issues.append("snapshot_source_caption missing 'Analysis day:'")
        if "GPS coverage:" not in caption:
            issues.append("snapshot_source_caption missing 'GPS coverage:'")
        expected_day = format_analysis_day_label(probe)
        if net.get("analysis_day_label") != expected_day:
            issues.append(
                f"analysis_day_label {net.get('analysis_day_label')} != {expected_day}"
            )

    return {
        "agency": agency_id,
        "available": info.get("available", False),
        "match_pct": info.get("match_pct"),
        "total_trips": info.get("total_trips"),
        "matched_trips": info.get("matched_trips"),
        "unmatched_trips": info.get("unmatched_trips"),
        "analysis_day_label": net.get("analysis_day_label"),
        "gps_coverage_label": net.get("gps_coverage_label"),
        "trips_match_computed": net.get("trips_match_computed"),
        "caption_sample": caption[:120] + "..." if len(caption) > 120 else caption,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE.isoformat())
    args = parser.parse_args()
    probe = date.fromisoformat(args.date)

    lines = [
        "# Diagnostics display validation",
        "",
        f"Probe date: **{probe}**",
        "",
        "| Agency | Data | Match % | Total trips | Matched | Unmatched | Analysis day | Issues |",
        "|--------|------|---------|-------------|---------|-------------|--------------|--------|",
    ]

    any_fail = False
    for aid in AGENCIES:
        r = validate_agency(aid, probe)
        issues = r["issues"]
        if issues:
            any_fail = True
        issue_txt = "; ".join(issues) if issues else "OK"
        lines.append(
            f"| {aid} | {'yes' if r['available'] else 'no'} | "
            f"{r['match_pct'] if r['match_pct'] is not None else 'N/A'} | "
            f"{r['total_trips'] if r['total_trips'] is not None else 'N/A'} | "
            f"{r['matched_trips'] if r['matched_trips'] is not None else 'N/A'} | "
            f"{r['unmatched_trips'] if r['unmatched_trips'] is not None else 'N/A'} | "
            f"{r.get('analysis_day_label', 'N/A')} | {issue_txt} |"
        )

    lines.extend(["", "## Notes", "", "- Display-only changes; no reliability formulas altered.", ""])
    out = ROOT / "docs" / "DIAGNOSTICS_DISPLAY_VALIDATION.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    for aid in AGENCIES:
        r = validate_agency(aid, probe)
        print(f"{aid}: available={r['available']} issues={r['issues']}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
