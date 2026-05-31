"""Tests for corridor-based reference points."""
from datetime import date

from utils.corridor_ref import load_route_corridor_ref, shapes_available


def test_translink_has_shapes():
    assert shapes_available("translink")


def test_edmonton_has_shapes():
    assert shapes_available("edmonton")


def test_corridor_ref_not_centroid_label():
    ref = load_route_corridor_ref("6636", "translink")
    assert ref is not None
    assert "centroid" not in ref["label"].lower()
    assert ref["source"] in ("shape_median", "shape_gps_refined", "busiest_stop")
    assert ref["lat"] and ref["lon"]


def test_corridor_ref_edmonton_route():
    ref = load_route_corridor_ref("009", "edmonton")
    assert ref is not None
    assert "Shape" in ref["label"] or "stop" in ref["label"].lower()
