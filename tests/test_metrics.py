import numpy as np

from utils.reliability import (
    PRIMARY_METRICS,
    compute_schedule_comparison,
    ADHERENCE_BAND_GOOD,
    ADHERENCE_BAND_MODERATE,
)


def test_primary_metrics_frozen():
    assert PRIMARY_METRICS == (
        "observed_headway",
        "scheduled_headway",
        "absolute_deviation",
        "relative_deviation",
    )


def test_schedule_comparison_perfect_match():
    out = compute_schedule_comparison(
        np.array([600.0, 900.0]),
        np.array([600.0, 900.0]),
    )
    assert list(out["abs_deviation_sec"]) == [0.0, 0.0]
    assert list(out["relative_deviation"]) == [0.0, 0.0]
    assert list(out["adherence_score"]) == [100.0, 100.0]
    assert list(out["adherence_band"]) == ["Good", "Good"]


def test_schedule_comparison_relative_deviation():
    out = compute_schedule_comparison(
        np.array([600.0]),
        np.array([900.0]),
    )
    assert out["abs_deviation_sec"][0] == 300.0
    assert abs(out["relative_deviation"][0] - 0.5) < 1e-9
    assert out["adherence_band"][0] == "Moderate"


def test_adherence_bands_thresholds():
    assert ADHERENCE_BAND_GOOD == 0.25
    assert ADHERENCE_BAND_MODERATE == 0.50
