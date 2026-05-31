"""Tests for service-day filtered scheduled headways."""
from datetime import date

from utils.gtfs_loader import build_active_service_ids_sql
from utils.reliability import _compute_scheduled_headways_cached


def test_active_service_ids_ttc_wednesday():
    sql = build_active_service_ids_sql(date(2026, 5, 20), "ttc")
    assert "calendar" in sql or "read_csv_auto" in sql
    assert "20260520" in sql
    assert "wednesday" in sql


def test_active_service_ids_edmonton_calendar_dates_only():
    sql = build_active_service_ids_sql(date(2026, 5, 20), "edmonton")
    assert "exception_type" in sql
    assert "20260520" in sql


def test_route504_hour9_service_day_filter():
    df = _compute_scheduled_headways_cached("504", date(2026, 5, 20))
    row = df[(df["direction_id"] == "0") & (df["hour"] == 9)]
    assert not row.empty
    assert int(row.iloc[0]["scheduled_trips"]) == 16
    assert float(row.iloc[0]["scheduled_headway_min"]) == 3.8


def test_route504_fewer_trips_than_unfiltered():
    filtered = _compute_scheduled_headways_cached("504", date(2026, 5, 20))
    peak = filtered[(filtered["direction_id"] == "0") & (filtered["hour"] == 9)]
    assert int(peak.iloc[0]["scheduled_trips"]) < 52
