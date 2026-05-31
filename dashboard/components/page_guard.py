"""Shared guards and error surfacing for Streamlit pages."""
from __future__ import annotations

import streamlit as st

from utils.agency_config import AGENCIES, SHARED_ANALYSIS_LABEL
from utils.agency_loader import agency_gtfs_available, agency_is_analytics_ready, get_current_agency_id


def require_active_agency() -> None:
    """Stop the page if the selected agency is not ready for analytics."""
    aid = get_current_agency_id()
    cfg = AGENCIES.get(aid, {})
    name = cfg.get("short_name", aid)

    if cfg.get("status") != "active":
        st.error(
            f"**{name}** is not in the active May cohort. "
            f"{cfg.get('data_note', 'Data pending.')}"
        )
        if cfg.get("block_reason"):
            st.caption(cfg["block_reason"])
        st.info("Switch to **TTC**, **TransLink**, or **Edmonton** in the sidebar.")
        st.stop()

    if not agency_gtfs_available(aid):
        st.error(
            f"GTFS static feed not found for **{name}**. "
            f"Expected `trips.txt` under `{cfg.get('gtfs_dir', 'data/')}`."
        )
        st.stop()

    if not agency_is_analytics_ready(aid):
        st.error(
            f"GTFS-RT positions are not available for **{name}** on the selected day."
        )
        st.markdown(
            "- Pick a day in the **shared May window** ({SHARED_ANALYSIS_LABEL}), or  \n"
            "- Enable **Use local cache** in the sidebar."
        )
        st.stop()


def run_data_load(label: str, loader, *args, **kwargs):
    """Run a loader inside a spinner; show a clear error instead of a traceback."""
    try:
        with st.spinner(label):
            return loader(*args, **kwargs)
    except FileNotFoundError as exc:
        st.error(f"Required file not found: {exc}")
        st.stop()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Query failed: {type(exc).__name__}: {exc}")
        st.caption(
            "Try local cache mode, another day in the shared May window, "
            "or check DuckDB/S3 connectivity."
        )
        st.stop()
