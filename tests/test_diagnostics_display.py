"""Display-only helpers for diagnostics panels."""
from datetime import date

from utils.diagnostics_display import (
    NA,
    fmt_count,
    fmt_pct,
    format_analysis_day_label,
    format_gps_coverage_range,
)


def test_format_analysis_day_label():
    assert format_analysis_day_label(date(2026, 5, 20)) == "May 20, 2026"
    assert format_analysis_day_label(None) == NA


def test_format_gps_coverage_range():
    label = format_gps_coverage_range(
        "2026-05-19 23:50:00-04",
        "2026-05-20 23:59:59-04",
    )
    assert "May 19" in label
    assert "May 20" in label
    assert "→" in label
    assert format_gps_coverage_range(None, None) == NA


def test_fmt_pct_and_count():
    assert fmt_pct(None) == NA
    assert fmt_pct(100.0) == "100.0%"
    assert fmt_count(None) == NA
    assert fmt_count(None, computed=False) == NA
    assert fmt_count(0) == "0"
    assert fmt_count(1234) == "1,234"
