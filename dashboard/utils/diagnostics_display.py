"""
Shared formatting for data-quality diagnostics (display only — no metric logic).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

NA = "N/A"


def format_analysis_day_label(d: date | None) -> str:
    if d is None:
        return NA
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def format_gps_coverage_range(t_min: str | None, t_max: str | None) -> str:
    if not t_min or not t_max:
        return NA
    try:
        start = pd.to_datetime(t_min)
        end = pd.to_datetime(t_max)
        return f"{start.strftime('%b %d %H:%M')} → {end.strftime('%b %d %H:%M')}"
    except Exception:
        return f"{t_min} → {t_max}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return NA
    return f"{float(value):.1f}%"


def fmt_count(value: int | float | None, *, computed: bool = True) -> str:
    if not computed or value is None:
        return NA
    return f"{int(value):,}"


def snapshot_caption_parts(info: dict, analysis_day: date | None) -> tuple[str, str]:
    """Return (analysis_day_label, gps_coverage_label) for captions."""
    return (
        format_analysis_day_label(analysis_day),
        format_gps_coverage_range(info.get("t_min"), info.get("t_max")),
    )
