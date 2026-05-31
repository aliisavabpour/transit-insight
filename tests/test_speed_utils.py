"""Tests for GPS-derived speed utilities."""
import pandas as pd

from utils.speed_utils import (
    collapse_latest_per_vehicle,
    compute_derived_speed_kmh,
    is_source_speed_unusable,
)


def test_is_source_speed_unusable_all_zero():
    assert is_source_speed_unusable(pd.Series([0, 0, 0]))


def test_is_source_speed_unusable_has_values():
    assert not is_source_speed_unusable(pd.Series([0, 12.5, 0]))


def test_compute_derived_speed_kmh_basic():
    # ~111 km/h over 10s for ~0.0003 deg lat step at equator-ish
    df = pd.DataFrame({
        "vehicle_id": ["v1", "v1"],
        "timestamp": pd.to_datetime(["2026-05-20 10:00:00", "2026-05-20 10:00:10"], utc=True),
        "latitude": [49.0, 49.0003],
        "longitude": [-123.0, -123.0],
    })
    speeds = compute_derived_speed_kmh(df)
    assert pd.isna(speeds.iloc[0])
    assert speeds.iloc[1] > 10
    assert speeds.iloc[1] < 120


def test_collapse_latest_uses_last_valid_effective_speed():
    df = pd.DataFrame({
        "vehicle_id": ["v1", "v1", "v1"],
        "timestamp": pd.to_datetime(
            ["2026-05-20 10:00:00", "2026-05-20 10:00:10", "2026-05-20 10:00:10"],
            utc=True,
        ),
        "latitude": [49.0, 49.0003, 49.0003],
        "longitude": [-123.0, -123.0, -123.0],
        "effective_speed_kmh": [float("nan"), 25.0, float("nan")],
    })
    out = collapse_latest_per_vehicle(df)
    assert len(out) == 1
    assert out.iloc[0]["effective_speed_kmh"] == 25.0


def test_compute_derived_speed_rejects_short_interval():
    df = pd.DataFrame({
        "vehicle_id": ["v1", "v1"],
        "timestamp": pd.to_datetime(["2026-05-20 10:00:00", "2026-05-20 10:00:02"], utc=True),
        "latitude": [49.0, 49.001],
        "longitude": [-123.0, -123.0],
    })
    speeds = compute_derived_speed_kmh(df)
    assert pd.isna(speeds.iloc[1])
