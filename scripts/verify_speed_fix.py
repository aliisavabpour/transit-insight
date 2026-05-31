"""Post-fix metrics for TransLink speed pipeline (stdout only)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))


class _FakeSessionState(dict):
    def __getattr__(self, k):
        return self[k]

    def __setattr__(self, k, v):
        self[k] = v


class _FakeStreamlit:
    session_state = _FakeSessionState()

    def cache_resource(self, f):
        return f

    def cache_data(self, *a, **kw):
        def dec(f):
            store = {}

            def w(*args, **kwargs):
                agency = _FakeStreamlit.session_state.get("current_agency_id", "")
                key = (agency, args, tuple(sorted(kwargs.items())))
                if key not in store:
                    store[key] = f(*args, **kwargs)
                return store[key]

            return w

        if len(a) == 1 and callable(a[0]) and not kw:
            return dec(a[0])
        return dec


sys.modules["streamlit"] = _FakeStreamlit()
st = _FakeStreamlit


def _bootstrap(agency_id: str, probe: date) -> None:
    st.session_state.clear()
    st.session_state["current_agency_id"] = agency_id
    st.session_state[f"{agency_id}_data_source"] = "s3"
    st.session_state["snapshot_date"] = probe


def metrics(agency_id: str, probe: date) -> dict:
    _bootstrap(agency_id, probe)
    from utils.real_data import (
        agency_needs_derived_speed,
        cache_scope,
        load_realtime_positions,
        load_route_summary,
    )

    scope = cache_scope()
    summary = load_route_summary(scope)
    eff_routes = summary["effective_avg_speed_kmh"].dropna()
    top_routes = summary.head(10)["route_id"].astype(str).tolist()

    pos_frames = []
    for rid in top_routes:
        df = load_realtime_positions(rid, True, scope)
        if not df.empty:
            pos_frames.append(df)

    import pandas as pd

    all_pos = pd.concat(pos_frames, ignore_index=True) if pos_frames else pd.DataFrame()
    speeds = all_pos["effective_speed_kmh"].dropna() if not all_pos.empty else pd.Series(dtype=float)

    return {
        "agency": agency_id,
        "needs_derived": agency_needs_derived_speed(scope),
        "home_avg_route_speed_kmh": round(float(eff_routes.mean()), 2) if len(eff_routes) else None,
        "routes_with_effective_speed": int(len(eff_routes)),
        "realtime_top10_valid_samples": int(len(speeds)),
        "realtime_top10_avg_speed_kmh": round(float(speeds.mean()), 2) if len(speeds) else None,
    }


if __name__ == "__main__":
    probe = date(2026, 5, 20)
    for aid in ("translink", "ttc"):
        print(metrics(aid, probe))
