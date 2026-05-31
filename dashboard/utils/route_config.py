"""
Route configuration for the TTC + OC Transpo Bus Reliability Dashboard.

PRIMARY FOCUS: TTC bus routes, with Route 29 Dufferin as the main validated
example. TTC streetcar routes (501, 504, 510) are retained for comparative
analysis but are not the focus of this cross-agency bus reliability prototype.

OC Transpo routes will be registered here once the GTFS-RT parquet is
available. The same pipeline (virtual-stop headway, DuckDB, GTFS join)
applies unchanged.

Reference-point selection rationale
-------------------------------------
Each route has a fixed reference point placed at a high-traffic intersection
near the centre of its coverage area to maximise GPS pass-event density.
Pass-event radius: see REF_RADIUS_METERS in utils/reliability.py (default ~200 m).

TTC routes
  29  Dufferin  — Dufferin St & Bloor St     (mid-route transfer hub)  [BUS — primary demo]
  501 Queen     — Queen St & Yonge St         (downtown core)           [STREETCAR]
  504 King      — King St & Bay St            (downtown core)           [STREETCAR]
  510 Spadina   — Spadina Ave & King St       (southern terminus area)  [STREETCAR]

OC Transpo routes — to be added once parquet is ingested.
"""

from __future__ import annotations


# ── TTC Routes ────────────────────────────────────────────────────────────────

TTC_ROUTES: dict[str, dict] = {
    "29": {
        "route_id":       "29",
        "agency_id":      "ttc",
        "name":           "Dufferin",
        "full_name":      "29 — Dufferin",
        "vehicle_type":   "bus",
        "is_primary_demo": True,     # main validated bus example for this project
        "color":          "#66BB6A",
        "ref_point": {
            "lat":   43.6620,
            "lon":   -79.4422,
            "label": "Dufferin St & Bloor St",
        },
        "directions": {
            "0": "Southbound",
            "1": "Northbound",
        },
        "map_center": {"lat": 43.690, "lon": -79.440},
        "map_zoom":   12,
        "description": (
            "Major north–south TTC bus route along Dufferin Street, "
            "from Exhibition Place in the south to the York University area in the north. "
            "Primary validated bus example for this cross-agency reliability prototype."
        ),
    },
    "501": {
        "route_id":       "501",
        "agency_id":      "ttc",
        "name":           "Queen",
        "full_name":      "501 — Queen",
        "vehicle_type":   "streetcar",
        "is_primary_demo": False,
        "color":          "#FFA726",
        "ref_point": {
            "lat":   43.6502,
            "lon":   -79.3773,
            "label": "Queen St & Yonge St",
        },
        "directions": {
            "0": "Eastbound",
            "1": "Westbound",
        },
        "map_center": {"lat": 43.652, "lon": -79.385},
        "map_zoom":   12,
        "description": (
            "Toronto's longest streetcar route, running east–west along Queen Street "
            "from Long Branch in the west to Neville Park in the east."
        ),
    },
    "504": {
        "route_id":       "504",
        "agency_id":      "ttc",
        "name":           "King",
        "full_name":      "504 — King",
        "vehicle_type":   "streetcar",
        "is_primary_demo": False,
        "color":          "#42A5F5",
        "ref_point": {
            "lat":   43.6476,
            "lon":   -79.3814,
            "label": "King St & Bay St",
        },
        "directions": {
            "0": "Eastbound",
            "1": "Westbound",
        },
        "map_center": {"lat": 43.651, "lon": -79.385},
        "map_zoom":   12,
        "description": (
            "High-frequency TTC streetcar on King Street with two overlapping patterns: "
            "504A (→ Distillery District) and 504B (→ Broadview Station). "
            "Included as a streetcar benchmark alongside the bus focus routes."
        ),
    },
    "510": {
        "route_id":       "510",
        "agency_id":      "ttc",
        "name":           "Spadina",
        "full_name":      "510 — Spadina",
        "vehicle_type":   "streetcar",
        "is_primary_demo": False,
        "color":          "#EF5350",
        "ref_point": {
            "lat":   43.6458,
            "lon":   -79.3958,
            "label": "Spadina Ave & King St",
        },
        "directions": {
            "0": "Southbound",
            "1": "Northbound",
        },
        "map_center": {"lat": 43.675, "lon": -79.395},
        "map_zoom":   12,
        "description": (
            "North–south TTC streetcar along Spadina Avenue, "
            "connecting Union Station in the south to Spadina subway station in the north."
        ),
    },
}


