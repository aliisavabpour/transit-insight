"""
Agency GTFS-RT snapshot day selection.

All active agencies share a fixed May 2026 analysis window.
Default: DuckDB reads partitioned parquet directly from S3 (httpfs).
"""
from __future__ import annotations

import os
import shutil
from datetime import date
from urllib.error import URLError
from urllib.request import urlretrieve

import streamlit as st

from utils.agency_config import (
    AGENCIES,
    DEFAULT_SNAPSHOT_DATE,
    SHARED_ANALYSIS_END,
    SHARED_ANALYSIS_LABEL,
    SHARED_ANALYSIS_START,
)
from utils.agency_loader import (
    cache_path_for_date,
    get_current_agency_id,
    list_selectable_agencies,
    s3_glob_for_date,
    s3_https_url_for_date,
    set_current_agency_id,
)

_DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "../data"))
_LEGACY_PATH = os.path.join(_DATA_DIR, "positions_0.parquet")

_SESSION_KEY = "snapshot_date"


def is_date_in_shared_window(d: date) -> bool:
    return SHARED_ANALYSIS_START <= d <= SHARED_ANALYSIS_END


def get_shared_analysis_bounds() -> tuple[date, date]:
    return SHARED_ANALYSIS_START, SHARED_ANALYSIS_END


def get_selected_date() -> date:
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = DEFAULT_SNAPSHOT_DATE
    d = st.session_state[_SESSION_KEY]
    if not is_date_in_shared_window(d):
        st.session_state[_SESSION_KEY] = DEFAULT_SNAPSHOT_DATE
        return DEFAULT_SNAPSHOT_DATE
    return d


def s3_url_for_date(d: date) -> str:
    return s3_https_url_for_date(d)


def _legacy_cache_path(d: date) -> str:
    aid = get_current_agency_id()
    base = AGENCIES[aid]["positions_cache_dir"]
    os.makedirs(base, exist_ok=True)
    legacy = os.path.join(base, f"positions_{d:%Y%m%d}.parquet")
    if os.path.exists(legacy):
        return legacy
    return cache_path_for_date(d)


def _seed_cache_from_legacy(target: str, d: date) -> bool:
    if not os.path.exists(_LEGACY_PATH):
        return False
    if os.path.exists(target) and os.path.getsize(target) > 1000:
        return True
    if d == DEFAULT_SNAPSHOT_DATE and get_current_agency_id() == "ttc":
        shutil.copy2(_LEGACY_PATH, target)
        return True
    return False


def download_parquet_for_date(d: date) -> str:
    path = cache_path_for_date(d)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path

    legacy = _legacy_cache_path(d)
    if legacy != path and os.path.exists(legacy) and os.path.getsize(legacy) > 1000:
        shutil.copy2(legacy, path)
        return path
    if legacy == path and os.path.exists(legacy) and os.path.getsize(legacy) > 1000:
        return legacy

    if _seed_cache_from_legacy(path, d):
        return path

    url = s3_url_for_date(d)
    tmp = path + ".tmp"
    urlretrieve(url, tmp)
    if os.path.getsize(tmp) < 1000:
        os.remove(tmp)
        raise URLError(f"Downloaded file too small — check URL: {url}")
    os.replace(tmp, path)
    return path


def get_active_parquet_path() -> str:
    from utils.positions_store import positions_uri

    return positions_uri(get_selected_date())


def render_agency_sidebar() -> None:
    from utils.positions_store import (
        ensure_local_cache,
        get_data_source,
        probe_positions_available,
        set_data_source,
        source_caption,
    )

    st.sidebar.info(f"**Shared May analysis window:** {SHARED_ANALYSIS_LABEL}")

    selectable = list_selectable_agencies()
    labels = {aid: AGENCIES[aid]["short_name"] for aid in selectable}
    if selectable:
        idx = selectable.index(get_current_agency_id()) if get_current_agency_id() in selectable else 0
        picked = st.sidebar.selectbox(
            "Agency",
            selectable,
            index=idx,
            format_func=lambda x: labels[x],
        )
        if picked != get_current_agency_id():
            set_current_agency_id(picked)

    aid = get_current_agency_id()
    cfg = AGENCIES[aid]
    min_d, max_d = get_shared_analysis_bounds()
    prev = st.session_state.get(_SESSION_KEY)

    st.sidebar.markdown(f"### {cfg['short_name']} realtime data")
    selected = st.sidebar.date_input(
        "Snapshot day",
        value=get_selected_date(),
        min_value=min_d,
        max_value=max_d,
        help=(
            f"Same calendar window for all active agencies ({SHARED_ANALYSIS_LABEL}). "
            "DuckDB queries S3 directly by default."
        ),
    )

    from utils.positions_store import data_source_session_key

    ds_key = data_source_session_key()
    prev_source = st.session_state.get(ds_key)
    if selected != prev:
        st.session_state[_SESSION_KEY] = selected
        st.cache_data.clear()

    use_local = st.sidebar.checkbox(
        "Use local cache (offline fallback)",
        value=get_data_source() == "local",
        help="Download daily parquet (~90 MB+). Use if S3 queries fail.",
    )

    if use_local:
        if prev_source != "local":
            st.cache_data.clear()
        set_data_source("local")
        try:
            with st.spinner(f"Ensuring local cache for {selected}…"):
                path = ensure_local_cache(selected)
            st.sidebar.success(f"Local cache: `{os.path.basename(path)}`")
        except URLError as e:
            st.sidebar.error(f"Download failed: {e}")
            st.session_state.pop("positions_parquet_path", None)
    else:
        if prev_source == "local":
            st.cache_data.clear()
        set_data_source("s3")
        ok = probe_positions_available("s3", selected.isoformat())
        if ok:
            st.sidebar.success(f"S3 direct · **{selected.strftime('%B %d, %Y')}**")
            st.sidebar.caption(f"`{s3_glob_for_date(selected)}`")
        else:
            st.sidebar.warning(
                "S3 partition not reachable for this agency/day. "
                "Try another day in the shared window or enable local cache."
            )

    st.sidebar.caption(source_caption())

    if cfg.get("status") == "active":
        from utils.diagnostics_display import format_analysis_day_label, format_gps_coverage_range
        from utils.real_data import get_parquet_snapshot_info

        info = get_parquet_snapshot_info()
        if info.get("available"):
            st.sidebar.caption(f"Analysis day: {format_analysis_day_label(selected)}")
            st.sidebar.caption(
                f"GPS coverage: {format_gps_coverage_range(info.get('t_min'), info.get('t_max'))}"
            )
            if info.get("match_pct") is not None:
                st.sidebar.caption(f"GTFS trip match: ~{info['match_pct']:.0f}%")
                if info.get("matched_trips") is not None:
                    from utils.diagnostics_display import fmt_count

                    st.sidebar.caption(
                        f"Matched trips: {fmt_count(info.get('matched_trips'))} · "
                        f"Unmatched: {fmt_count(info.get('unmatched_trips'))}"
                    )


def render_ttc_date_sidebar() -> None:
    render_agency_sidebar()
