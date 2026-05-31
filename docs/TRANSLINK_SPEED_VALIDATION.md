# TransLink Speed Validation

**Probe date:** 2026-05-20

## 1. Realtime data path (before fix)

| Component | File | Function | Speed field |
|-----------|------|----------|-------------|
| Fleet Avg Speed KPI | `pages/01_Realtime.py` | `load_realtime_positions` → mean | `effective_speed_kmh` |
| Speed Distribution | `pages/01_Realtime.py` | histogram of positions | `effective_speed_kmh` |
| Route Summary avg/max | `pages/01_Realtime.py` | `load_realtime_route_summary` | `effective_avg/max_speed_kmh` |
| Map hover | `pages/01_Realtime.py` | scatter_mapbox | `effective_speed_kmh` |
| Source SQL (legacy) | `utils/real_data.py` | `load_route_summary`, `load_route_positions` | `speed * 3.6` (unchanged elsewhere) |

## 2. Source issue — TransLink May 20, 2026

| Metric | Value |
|--------|------:|
| Rows | 1,981,377.0 |
| Min speed (km/h) | 0.0 |
| Mean speed (km/h) | 0.0 |
| Max speed (km/h) | 0.0 |
| % speed == 0 or null | 100.0% |
| Rows with usable bbox lat/lon | 1,981,377.0 |
| Distinct vehicles | 1,482.0 |
| `agency_needs_derived_speed()` | **True** |

**Root cause:** TransLink parquet `speed` and `bearing` are always 0; coordinates in `bbox` are valid and change over time.

## 3. Fix — derived speed from consecutive GPS

Module: `utils/speed_utils.py` → `compute_derived_speed_kmh`

- Haversine distance between consecutive pings per `vehicle_id`
- `speed_kmh = distance_m / elapsed_s × 3.6`
- Filters: elapsed 5–600 s, distance > 0, speed ≤ 120 km/h
- TransLink Realtime only: `effective_speed_kmh` = derived when source unusable
- TTC / Edmonton: source speed unchanged

## 4. Validation by agency

| Agency | Source mean | Source max | Derived mean* | Derived max* | Valid derived % | Vehicles (sample) |
|--------|------------:|-----------:|--------------:|-------------:|----------------:|------------------:|
| TRANSLINK | 0.0 | 0.0 | 22.63 | 72.61 | 0.01 | 351 |
| TTC | 13.97 | 106.22 | 13.85 | 115.0 | 0.03 | 260 |
| EDMONTON | 18.04 | 112.65 | 63.91 | 115.02 | 0.0 | 448 |

*For TTC/Edmonton, derived columns are computed for comparison only; Realtime UI still uses source speed.

## 5. Expected Realtime outcome

- **TransLink:** Avg Speed and Route Summary show plausible derived speeds (typically 15–35 km/h urban bus).
- **TTC / Edmonton:** Unchanged (source speed).
- **Reliability / Route Analysis / Network Indicators:** Not modified.

Re-run: `python scripts/validate_translink_speed.py --date 2026-05-20`
