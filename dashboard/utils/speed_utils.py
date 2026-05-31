"""
GPS-derived speed utilities for agencies with missing/zero source speed.

Used by the Realtime page when parquet `speed` is unusable (e.g. TransLink).
Reliability and Route Analysis are unchanged.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MIN_ELAPSED_SEC = 5
MAX_ELAPSED_SEC = 600
MAX_SPEED_KMH = 120.0

_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(
    lat1: np.ndarray | float,
    lon1: np.ndarray | float,
    lat2: np.ndarray | float,
    lon2: np.ndarray | float,
) -> np.ndarray:
    """Great-circle distance in meters between (lat1,lon1) and (lat2,lon2)."""
    lat1_r = np.radians(np.asarray(lat1, dtype=float))
    lon1_r = np.radians(np.asarray(lon1, dtype=float))
    lat2_r = np.radians(np.asarray(lat2, dtype=float))
    lon2_r = np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _lat_lon_columns(df: pd.DataFrame) -> tuple[str, str]:
    if "latitude" in df.columns and "longitude" in df.columns:
        return "latitude", "longitude"
    if "lat" in df.columns and "lon" in df.columns:
        return "lat", "lon"
    raise ValueError("DataFrame needs latitude/longitude or lat/lon columns")


def compute_derived_speed_kmh(df: pd.DataFrame) -> pd.Series:
    """
    Derive speed (km/h) from consecutive GPS points per vehicle_id.

    Expects columns: vehicle_id, timestamp, latitude/longitude (or lat/lon).
    Returns a Series aligned with df.index; NaN where filters fail or on first ping.
    """
    if df.empty:
        return pd.Series(dtype=float)

    lat_col, lon_col = _lat_lon_columns(df)
    required = {"vehicle_id", "timestamp", lat_col, lon_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for derived speed: {sorted(missing)}")

    out = pd.Series(np.nan, index=df.index, dtype=float)

    for _, grp in df.groupby("vehicle_id", sort=False):
        g = (
            grp.sort_values("timestamp")
            .dropna(subset=[lat_col, lon_col, "timestamp"])
            .drop_duplicates(subset=["timestamp"], keep="last")
        )
        if len(g) < 2:
            continue

        lat = g[lat_col].astype(float).to_numpy()
        lon = g[lon_col].astype(float).to_numpy()
        ts = pd.to_datetime(g["timestamp"], utc=True).astype("int64").to_numpy() // 10**9

        lat_prev, lat_curr = lat[:-1], lat[1:]
        lon_prev, lon_curr = lon[:-1], lon[1:]
        dt = (ts[1:] - ts[:-1]).astype(np.float64)

        dist_m = np.asarray(
            haversine_meters(lat_prev, lon_prev, lat_curr, lon_curr),
            dtype=np.float64,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            speed_kmh = dist_m / dt * 3.6

        valid = (
            np.isfinite(speed_kmh)
            & (dt >= MIN_ELAPSED_SEC)
            & (dt <= MAX_ELAPSED_SEC)
            & (dist_m > 0)
            & (speed_kmh <= MAX_SPEED_KMH)
        )
        for idx, spd in zip(g.index[1:], np.where(valid, speed_kmh, np.nan)):
            out.at[idx] = float(spd)

    return out


def is_source_speed_unusable(speed_kmh: pd.Series) -> bool:
    """True when speed column is missing, all null, or all zero."""
    if speed_kmh is None or speed_kmh.empty:
        return True
    valid = speed_kmh.dropna()
    if valid.empty:
        return True
    return (valid == 0).all()


def apply_effective_speed_kmh(df: pd.DataFrame, use_derived: bool) -> pd.DataFrame:
    """
    Add derived_speed_kmh and effective_speed_kmh columns.

    When use_derived is False (TTC, Edmonton, or TransLink with valid source speed),
    effective_speed_kmh equals source speed_kmh.
    When use_derived is True, effective_speed_kmh uses derived values (NaN if unknown).
    """
    result = df.copy()
    if "speed_kmh" not in result.columns and "speed" in result.columns:
        result["speed_kmh"] = result["speed"] * 3.6

    if use_derived:
        result["derived_speed_kmh"] = compute_derived_speed_kmh(result)
        result["effective_speed_kmh"] = result["derived_speed_kmh"]
    else:
        result["derived_speed_kmh"] = np.nan
        result["effective_speed_kmh"] = pd.to_numeric(result.get("speed_kmh"), errors="coerce")

    return result


def collapse_latest_per_vehicle(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per vehicle: latest GPS position; speed = last non-null effective_speed_kmh.

    TransLink often ends a trace with duplicate-timestamp pings (no movement), so the
    chronologically last row lacks a derived segment speed even when earlier rows have one.
    """
    if df.empty:
        return df
    rows: list[pd.Series] = []
    for _, grp in df.groupby("vehicle_id", sort=False):
        g = grp.sort_values("timestamp")
        row = g.iloc[-1].copy()
        if "effective_speed_kmh" in g.columns:
            valid = g["effective_speed_kmh"].dropna()
            row["effective_speed_kmh"] = float(valid.iloc[-1]) if len(valid) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)