# ── OC Transpo Routes — placeholder ──────────────────────────────────────────
# Routes will be registered here once the OC Transpo GTFS-RT parquet is loaded.
# The same fields as TTC routes apply; agency_id should be set to "octranspo".
#
# Example structure (to be populated):
# OC_TRANSPO_ROUTES: dict[str, dict] = {
#     "95": {
#         "route_id":     "95",
#         "agency_id":    "octranspo",
#         "name":         "Richmond",
#         "full_name":    "95 — Richmond",
#         "vehicle_type": "bus",
#         "is_primary_demo": True,
#         "color":        "#1E88E5",
#         "ref_point":    {"lat": ..., "lon": ..., "label": "..."},
#         ...
#     },
# }

OC_TRANSPO_ROUTES: dict[str, dict] = {}   # populated when data is loaded


# ── Combined registry ─────────────────────────────────────────────────────────

SUPPORTED_ROUTES: dict[str, dict] = {**TTC_ROUTES, **OC_TRANSPO_ROUTES}


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_route_config(route_id: str) -> dict | None:
    """Return config dict for a route, or None if not supported."""
    return SUPPORTED_ROUTES.get(str(route_id))


def get_supported_route_ids() -> list[str]:
    """All supported route IDs in ascending numeric order."""
    return sorted(SUPPORTED_ROUTES.keys(), key=lambda x: int(x))


def get_routes_for_agency(agency_id: str) -> dict[str, dict]:
    """Return all route configs for a given agency."""
    return {rid: cfg for rid, cfg in SUPPORTED_ROUTES.items()
            if cfg.get("agency_id") == agency_id}


def get_network_routes_for_agency(agency_id: str) -> dict[str, dict]:
    """
    Routes used on the Network Indicators page.
    Uses configured ref points when present; otherwise top parquet routes with
    corridor-based shape references (falls back to busiest stop if no shapes).
    """
    configured = get_routes_for_agency(agency_id)
    if configured:
        return configured

    from utils.corridor_ref import load_route_corridor_ref
    from utils.real_data import cache_scope, load_route_summary

    summary = load_route_summary(cache_scope())
    if summary.empty:
        return {}

    top = summary.nlargest(8, "records")
    specs: dict[str, dict] = {}
    for _, row in top.iterrows():
        rid = str(row["route_id"])
        corridor = load_route_corridor_ref(rid, agency_id)
        if not corridor:
            continue
        specs[rid] = {
            "route_id": rid,
            "agency_id": agency_id,
            "name": str(row.get("route_name", rid)),
            "full_name": f"{rid} — {row.get('route_name', rid)}",
            "vehicle_type": "bus",
            "ref_point": {
                "lat": corridor["lat"],
                "lon": corridor["lon"],
                "label": corridor["label"],
            },
            "directions": {"0": "Direction 0", "1": "Direction 1"},
        }
    return specs


def get_bus_route_ids(agency_id: str | None = None) -> list[str]:
    """Return route IDs where vehicle_type == 'bus', optionally filtered by agency."""
    return sorted(
        [rid for rid, cfg in SUPPORTED_ROUTES.items()
         if cfg.get("vehicle_type") == "bus"
         and (agency_id is None or cfg.get("agency_id") == agency_id)],
        key=lambda x: int(x) if x.isdigit() else x,
    )


def get_direction_label(route_id: str, direction_id: str | int) -> str:
    """Return human-readable direction label (e.g. 'Eastbound')."""
    cfg = SUPPORTED_ROUTES.get(str(route_id), {})
    return cfg.get("directions", {}).get(str(direction_id), f"Dir {direction_id}")


def get_route_color(route_id: str) -> str:
    """Return the brand colour hex for a route."""
    return SUPPORTED_ROUTES.get(str(route_id), {}).get("color", "#9E9E9E")
