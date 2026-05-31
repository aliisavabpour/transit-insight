"""
GTFS-RT positions access: DuckDB queries against partitioned S3 parquet (default)
or optional local cache fallback.

S3 layout:
  s3://gtfs-rt-etl-data/ttc/positions/year=YYYY/month=MM/day=DD/*.parquet
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st

# DuckDB tuning (see docs/OPTIMIZATION.md)
_DUCKDB_DIR = Path(__file__).resolve().parent.parent / ".duckdb"
_DUCKDB_TEMP = _DUCKDB_DIR / "tmp"
_DUCKDB_MEMORY_LIMIT = os.environ.get("DUCKDB_MEMORY_LIMIT", "4GB")
_DUCKDB_THREADS = int(os.environ.get("DUCKDB_THREADS", str(min(8, os.cpu_count() or 4))))

from utils.agency_loader import (
    agency_timezone,
    cache_path_for_date,
    data_source_session_key,
    get_current_agency_id,
    s3_glob_for_date as agency_s3_glob,
)
from utils.parquet_date import get_selected_date, download_parquet_for_date

logger = logging.getLogger(__name__)

POSITION_COLUMNS = (
    "trip_id",
    "route_id",
    "vehicle_id",
    "direction_id",
    "timestamp",
    "speed",
    "bearing",
    "bbox",
)

_QUERY_LOG_KEY = "duckdb_query_log"


def s3_glob_for_date(d: date | None = None) -> str:
    return agency_s3_glob(d or get_selected_date())


def get_data_source() -> str:
    """'s3' (default) or 'local' cache file."""
    key = data_source_session_key()
    return st.session_state.get(key, "s3")


def set_data_source(mode: str) -> None:
    st.session_state[data_source_session_key()] = mode


def positions_uri(d: date | None = None) -> str:
    """Active parquet URI/path for the selected snapshot day."""
    d = d or get_selected_date()
    if get_data_source() == "local":
        return cache_path_for_date(d)
    return s3_glob_for_date(d)


def read_parquet_expr(d: date | None = None) -> str:
    """DuckDB read_parquet(...) expression with hive partitioning."""
    uri = positions_uri(d).replace("'", "''")
    return f"read_parquet('{uri}', hive_partitioning = true)"


def _configure_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    """
    Session-scoped DuckDB settings for remote Parquet (S3 via httpfs).

    - parquet_metadata_cache: reuse footer/schema across scans (same connection).
    - enable_external_file_cache: in-RAM cache of remote byte ranges (default true).
    - enable_object_cache: legacy no-op in DuckDB 1.5.x — not set.
    """
    tz = agency_timezone().replace("'", "''")
    _DUCKDB_TEMP.mkdir(parents=True, exist_ok=True)
    temp_dir = str(_DUCKDB_TEMP).replace("'", "''")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute("SET parquet_metadata_cache = true;")
    con.execute("SET enable_external_file_cache = true;")
    con.execute(f"SET memory_limit = '{_DUCKDB_MEMORY_LIMIT}';")
    con.execute(f"SET threads = {_DUCKDB_THREADS};")
    con.execute(f"SET temp_directory = '{temp_dir}';")
    con.execute(f"SET timezone = '{tz}';")


@st.cache_resource
def _streamlit_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """One DuckDB connection per Streamlit server process (required for warm S3 cache)."""
    con = duckdb.connect()
    _configure_duckdb(con)
    return con


def duckdb_connect(*, ephemeral: bool = False) -> tuple[duckdb.DuckDBPyConnection, bool]:
    """
    Return (connection, should_close_after_use).

    Streamlit pages reuse a cached connection so enable_external_file_cache
    can serve repeated S3 scans. Scripts/tests pass ephemeral=True.
    """
    if ephemeral:
        con = duckdb.connect()
        _configure_duckdb(con)
        return con, True
    try:
        return _streamlit_duckdb_connection(), False
    except Exception:
        con = duckdb.connect()
        _configure_duckdb(con)
        return con, True


def get_duckdb_cache_settings() -> dict[str, str]:
    """Current cache-related settings on the active (or ephemeral) connection."""
    con, close = duckdb_connect(ephemeral=True)
    try:
        rows = con.execute(
            """
            SELECT name, value::VARCHAR AS value
            FROM duckdb_settings()
            WHERE name IN (
                'parquet_metadata_cache',
                'enable_external_file_cache',
                'enable_object_cache',
                'enable_http_metadata_cache',
                'memory_limit',
                'temp_directory',
                'threads'
            )
            ORDER BY name
            """
        ).fetchall()
        return {name: value for name, value in rows}
    finally:
        if close:
            con.close()


def _escape_route_id(route_id: str) -> str:
    rid = str(route_id).replace("'", "''")
    if not rid.replace("-", "").isalnum():
        raise ValueError(f"Invalid route_id: {route_id!r}")
    return rid


def positions_where_clause(
    route_id: str | None = None,
    require_trip_id: bool = False,
    d: date | None = None,
) -> str:
    """SQL WHERE fragment (without the WHERE keyword)."""
    parts: list[str] = []
    if route_id is not None:
        parts.append(f"route_id = '{_escape_route_id(route_id)}'")
    if require_trip_id:
        parts.append("trip_id IS NOT NULL")
    if get_data_source() == "local":
        day = d or get_selected_date()
        tz = agency_timezone().replace("'", "''")
        parts.append(
            f"DATE(timestamp AT TIME ZONE '{tz}') = DATE '{day.isoformat()}'"
        )
    if not parts:
        return "TRUE"
    return " AND ".join(parts)


def positions_subquery(
    route_id: str | None = None,
    require_trip_id: bool = False,
    d: date | None = None,
    alias: str = "p",
) -> str:
    """
  SQL subquery selecting only required columns from the active parquet source.

  Example: FROM ( ... ) AS p
    """
    cols = ", ".join(POSITION_COLUMNS)
    where = positions_where_clause(route_id, require_trip_id, d)
    scan = read_parquet_expr(d)
    return f"""
        (
            SELECT {cols}
            FROM {scan}
            WHERE {where}
        ) AS {alias}
    """


def execute_query(
    sql: str,
    label: str = "duckdb",
    params: list[Any] | None = None,
) -> pd.DataFrame:
    """Run SQL and log elapsed time; append to Streamlit session query log."""
    con, close = duckdb_connect()
    t0 = time.perf_counter()
    try:
        if params:
            df = con.execute(sql, params).df()
        else:
            df = con.execute(sql).df()
    finally:
        if close:
            con.close()
    elapsed = time.perf_counter() - t0
    logger.info("%s finished in %.2fs [%s]", label, elapsed, get_data_source())
    _record_query_timing(label, elapsed)
    return df


def execute_scalar(sql: str, label: str = "duckdb") -> Any:
    con, close = duckdb_connect()
    t0 = time.perf_counter()
    try:
        row = con.execute(sql).fetchone()
    finally:
        if close:
            con.close()
    elapsed = time.perf_counter() - t0
    logger.info("%s finished in %.2fs [%s]", label, elapsed, get_data_source())
    _record_query_timing(label, elapsed)
    return row[0] if row else None


def _record_query_timing(label: str, elapsed: float) -> None:
    try:
        log = st.session_state.setdefault(_QUERY_LOG_KEY, [])
        log.append({"label": label, "seconds": round(elapsed, 2), "source": get_data_source()})
        st.session_state[_QUERY_LOG_KEY] = log[-12:]
    except Exception:
        pass


def get_query_log() -> list[dict]:
    try:
        return list(st.session_state.get(_QUERY_LOG_KEY, []))
    except Exception:
        return []


def _parquet_probe_expr(d: date, agency_id: str, source: str) -> str:
    if source == "local":
        path = cache_path_for_date(d, agency_id).replace("'", "''")
        return f"read_parquet('{path}')"
    glob = agency_s3_glob(d, agency_id).replace("'", "''")
    return f"read_parquet('{glob}', hive_partitioning = true)"


@st.cache_data(ttl=300, show_spinner=False)
def probe_agency_positions_available(agency_id: str, source: str, day_iso: str) -> bool:
    """Lightweight availability check for a specific agency (S3 or local path)."""
    from utils.agency_config import get_agency_config

    d = date.fromisoformat(day_iso)
    if source == "local":
        path = cache_path_for_date(d, agency_id)
        return os.path.exists(path) and os.path.getsize(path) > 1000
    cfg = get_agency_config(agency_id) or {}
    tz = cfg.get("timezone", "UTC").replace("'", "''")
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs;")
        con.execute("LOAD httpfs;")
        con.execute(f"SET timezone = '{tz}';")
        try:
            con.execute(
                f"SELECT 1 FROM {_parquet_probe_expr(d, agency_id, source)} LIMIT 1"
            ).fetchone()
            return True
        finally:
            con.close()
    except Exception as exc:
        logger.warning("Positions probe failed %s %s: %s", agency_id, day_iso, exc)
        return False


@st.cache_data(ttl=300, show_spinner=False)
def probe_positions_available(source: str, day_iso: str) -> bool:
    return probe_agency_positions_available(get_current_agency_id(), source, day_iso)


def positions_available() -> bool:
    return probe_positions_available(get_data_source(), get_selected_date().isoformat())


def ensure_local_cache(d: date | None = None) -> str:
    """Download/cache parquet for offline use; switches source to local."""
    d = d or get_selected_date()
    path = download_parquet_for_date(d)
    set_data_source("local")
    st.session_state["positions_parquet_path"] = path
    return path


def source_caption() -> str:
    d = get_selected_date()
    if get_data_source() == "local":
        return (
            f"Source: local cache · {d.strftime('%B %d, %Y')} · "
            f"`{os.path.basename(cache_path_for_date(d))}`"
        )
    return f"Source: S3 parquet (DuckDB httpfs) · {d.strftime('%B %d, %Y')}"
