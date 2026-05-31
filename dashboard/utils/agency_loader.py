"""
Multi-agency data paths and session context.

Centralizes S3 globs, local cache paths, GTFS directories, and timezone so
positions_store, gtfs_loader, and reliability share one configuration surface.
"""
from __future__ import annotations

import os
from datetime import date

from utils.agency_config import AGENCIES, agency_gtfs_available, get_agency_config

_SESSION_AGENCY_KEY = "current_agency_id"


def get_current_agency_id() -> str:
    try:
        import streamlit as st

        return st.session_state.get(_SESSION_AGENCY_KEY, "ttc")
    except Exception:
        return "ttc"


def set_current_agency_id(agency_id: str) -> None:
    if agency_id not in AGENCIES:
        raise ValueError(f"Unknown agency: {agency_id!r}")
    try:
        import streamlit as st

        prev = st.session_state.get(_SESSION_AGENCY_KEY)
        if prev != agency_id:
            st.session_state[_SESSION_AGENCY_KEY] = agency_id
            st.cache_data.clear()
    except Exception:
        pass


def get_active_agency_config() -> dict:
    cfg = get_agency_config(get_current_agency_id())
    if cfg is None:
        raise ValueError("No agency configuration for current session")
    return cfg


def list_selectable_agencies() -> list[str]:
    """Agencies shown in the sidebar selector (active only)."""
    return [aid for aid, cfg in AGENCIES.items() if cfg.get("status") == "active"]


def list_pending_agencies() -> list[str]:
    return [aid for aid, cfg in AGENCIES.items() if cfg.get("status") == "pending"]


def agency_is_analytics_ready(agency_id: str | None = None) -> bool:
    aid = agency_id or get_current_agency_id()
    cfg = get_agency_config(aid)
    if not cfg or cfg.get("status") != "active":
        return False
    if not agency_gtfs_available(aid):
        return False
    from utils.parquet_date import get_selected_date, is_date_in_shared_window
    from utils.positions_store import probe_agency_positions_available, get_data_source

    d = get_selected_date()
    if not is_date_in_shared_window(d):
        return False
    return probe_agency_positions_available(aid, get_data_source(), d.isoformat())


def gtfs_dir(agency_id: str | None = None) -> str:
    cfg = get_agency_config(agency_id or get_current_agency_id())
    if not cfg:
        raise ValueError("Unknown agency")
    return cfg["gtfs_dir"]


def gtfs_file_path(filename: str, agency_id: str | None = None) -> str:
    return os.path.join(gtfs_dir(agency_id), filename)


def positions_cache_dir(agency_id: str | None = None) -> str:
    cfg = get_agency_config(agency_id or get_current_agency_id())
    if not cfg:
        raise ValueError("Unknown agency")
    base = cfg.get("positions_cache_dir")
    if base:
        os.makedirs(base, exist_ok=True)
        return base
    return os.path.join(os.path.dirname(__file__), "../data/positions_cache")


def cache_path_for_date(d: date, agency_id: str | None = None) -> str:
    os.makedirs(positions_cache_dir(agency_id), exist_ok=True)
    aid = agency_id or get_current_agency_id()
    return os.path.join(positions_cache_dir(agency_id), f"{aid}_positions_{d:%Y%m%d}.parquet")


def s3_glob_for_date(d: date, agency_id: str | None = None) -> str:
    cfg = get_agency_config(agency_id or get_current_agency_id())
    if not cfg:
        raise ValueError("Unknown agency")
    template = cfg["s3_positions_glob"]
    return template.format(
        agency_id=cfg["agency_id"],
        year=d.year,
        month=f"{d.month:02d}",
        day=f"{d.day:02d}",
    )


def s3_https_url_for_date(d: date, agency_id: str | None = None) -> str:
    cfg = get_agency_config(agency_id or get_current_agency_id())
    if not cfg:
        raise ValueError("Unknown agency")
    return cfg["s3_https_template"].format(
        agency_id=cfg["agency_id"],
        year=d.year,
        month=f"{d.month:02d}",
        day=f"{d.day:02d}",
    )


def agency_timezone(agency_id: str | None = None) -> str:
    cfg = get_agency_config(agency_id or get_current_agency_id())
    return cfg.get("timezone", "America/Toronto") if cfg else "America/Toronto"


def data_source_session_key(agency_id: str | None = None) -> str:
    return f"{agency_id or get_current_agency_id()}_data_source"
